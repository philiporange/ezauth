import re
from urllib.parse import urlencode, urlparse

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from ezauth.config import settings
from ezauth.dependencies import AppDep, DbSession, RedisDep
from ezauth.models.application import Application
from ezauth.models.domain import Domain
from ezauth.services.auth import (
    AuthError, consume_code, signin_magic_link, signin_password, signup,
)

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

router = APIRouter()
templates = Jinja2Templates(directory="src/ezauth/hosted/templates")

_ERROR_MESSAGES = {
    "rate_limited": "Too many attempts. Please try again later.",
    "invalid_credentials": "Invalid email or password.",
    "invalid_code": "Invalid or expired code.",
    "user_exists": "An account with this email already exists.",
}


def _ctx(app: Application, request: Request, **kwargs) -> dict:
    """Build common template context."""
    return {
        "request": request,
        "app_name": app.name,
        "passwords_enabled": app.passwords_enabled,
        "verification_method": app.verification_method,
        **kwargs,
    }


async def _safe_redirect_url(
    redirect_url: str | None, app: Application, db=None
) -> str:
    """Validate redirect_url against app domains to prevent open redirects."""
    fallback = f"https://{app.primary_domain}" if app.primary_domain else "/"
    if not redirect_url:
        return fallback

    parsed = urlparse(redirect_url)
    host = parsed.hostname
    if not host:
        return fallback

    if host == app.primary_domain:
        return redirect_url

    if db is not None:
        result = await db.execute(
            select(Domain).where(
                Domain.app_id == app.id,
                Domain.domain == host,
                Domain.verified.is_(True),
            )
        )
        if result.scalars().first():
            return redirect_url

    return fallback


def _after_email_sent(app: Application, email: str, flow_type: str, redirect_url: str):
    """Redirect to the appropriate page after sending an email."""
    if app.verification_method == "code":
        params = urlencode({"email": email, "type": flow_type, "redirect_url": redirect_url})
        return RedirectResponse(url=f"/auth/verify-code?{params}", status_code=302)
    else:
        params = urlencode({"email": email, "type": flow_type})
        return RedirectResponse(url=f"/auth/check-email?{params}", status_code=302)


# --- Login ---


@router.get("/login", response_class=HTMLResponse)
async def login_page(
    request: Request, app: AppDep, redirect_url: str | None = None
):
    return templates.TemplateResponse(
        "login.html",
        _ctx(app, request, redirect_url=redirect_url or ""),
    )


@router.post("/login")
async def login_submit(
    request: Request,
    db: DbSession,
    redis: RedisDep,
    app: AppDep,
):
    form = await request.form()
    email = form.get("email", "").strip()
    password = form.get("password", "")
    redirect_url = form.get("redirect_url", "")
    strategy = form.get("strategy", "magic_link")
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")

    # Validate email
    if not email or not _EMAIL_RE.match(email):
        return templates.TemplateResponse(
            "login.html",
            _ctx(app, request, error="Please enter a valid email address.",
                 email=email, redirect_url=redirect_url),
        )

    # If passwords not enabled, force magic_link strategy
    if not app.passwords_enabled:
        strategy = "magic_link"

    if strategy == "magic_link":
        try:
            await signin_magic_link(
                db,
                redis,
                app=app,
                email=email,
                redirect_url=redirect_url or None,
                ip_address=ip,
                user_agent=ua,
            )
        except AuthError as e:
            return templates.TemplateResponse(
                "login.html",
                _ctx(app, request, error=_ERROR_MESSAGES.get(e.code, e.message),
                     email=email, redirect_url=redirect_url),
            )
        return _after_email_sent(app, email, "signin", redirect_url)

    # Password strategy (only reachable when passwords_enabled)
    if not password:
        return templates.TemplateResponse(
            "login.html",
            _ctx(app, request, error="Password is required.",
                 email=email, redirect_url=redirect_url),
        )

    try:
        user, session, access_jwt, raw_refresh = await signin_password(
            db,
            redis,
            app=app,
            email=email,
            password=password,
            ip_address=ip,
            user_agent=ua,
        )
    except AuthError as e:
        return templates.TemplateResponse(
            "login.html",
            _ctx(app, request, error=_ERROR_MESSAGES.get(e.code, e.message),
                 email=email, redirect_url=redirect_url),
        )

    final_url = await _safe_redirect_url(redirect_url or None, app, db)
    response = RedirectResponse(url=final_url, status_code=302)
    response.set_cookie(
        key=settings.session_cookie_name,
        value=access_jwt,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        domain=settings.session_cookie_domain or None,
    )
    return response


# --- Forgot password (sends code/link when passwords are enabled) ---


@router.get("/forgot-password", response_class=HTMLResponse)
async def forgot_password_page(
    request: Request, app: AppDep, redirect_url: str | None = None
):
    return templates.TemplateResponse(
        "forgot_password.html",
        _ctx(app, request, redirect_url=redirect_url or ""),
    )


