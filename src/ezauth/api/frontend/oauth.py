from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from ezauth.config import settings
from ezauth.dependencies import AppDep, DbSession, RedisDep
from ezauth.models.application import Application
from ezauth.schemas.oauth import OAuthAuthorizeResponse
from ezauth.services.auth import AuthError
from ezauth.services.oauth import decode_state, exchange_code, get_authorization_url

router = APIRouter()


@router.get("/oauth/{provider}/authorize")
async def oauth_authorize(
    provider: str,
    app: AppDep,
    redis: RedisDep,
    redirect_url: str = "",
):
    """Get the OAuth authorization URL for a provider."""
    try:
        url = await get_authorization_url(app, redis, provider, redirect_url)
    except AuthError as e:
        raise HTTPException(status_code=400, detail=e.message)
    return OAuthAuthorizeResponse(authorization_url=url)


async def _resolve_app_from_state(db, state: str) -> Application:
    """Resolve the application from the state parameter's embedded publishable key."""
    state_data = decode_state(state)
    pk = state_data.get("pk")
    if not pk:
        raise AuthError("Missing publishable key in OAuth state", code="invalid_state")

    result = await db.execute(
        select(Application).where(Application.publishable_key == pk)
    )
    app = result.scalars().first()
    if app is None:
        raise AuthError("Invalid publishable key in OAuth state", code="invalid_state")
    return app


@router.get("/oauth/{provider}/callback")
async def oauth_callback_get(
    provider: str,
    request: Request,
    db: DbSession,
    redis: RedisDep,
    code: str = "",
    state: str = "",
    error: str = "",
    error_description: str = "",
):
    """Handle OAuth callback via GET redirect (Google)."""
    if error:
        # Provider returned an error — redirect back with error params
        try:
            state_data = decode_state(state) if state else {}
        except Exception:
            state_data = {}
        redirect_url = state_data.get("redirect_url", "/")
        params = urlencode(
            {"error": error, "error_description": error_description}
        )
        sep = "&" if "?" in redirect_url else "?"
        return RedirectResponse(
            url=f"{redirect_url}{sep}{params}",
            status_code=302,
        )

    return await _handle_callback(provider, request, db, redis, code, state)


@router.post("/oauth/{provider}/callback")
async def oauth_callback_post(
    provider: str,
    request: Request,
    db: DbSession,
    redis: RedisDep,
):
    """Handle OAuth callback via POST form_post (Apple)."""
    form = await request.form()
    code = form.get("code", "")
    state = form.get("state", "")
    id_token = form.get("id_token")
    error_val = form.get("error", "")

    if error_val:
        try:
            state_data = decode_state(state) if state else {}
        except Exception:
            state_data = {}
        redirect_url = state_data.get("redirect_url", "/")
        sep = "&" if "?" in redirect_url else "?"
        return RedirectResponse(
            url=f"{redirect_url}{sep}{urlencode({'error': error_val})}",
            status_code=302,
        )

    return await _handle_callback(
        provider, request, db, redis, code, state, id_token_hint=id_token
    )


async def _handle_callback(
    provider: str,
    request: Request,
    db,
    redis,
    code: str,
    state: str,
    id_token_hint: str | None = None,
):
    """Common handler for OAuth callbacks."""
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state parameter")

    try:
        app = await _resolve_app_from_state(db, state)
    except AuthError as e:
        raise HTTPException(status_code=400, detail=e.message)

    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")

    try:
        user, session, access_jwt, raw_refresh, redirect_url = await exchange_code(
            db, redis, app, provider, code, state,
            id_token_hint=id_token_hint,
            ip_address=ip,
            user_agent=ua,
        )
    except AuthError as e:
        # Redirect with error
        try:
            state_data = decode_state(state)
            redirect_url = state_data.get("redirect_url", "/")
        except Exception:
            redirect_url = "/"
        params = urlencode(
            {"error": e.code, "error_description": e.message}
        )
        sep = "&" if "?" in redirect_url else "?"
        return RedirectResponse(
            url=f"{redirect_url}{sep}{params}",
            status_code=302,
        )

    final_url = redirect_url or "/"
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
