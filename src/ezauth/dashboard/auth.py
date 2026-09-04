"""Dashboard authentication: email-code login, Redis sessions and CSRF.

Sign-in sends a 6-digit code to an owner address (tenant.owner_email or
application.owner_email) or to a superadmin listed in
`settings.dashboard_admin_emails`. Owner codes are recorded as auth_attempts
against one of the owner's applications and only ever stored as a hash;
superadmin codes for addresses that own no application live in Redis, also
hashed, with an attempt counter that burns the code after
`settings.max_code_attempts` wrong guesses. Issuing a code revokes every code
previously issued to that address, and both the send cooldown and the per-IP
and per-email rate limits are enforced in Redis.

Sessions are Redis keys holding {email, is_super, csrf} under
`settings.dashboard_session_ttl_seconds`, so they survive a restart and work
across worker processes. Every session carries a CSRF token: it is echoed in a
readable cookie and in every form, and `require_dashboard_auth` — the
dependency behind every authenticated dashboard route — rejects any unsafe
method whose `X-CSRF-Token` header or `csrf_token` field does not match the
token held with the session.

This module also owns the shared Jinja2 environment for the dashboard: the
directory is resolved from this file rather than the working directory, and a
context processor exposes `csrf_token` to every template.
"""

import json
import pathlib
import secrets
from dataclasses import dataclass

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from redis.asyncio import Redis
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ezauth.config import settings
from ezauth.crypto import constant_time_compare, generate_code, hash_token
from ezauth.dependencies import DbSession, RedisDep
from ezauth.models.application import Application
from ezauth.models.auth_attempt import AuthAttempt, AuthAttemptStatus, AuthAttemptType
from ezauth.models.tenant import Tenant
from ezauth.ratelimiter import RateLimiter, parse_limits
from ezauth.services.mail import MailService
from ezauth.services.tokens import consume_admin_login_code, create_auth_attempt

TEMPLATES_DIR = pathlib.Path(__file__).parent / "templates"

SESSION_COOKIE = "__dashboard_session"
CSRF_COOKIE = "__dashboard_csrf"
CSRF_HEADER = "X-CSRF-Token"
CSRF_FIELD = "csrf_token"

_SESSION_PREFIX = "dash:session:"
_CODE_PREFIX = "dash:code:"
_COOLDOWN_PREFIX = "dash:cooldown:"

_CODE_TTL = 900  # 15 minutes
_SEND_COOLDOWN = 60  # seconds between code emails per address
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})

router = APIRouter()


def _csrf_context(request: Request) -> dict:
    return {"csrf_token": getattr(request.state, "csrf_token", "")}


templates = Jinja2Templates(directory=str(TEMPLATES_DIR), context_processors=[_csrf_context])


@dataclass
class DashboardAuth:
    email: str
    is_super: bool


def _admin_emails() -> set[str]:
    return set(settings.dashboard_admin_email_list)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


async def _within_rate_limits(
    redis: Redis, request: Request, email: str, action: str, ip_spec: str, email_spec: str
) -> bool:
    """Consume one unit of the per-IP and per-email budget for this action."""
    ip_limiter = RateLimiter(
        redis,
        parse_limits(ip_spec),
        user_id=_client_ip(request),
        namespace=f"dash-{action}-ip",
    )
    email_limiter = RateLimiter(
        redis,
        parse_limits(email_spec),
        user_id=email,
        namespace=f"dash-{action}-email",
    )
    return await ip_limiter.check_and_consume() and await email_limiter.check_and_consume()


async def create_dashboard_session(redis: Redis, email: str, is_super: bool) -> tuple[str, str]:
    """Store a new session in Redis and return (session_id, csrf_token)."""
    session_id = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(32)
    await redis.setex(
        _SESSION_PREFIX + session_id,
        settings.dashboard_session_ttl_seconds,
        json.dumps({"email": email, "is_super": is_super, "csrf": csrf_token}),
    )
    return session_id, csrf_token


async def load_dashboard_session(redis: Redis, session_id: str) -> dict | None:
    raw = await redis.get(_SESSION_PREFIX + session_id)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


async def destroy_dashboard_session(redis: Redis, session_id: str) -> None:
    await redis.delete(_SESSION_PREFIX + session_id)


async def _submitted_csrf_token(request: Request) -> str:
    token = request.headers.get(CSRF_HEADER, "")
    if token:
        return token
    content_type = request.headers.get("content-type", "")
    if content_type.startswith(("application/x-www-form-urlencoded", "multipart/form-data")):
        form = await request.form()
        value = form.get(CSRF_FIELD, "")
        if isinstance(value, str):
            return value
    return ""


async def _require_csrf(request: Request, expected: str) -> None:
    if request.method in _SAFE_METHODS:
        return
    submitted = await _submitted_csrf_token(request)
    if not expected or not submitted or not constant_time_compare(submitted, expected):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")


async def require_dashboard_auth(request: Request, redis: RedisDep) -> DashboardAuth:
    """Resolve the dashboard identity and enforce CSRF on unsafe methods."""
    session_id = request.cookies.get(SESSION_COOKIE)
    session = await load_dashboard_session(redis, session_id) if session_id else None
    if session is None:
        raise HTTPException(status_code=302, headers={"Location": "/dashboard/login"})
    request.state.csrf_token = session.get("csrf", "")
    await _require_csrf(request, session.get("csrf", ""))
    return DashboardAuth(email=session["email"], is_super=bool(session["is_super"]))


async def require_superadmin(
    auth: DashboardAuth = Depends(require_dashboard_auth),
) -> DashboardAuth:
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