@router.post("/forgot-password")
async def forgot_password_submit(
    request: Request,
    db: DbSession,
    redis: RedisDep,
    app: AppDep,
):
    form = await request.form()
    email = form.get("email", "").strip()
    redirect_url = form.get("redirect_url", "")
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")

    if not email or not _EMAIL_RE.match(email):
        return templates.TemplateResponse(
            "forgot_password.html",
            _ctx(app, request, error="Please enter a valid email address.",
                 email=email, redirect_url=redirect_url),
        )

    try:
        await signin_magic_link(
            db,
            redis,
            app=app,
            email=email,
            redirect_url=redirect_url or None,
            ip_address=ip,
            user_agent=ua,
        )
    except AuthError as e:
        return templates.TemplateResponse(
            "forgot_password.html",
            _ctx(app, request, error=_ERROR_MESSAGES.get(e.code, e.message),
                 email=email, redirect_url=redirect_url),
        )

    return _after_email_sent(app, email, "reset", redirect_url)


# --- Signup ---


@router.get("/signup", response_class=HTMLResponse)
async def signup_page(
    request: Request, app: AppDep, redirect_url: str | None = None
):
    return templates.TemplateResponse(
        "signup.html",
        _ctx(app, request, redirect_url=redirect_url or ""),
    )


@router.post("/signup")
async def signup_submit(
    request: Request,
    db: DbSession,
    redis: RedisDep,
    app: AppDep,
):
    form = await request.form()
    email = form.get("email", "").strip()
    password = form.get("password", "") or None
    redirect_url = form.get("redirect_url", "")
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")

    # Validate email
    if not email or not _EMAIL_RE.match(email):
        return templates.TemplateResponse(
            "signup.html",
            _ctx(app, request, error="Please enter a valid email address.",
                 email=email, redirect_url=redirect_url),
        )

    # Require password when passwords are enabled
    if app.passwords_enabled and not password:
        return templates.TemplateResponse(
            "signup.html",
            _ctx(app, request, error="Password is required.",
                 email=email, redirect_url=redirect_url),
        )

    if app.passwords_enabled and password and len(password) < 8:
        return templates.TemplateResponse(
            "signup.html",
            _ctx(app, request, error="Password must be at least 8 characters.",
                 email=email, redirect_url=redirect_url),
        )

    # Strip password if passwords are not enabled
    if not app.passwords_enabled:
        password = None

    try:
        await signup(
            db,
            redis,
            app=app,
            email=email,
            password=password,
            redirect_url=redirect_url or None,
            ip_address=ip,
            user_agent=ua,
        )
    except AuthError as e:
        return templates.TemplateResponse(
            "signup.html",
            _ctx(app, request, error=_ERROR_MESSAGES.get(e.code, e.message),
                 email=email, redirect_url=redirect_url),
        )

    return _after_email_sent(app, email, "verify", redirect_url)


# --- Verify code ---


@router.get("/verify-code", response_class=HTMLResponse)
async def verify_code_page(
    request: Request,
    app: AppDep,
    email: str = "",
    type: str = "signin",
    redirect_url: str = "",
):
    return templates.TemplateResponse(
        "verify_code.html",
        _ctx(app, request, email=email, type=type, redirect_url=redirect_url),
    )


@router.post("/verify-code")
async def verify_code_submit(
    request: Request,
    db: DbSession,
    app: AppDep,
):
    form = await request.form()
    email = form.get("email", "").strip()
    code = form.get("code", "").strip()
    redirect_url = form.get("redirect_url", "")
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")

    if not code or len(code) != 6 or not code.isdigit():
        return templates.TemplateResponse(
            "verify_code.html",
            _ctx(app, request, error="Please enter a valid 6-digit code.",
                 email=email, redirect_url=redirect_url),
        )

    try:
        user, session, access_jwt, raw_refresh, stored_redirect = await consume_code(
            db,
            email=email,
            code=code,
            app=app,
            ip_address=ip,
            user_agent=ua,
        )
    except AuthError as e:
        return templates.TemplateResponse(
            "verify_code.html",
            _ctx(app, request, error=_ERROR_MESSAGES.get(e.code, e.message),
                 email=email, redirect_url=redirect_url),
        )

    final_url = await _safe_redirect_url(
        stored_redirect or redirect_url or None, app, db
    )
    response = RedirectResponse(url=final_url, status_code=302)
    response.set_cookie(
        key=settings.session_cookie_name,
        value=access_jwt,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        domain=settings.session_cookie_domain or None,
    )
    return response


# --- Check email (for link-based verification) ---


@router.get("/check-email", response_class=HTMLResponse)
async def check_email_page(
    request: Request,
    app: AppDep,
    email: str = "",
    type: str = "signin",
):
    return templates.TemplateResponse(
        "check_email.html",
        _ctx(app, request, email=email, type=type),
    )
