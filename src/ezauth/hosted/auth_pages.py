"""Server-rendered sign-in, sign-up and verification pages.

These pages are the fallback UI for applications that do not build their own,
so they take credentials directly from untrusted browsers. Every form carries a
double-submit CSRF token, because a cross-site post to the login form would
otherwise log a victim into an attacker's account. Code entry is rate limited
per address and per IP on top of the per-attempt counter enforced by the token
service, since a six-digit code is small enough to guess without both.

Redirect targets are resolved through the shared validator, so a page can only
send a browser back to a domain the application owns. The password reset flow
proves control of the address with a code or link, opens a session, and then
requires a new password to be set, which revokes the user's other sessions.
"""

import pathlib
import re
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from ezauth import cookies, csrf
from ezauth.config import settings
from ezauth.dependencies import AppDep, DbSession, RedisDep, SessionDep
from ezauth.models.application import Application
from ezauth.models.user import User
from ezauth.redirects import safe_redirect_url
from ezauth.services.auth import (
    AuthError,
    consume_code,
    enforce_code_rate_limits,
    set_password,
    signin_magic_link,
    signin_password,
    signup,
)
from ezauth.services.oauth import get_authorization_url

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_TEMPLATE_DIR = pathlib.Path(__file__).parent / "templates"

router = APIRouter()
templates = Jinja2Templates(directory=str(_TEMPLATE_DIR))

_ERROR_MESSAGES = {
    "rate_limited": "Too many attempts. Please try again later.",
    "invalid_credentials": "Invalid email or password.",
    "invalid_code": "Invalid or expired code.",
    "too_many_attempts": "Too many incorrect attempts. Request a new code.",
    "email_not_verified": "Verify your email address before signing in.",
    "invalid_redirect_url": "That redirect destination is not allowed.",
    "weak_password": "Password must be at least 8 characters.",
}


def _ctx(app: Application, request: Request, **kwargs) -> dict:
    """Build common template context, including the CSRF token for this browser."""
    oauth_providers = list((app.settings_json or {}).get("oauth_providers", {}).keys())
    return {
        "request": request,
        "app_name": app.name,
        "passwords_enabled": app.passwords_enabled,
        "verification_method": app.verification_method,
        "oauth_providers": oauth_providers,
        "csrf_token": csrf.issue_token(request),
        **kwargs,
    }


def _render(app: Application, request: Request, template: str, **kwargs):
    """Render a page and make sure the browser holds the matching CSRF cookie."""
    context = _ctx(app, request, **kwargs)
    response = templates.TemplateResponse(request, template, context)
    return csrf.attach_token(response, context["csrf_token"])


def _require_csrf(request: Request, form) -> None:
    if not csrf.verify(request, form.get(csrf.CSRF_FIELD_NAME)):
        raise HTTPException(status_code=403, detail="Invalid or missing CSRF token")


def _set_session_cookie(response, app: Application, access_jwt: str, refresh_token=None):
    return cookies.set_session_cookies(
        response, access_jwt=access_jwt, refresh_token=refresh_token, app=app
    )


def _after_email_sent(app: Application, email: str, flow_type: str, redirect_url: str):
    """Send the browser to code entry or to the check-your-email page."""
    if app.verification_method == "code":
        params = urlencode({"email": email, "type": flow_type, "redirect_url": redirect_url})
        return RedirectResponse(url=f"/auth/verify-code?{params}", status_code=302)
    params = urlencode({"email": email, "type": flow_type})
    return RedirectResponse(url=f"/auth/check-email?{params}", status_code=302)


# --- Login ---


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, app: AppDep, redirect_url: str | None = None):
    return _render(app, request, "login.html", redirect_url=redirect_url or "")