async def _revoke_pending_codes(db: AsyncSession, redis: Redis, email: str) -> None:
    """Kill every login code already outstanding for this address."""
    await db.execute(
        update(AuthAttempt)
        .where(
            AuthAttempt.type == AuthAttemptType.admin_login,
            func.lower(AuthAttempt.email) == email,
            AuthAttempt.status == AuthAttemptStatus.pending,
        )
        .values(status=AuthAttemptStatus.revoked)
    )
    await redis.delete(_CODE_PREFIX + email)


async def _store_admin_code(redis: Redis, email: str, code: str) -> None:
    await redis.setex(
        _CODE_PREFIX + email,
        _CODE_TTL,
        json.dumps({"hash": hash_token(code), "attempts": 0}),
    )


async def _consume_admin_code(redis: Redis, email: str, code: str) -> bool:
    """Check a superadmin code held in Redis, burning it once used or abused."""
    key = _CODE_PREFIX + email
    raw = await redis.get(key)
    if not raw:
        return False
    try:
        pending = json.loads(raw)
    except ValueError:
        await redis.delete(key)
        return False

    attempts = int(pending.get("attempts", 0)) + 1
    if attempts > settings.max_code_attempts:
        await redis.delete(key)
        return False
    if constant_time_compare(pending.get("hash", ""), hash_token(code)):
        await redis.delete(key)
        return True

    pending["attempts"] = attempts
    await redis.set(key, json.dumps(pending), keepttl=True)
    return False


async def _send_login_code(email: str, code: str) -> None:
    mail = MailService()
    await mail.send_template(
        "admin_login_code",
        email,
        "Your ezAuth Dashboard Code",
        {"confirmation_code": code, "app_name": "ezAuth", "name": "Admin"},
    )


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@router.post("/login")
async def login(request: Request, db: DbSession, redis: RedisDep):
    form = await request.form()
    email = (form.get("email", "") or "").strip().lower()
    if not email:
        return templates.TemplateResponse(
            "login.html", {"request": request, "error": "Email is required"}
        )

    if not await _within_rate_limits(
        redis,
        request,
        email,
        "login",
        settings.admin_auth_rate_limit_ip,
        settings.admin_auth_rate_limit_email,
    ):
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Too many attempts. Try again later."},
            status_code=429,
        )

    cooldown_key = _COOLDOWN_PREFIX + email
    if not await redis.set(cooldown_key, "1", ex=_SEND_COOLDOWN, nx=True):
        # Pretend success; the previously sent code is still valid.
        return templates.TemplateResponse(
            "login_verify.html", {"request": request, "email": email}
        )

    apps = await _owned_apps(db, email)
    await _revoke_pending_codes(db, redis, email)

    if apps:
        # One code, recorded against the first owned app.
        code = generate_code(6)
        await create_auth_attempt(
            db,
            app_id=apps[0].id,
            type=AuthAttemptType.admin_login,
            email=email,
            expire_minutes=_CODE_TTL // 60,
            code=code,
        )
        await _send_login_code(email, code)
    elif email in _admin_emails():
        code = generate_code(6)
        await _store_admin_code(redis, email, code)
        await _send_login_code(email, code)

    # Always show the verify page (don't leak whether the email matched).
    return templates.TemplateResponse(
        "login_verify.html", {"request": request, "email": email}
    )


async def _verify_code(db: AsyncSession, redis: Redis, email: str, code: str) -> bool:
    """Consume a pending login code for this email, from Postgres or Redis."""
    app_ids, _reason = await consume_admin_login_code(db, email=email, code=code)
    if app_ids:
        return True
    return await _consume_admin_code(redis, email, code)


@router.post("/login/verify")
async def login_verify(request: Request, db: DbSession, redis: RedisDep):
    form = await request.form()
    email = (form.get("email", "") or "").strip().lower()
    code = (form.get("code", "") or "").strip()

    if not email or not code:
        return templates.TemplateResponse(
            "login_verify.html",
            {"request": request, "email": email, "error": "Enter your code"},
        )

    if not await _within_rate_limits(
        redis,
        request,
        email,
        "verify",
        settings.admin_verify_rate_limit_ip,
        settings.admin_verify_rate_limit_email,
    ):
        return templates.TemplateResponse(
            "login_verify.html",
            {
                "request": request,
                "email": email,
                "error": "Too many attempts. Try again later.",
            },
            status_code=429,
        )

    if not await _verify_code(db, redis, email, code):
        return templates.TemplateResponse(
            "login_verify.html",
            {"request": request, "email": email, "error": "Invalid or expired code"},
        )

    session_id, csrf_token = await create_dashboard_session(
        redis, email, email in _admin_emails()
    )
    response = RedirectResponse(url="/dashboard", status_code=302)
    response.set_cookie(
        key=SESSION_COOKIE,
        value=session_id,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        max_age=settings.dashboard_session_ttl_seconds,
    )
    response.set_cookie(
        key=CSRF_COOKIE,
        value=csrf_token,
        httponly=False,
        secure=settings.session_cookie_secure,
        samesite="lax",
        max_age=settings.dashboard_session_ttl_seconds,
    )
    return response


@router.post("/logout")
async def logout(
    request: Request,
    redis: RedisDep,
    auth: DashboardAuth = Depends(require_dashboard_auth),
):
    session_id = request.cookies.get(SESSION_COOKIE)
    if session_id:
        await destroy_dashboard_session(redis, session_id)
    response = RedirectResponse(url="/dashboard/login", status_code=302)
    response.delete_cookie(SESSION_COOKIE)
    response.delete_cookie(CSRF_COOKIE)
    return response
