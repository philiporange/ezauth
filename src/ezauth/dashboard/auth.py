"""Dashboard authentication.

Email-code login with identity-carrying sessions. Owners (tenant.owner_email or
application.owner_email) get access scoped to their own resources; emails listed
in settings.dashboard_admin_emails get superadmin access to everything.

Owner login codes are stored as auth_attempts (tied to one of the owner's apps);
superadmin codes for emails that own no apps are kept in process memory, like the
sessions themselves. Sessions map an opaque cookie token to {email, is_super,
expires} in process memory, so a restart logs everyone out.
"""

import secrets
import time
from dataclasses import dataclass

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ezauth.config import settings
from ezauth.crypto import constant_time_compare, generate_code, hash_token
from ezauth.dependencies import get_db
from ezauth.models.application import Application
from ezauth.models.auth_attempt import AuthAttemptType
from ezauth.models.tenant import Tenant
from ezauth.services.mail import MailService
from ezauth.services.tokens import consume_auth_attempt_by_code, create_auth_attempt

router = APIRouter()
templates = Jinja2Templates(directory="src/ezauth/dashboard/templates")

_SESSION_TTL = 86400  # 24 hours
_CODE_TTL = 900  # 15 minutes
_SEND_COOLDOWN = 60  # seconds between code emails per address
_MAX_CODE_ATTEMPTS = 5

# session_id -> {"email": str, "is_super": bool, "expires": float}
_dashboard_sessions: dict[str, dict] = {}

# Superadmin codes for emails without owned apps: email -> {hash, expires, attempts}
_admin_codes: dict[str, dict] = {}

# email -> timestamp of last code send
_send_cooldown: dict[str, float] = {}


@dataclass
class DashboardAuth:
    email: str
    is_super: bool


def _admin_emails() -> set[str]:
    return {
        e.strip().lower()
        for e in settings.dashboard_admin_emails.split(",")
        if e.strip()
    }


def require_dashboard_auth(request: Request) -> DashboardAuth:
    session_id = request.cookies.get("__dashboard_session")
    session = _dashboard_sessions.get(session_id) if session_id else None
    if session is None or session["expires"] < time.time():
        if session_id:
            _dashboard_sessions.pop(session_id, None)
        raise HTTPException(status_code=302, headers={"Location": "/dashboard/login"})
    return DashboardAuth(email=session["email"], is_super=session["is_super"])


def require_superadmin(request: Request) -> DashboardAuth:
    auth = require_dashboard_auth(request)
    if not auth.is_super:
        raise HTTPException(status_code=403, detail="Superadmin access required")
    return auth


async def _owned_apps(db: AsyncSession, email: str) -> list[Application]:
    """Applications this email may administer: direct owner or tenant owner."""
    result = await db.execute(
        select(Application)
        .join(Tenant, Application.tenant_id == Tenant.id)
        .where(
            or_(
                func.lower(Application.owner_email) == email,
                func.lower(Tenant.owner_email) == email,
            )
        )
        .order_by(Application.created_at)
    )
    return list(result.scalars().all())


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@router.post("/login")
async def login(request: Request, db: AsyncSession = Depends(get_db)):
    form = await request.form()
    email = (form.get("email", "") or "").strip().lower()
    if not email:
        return templates.TemplateResponse(
            "login.html", {"request": request, "error": "Email is required"}
        )

    now = time.time()
    if _send_cooldown.get(email, 0) > now - _SEND_COOLDOWN:
        # Pretend success; the previously sent code is still valid.
        return templates.TemplateResponse(
            "login_verify.html", {"request": request, "email": email}
        )
    _send_cooldown[email] = now

    apps = await _owned_apps(db, email)

    if apps:
        # One code, recorded against the first owned app.
        code = generate_code(6)
        await create_auth_attempt(
            db,
            app_id=apps[0].id,
            type=AuthAttemptType.admin_login,
            email=email,
            expire_minutes=_CODE_TTL // 60,
            metadata={"code": code},
        )
        mail = MailService()
        await mail.send_template(
            "admin_login_code",
            email,
            "Your ezAuth Dashboard Code",
            {"confirmation_code": code, "app_name": "ezAuth", "name": "Admin"},
        )
    elif email in _admin_emails():
        # Superadmin with no owned apps: keep the code in process memory.
        code = generate_code(6)
        _admin_codes[email] = {
            "hash": hash_token(code),
            "expires": now + _CODE_TTL,
            "attempts": 0,
        }
        mail = MailService()
        await mail.send_template(
            "admin_login_code",
            email,
            "Your ezAuth Dashboard Code",
            {"confirmation_code": code, "app_name": "ezAuth", "name": "Admin"},
        )

    # Always show the verify page (don't leak whether the email matched).
    return templates.TemplateResponse(
        "login_verify.html", {"request": request, "email": email}
    )


async def _verify_code(db: AsyncSession, email: str, code: str) -> bool:
    """Consume a pending login code for this email, from DB or memory."""
    for app in await _owned_apps(db, email):
        attempt = await consume_auth_attempt_by_code(
            db, email=email, code=code, app_id=app.id
        )
        if attempt:
            return True

    pending = _admin_codes.get(email)
    if pending:
        if pending["expires"] < time.time():
            _admin_codes.pop(email, None)
            return False
        pending["attempts"] += 1
        if pending["attempts"] > _MAX_CODE_ATTEMPTS:
            _admin_codes.pop(email, None)
            return False
        if constant_time_compare(pending["hash"], hash_token(code)):
            _admin_codes.pop(email, None)
            return True
    return False


@router.post("/login/verify")
async def login_verify(request: Request, db: AsyncSession = Depends(get_db)):
    form = await request.form()
    email = (form.get("email", "") or "").strip().lower()
    code = (form.get("code", "") or "").strip()

    if not email or not code:
        return templates.TemplateResponse(
            "login_verify.html",
            {"request": request, "email": email, "error": "Enter your code"},
        )

    if not await _verify_code(db, email, code):
        return templates.TemplateResponse(
            "login_verify.html",
            {"request": request, "email": email, "error": "Invalid or expired code"},
        )

    session_id = secrets.token_urlsafe(32)
    _dashboard_sessions[session_id] = {
        "email": email,
        "is_super": email in _admin_emails(),
        "expires": time.time() + _SESSION_TTL,
    }
    response = RedirectResponse(url="/dashboard", status_code=302)
    response.set_cookie(
        key="__dashboard_session",
        value=session_id,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        max_age=_SESSION_TTL,
    )
    return response


@router.get("/logout")
async def logout(request: Request):
    session_id = request.cookies.get("__dashboard_session")
    if session_id:
        _dashboard_sessions.pop(session_id, None)
    response = RedirectResponse(url="/dashboard/login", status_code=302)
    response.delete_cookie("__dashboard_session")
    return response