@router.post("/login")
async def login_submit(
    request: Request,
    db: DbSession,
    redis: RedisDep,
    app: AppDep,
):
    form = await request.form()
    _require_csrf(request, form)

    email = form.get("email", "").strip()
    password = form.get("password", "")
    redirect_url = form.get("redirect_url", "")
    strategy = form.get("strategy", "magic_link")
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")

    if not email or not _EMAIL_RE.match(email):
        return _render(
            app, request, "login.html",
            error="Please enter a valid email address.",
            email=email, redirect_url=redirect_url,
        )

    if not app.passwords_enabled:
        strategy = "magic_link"

    if strategy == "magic_link":
        try:
            await signin_magic_link(
                db, redis, app=app, email=email,
                redirect_url=redirect_url or None,
                ip_address=ip, user_agent=ua,
            )
        except AuthError as e:
            return _render(
                app, request, "login.html",
                error=_ERROR_MESSAGES.get(e.code, e.message),
                email=email, redirect_url=redirect_url,
            )
        return _after_email_sent(app, email, "signin", redirect_url)

    if not password:
        return _render(
            app, request, "login.html", error="Password is required.",
            email=email, redirect_url=redirect_url,
        )

    try:
        user, session, access_jwt, raw_refresh = await signin_password(
            db, redis, app=app, email=email, password=password,
            ip_address=ip, user_agent=ua,
        )
    except AuthError as e:
        return _render(
            app, request, "login.html",
            error=_ERROR_MESSAGES.get(e.code, e.message),
            email=email, redirect_url=redirect_url,
        )

    final_url = await safe_redirect_url(db, app, redirect_url or None)
    return _set_session_cookie(
        RedirectResponse(url=final_url, status_code=302), app, access_jwt, raw_refresh
    )


# --- Forgot password ---


@router.get("/forgot-password", response_class=HTMLResponse)
async def forgot_password_page(
    request: Request, app: AppDep, redirect_url: str | None = None
):
    return _render(app, request, "forgot_password.html", redirect_url=redirect_url or "")


@router.post("/forgot-password")
async def forgot_password_submit(
    request: Request,
    db: DbSession,
    redis: RedisDep,
    app: AppDep,
):
    form = await request.form()
    _require_csrf(request, form)

    email = form.get("email", "").strip()
    redirect_url = form.get("redirect_url", "")
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")

    if not email or not _EMAIL_RE.match(email):
        return _render(
            app, request, "forgot_password.html",
            error="Please enter a valid email address.",
            email=email, redirect_url=redirect_url,
        )

    try:
        await signin_magic_link(
            db, redis, app=app, email=email,
            redirect_url=redirect_url or None,
            ip_address=ip, user_agent=ua,
        )
    except AuthError as e:
        return _render(
            app, request, "forgot_password.html",
            error=_ERROR_MESSAGES.get(e.code, e.message),
            email=email, redirect_url=redirect_url,
        )

    return _after_email_sent(app, email, "reset", redirect_url)


# --- Set password (reached with a session, after proving email ownership) ---


@router.get("/set-password", response_class=HTMLResponse)
async def set_password_page(
    request: Request, app: AppDep, session: SessionDep, redirect_url: str = ""
):
    return _render(app, request, "set_password.html", redirect_url=redirect_url)


