import secrets
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ezauth.crypto import generate_code
from ezauth.dependencies import get_db
from ezauth.models.application import Application
from ezauth.models.auth_attempt import AuthAttemptType
from ezauth.services.mail import MailService
from ezauth.services.tokens import create_auth_attempt, consume_auth_attempt_by_code

router = APIRouter()
templates = Jinja2Templates(
    directory="src/ezauth/dashboard/templates"
)

# Simple session-based dashboard auth.
_dashboard_sessions: dict[str, float] = {}

_SESSION_TTL = 86400  # 24 hours

# Temporary store for pending email verifications: email -> expiry
_pending_emails: dict[str, float] = {}


def require_dashboard_auth(request: Request):
    session_id = request.cookies.get("__dashboard_session")
    if not session_id or session_id not in _dashboard_sessions:
        raise HTTPException(status_code=302, headers={"Location": "/dashboard/login"})
    if _dashboard_sessions[session_id] < time.time():
        _dashboard_sessions.pop(session_id, None)
        raise HTTPException(status_code=302, headers={"Location": "/dashboard/login"})
    return session_id


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

    # Look up apps with this owner_email
    result = await db.execute(
        select(Application).where(func.lower(Application.owner_email) == email)
    )
    apps = result.scalars().all()

    # Send codes for matching apps (silently succeed if none match)
    for app in apps:
        code = generate_code(6)
        await create_auth_attempt(
            db,
            app_id=app.id,
            type=AuthAttemptType.admin_login,
            email=email,
            expire_minutes=15,
            metadata={"code": code},
        )
        mail = MailService(
            sender_name=app.email_from_name,
            sender_address=app.email_from_address,
        )
        await mail.send_template(
            "admin_login_code",
            email,
            "Your EZAuth Dashboard Code",
            {"confirmation_code": code, "app_name": app.name, "name": "Admin"},
        )

    # Always show the verify page (don't leak whether email matched)
    _pending_emails[email] = time.time() + 900  # 15 min
    return templates.TemplateResponse(
        "login_verify.html", {"request": request, "email": email}
    )


@router.post("/login/verify")
async def login_verify(request: Request, db: AsyncSession = Depends(get_db)):
    form = await request.form()
    email = (form.get("email", "") or "").strip().lower()
    code = (form.get("code", "") or "").strip()

    if not email or not code:
        return templates.TemplateResponse(
            "login_verify.html", {"request": request, "email": email, "error": "Enter your code"}
        )

    # Try to consume across all apps for this owner_email
    result = await db.execute(
        select(Application).where(func.lower(Application.owner_email) == email)
    )
    apps = result.scalars().all()

    consumed = False
    for app in apps:
        attempt = await consume_auth_attempt_by_code(
            db, email=email, code=code, app_id=app.id
        )
        if attempt:
            consumed = True
            break

    if not consumed:
        return templates.TemplateResponse(
            "login_verify.html", {"request": request, "email": email, "error": "Invalid or expired code"}
        )

    _pending_emails.pop(email, None)
    session_id = secrets.token_urlsafe(32)
    _dashboard_sessions[session_id] = time.time() + _SESSION_TTL
    response = RedirectResponse(url="/dashboard/tenants", status_code=302)
    response.set_cookie(key="__dashboard_session", value=session_id, httponly=True)
    return response


@router.get("/logout")
async def logout(request: Request):
    session_id = request.cookies.get("__dashboard_session")
    if session_id:
        _dashboard_sessions.pop(session_id, None)
    response = RedirectResponse(url="/dashboard/login", status_code=302)
    response.delete_cookie("__dashboard_session")
    return response
