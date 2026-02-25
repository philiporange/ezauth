import secrets
import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ezauth.config import settings

router = APIRouter()
templates = Jinja2Templates(
    directory="src/ezauth/dashboard/templates"
)

# Simple session-based dashboard auth.
# Maps session_id -> expiry timestamp. In a multi-worker deployment, replace
# this with Redis-backed sessions.
_dashboard_sessions: dict[str, float] = {}

_SESSION_TTL = 86400  # 24 hours


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
async def login(request: Request):
    form = await request.form()
    password = form.get("password", "")
    if not secrets.compare_digest(str(password), settings.dashboard_secret_key):
        return templates.TemplateResponse(
            "login.html", {"request": request, "error": "Invalid password"}
        )
    session_id = secrets.token_urlsafe(32)
    _dashboard_sessions[session_id] = time.time() + _SESSION_TTL
    response = RedirectResponse(url="/dashboard/tenants", status_code=302)
    response.set_cookie(key="__dashboard_session", value=session_id, httponly=True)
    return response


@router.get("/logout")
async def logout(request: Request):
    session_id = request.cookies.get("__dashboard_session")
    if session_id:
        _dashboard_sessions.discard(session_id)
    response = RedirectResponse(url="/dashboard/login", status_code=302)
    response.delete_cookie("__dashboard_session")
    return response