@router.post("/set-password")
async def set_password_submit(
    request: Request,
    db: DbSession,
    app: AppDep,
    session: SessionDep,
):
    form = await request.form()
    _require_csrf(request, form)

    password = form.get("password", "")
    confirm = form.get("confirm_password", "")
    redirect_url = form.get("redirect_url", "")

    if password != confirm:
        return _render(
            app, request, "set_password.html",
            error="Passwords do not match.", redirect_url=redirect_url,
        )

    result = await db.execute(
        select(User).where(User.id == session.user_id, User.app_id == app.id)
    )
    user = result.scalars().first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    try:
        await set_password(
            db, app=app, user=user, new_password=password,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    except AuthError as e:
        return _render(
            app, request, "set_password.html",
            error=_ERROR_MESSAGES.get(e.code, e.message), redirect_url=redirect_url,
        )

    final_url = await safe_redirect_url(db, app, redirect_url or None)
    response = RedirectResponse(url=f"/auth/login?redirect_url={final_url}", status_code=302)
    return cookies.clear_session_cookies(response, app)


# --- Signup ---


@router.get("/signup", response_class=HTMLResponse)
async def signup_page(request: Request, app: AppDep, redirect_url: str | None = None):
    return _render(app, request, "signup.html", redirect_url=redirect_url or "")


@router.post("/signup")
async def signup_submit(
    request: Request,
    db: DbSession,
    redis: RedisDep,
    app: AppDep,
):
    form = await request.form()
    _require_csrf(request, form)

    email = form.get("email", "").strip()
    password = form.get("password", "") or None
    redirect_url = form.get("redirect_url", "")
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")

    if not email or not _EMAIL_RE.match(email):
        return _render(
            app, request, "signup.html",
            error="Please enter a valid email address.",
            email=email, redirect_url=redirect_url,
        )

    if app.passwords_enabled and not password:
        return _render(
            app, request, "signup.html", error="Password is required.",
            email=email, redirect_url=redirect_url,
        )

    if app.passwords_enabled and password and len(password) < 8:
        return _render(
            app, request, "signup.html",
            error="Password must be at least 8 characters.",
            email=email, redirect_url=redirect_url,
        )

    if not app.passwords_enabled:
        password = None

    try:
        await signup(
            db, redis, app=app, email=email, password=password,
            redirect_url=redirect_url or None, ip_address=ip, user_agent=ua,
        )
    except AuthError as e:
        return _render(
            app, request, "signup.html",
            error=_ERROR_MESSAGES.get(e.code, e.message),
            email=email, redirect_url=redirect_url,
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
    return _render(
        app, request, "verify_code.html",
        email=email, type=type, redirect_url=redirect_url,
    )


@router.post("/verify-code")
async def verify_code_submit(
    request: Request,
    db: DbSession,
    redis: RedisDep,
    app: AppDep,
):
    form = await request.form()
    _require_csrf(request, form)

    email = form.get("email", "").strip()
    code = form.get("code", "").strip()
    redirect_url = form.get("redirect_url", "")
    flow_type = form.get("type", "signin")
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")

    if not code or len(code) != 6 or not code.isdigit():
        return _render(
            app, request, "verify_code.html",
            error="Please enter a valid 6-digit code.",
            email=email, type=flow_type, redirect_url=redirect_url,
        )

    try:
        await enforce_code_rate_limits(redis, app=app, email=email, ip_address=ip)
        user, session, access_jwt, raw_refresh, stored_redirect = await consume_code(
            db, email=email, code=code, app=app, ip_address=ip, user_agent=ua,
        )
    except AuthError as e:
        return _render(
            app, request, "verify_code.html",
            error=_ERROR_MESSAGES.get(e.code, e.message),
            email=email, type=flow_type, redirect_url=redirect_url,
        )

    if flow_type == "reset":
        target = f"/auth/set-password?{urlencode({'redirect_url': redirect_url})}"
        return _set_session_cookie(
            RedirectResponse(url=target, status_code=302), app, access_jwt, raw_refresh
        )

    final_url = await safe_redirect_url(db, app, stored_redirect or redirect_url or None)
    return _set_session_cookie(
        RedirectResponse(url=final_url, status_code=302), app, access_jwt, raw_refresh
    )


# --- Check email (for link-based verification) ---


@router.get("/check-email", response_class=HTMLResponse)
async def check_email_page(
    request: Request,
    app: AppDep,
    email: str = "",
    type: str = "signin",
):
    return _render(app, request, "check_email.html", email=email, type=type)


# --- OAuth ---


@router.get("/oauth/{provider}")
async def hosted_oauth_redirect(
    request: Request,
    provider: str,
    db: DbSession,
    app: AppDep,
    redis: RedisDep,
    redirect_url: str = "",
):
    """Start an OAuth flow, binding the state nonce to this browser."""
    try:
        url, state_secret = await get_authorization_url(
            db, app, redis, provider, redirect_url
        )
    except AuthError:
        return RedirectResponse(url="/auth/login", status_code=302)

    response = RedirectResponse(url=url, status_code=302)
    response.set_cookie(
        key=settings.oauth_state_cookie_name,
        value=state_secret,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        max_age=settings.oauth_state_ttl_seconds,
    )
    return response
