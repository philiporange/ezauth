"""OAuth authorization and callback endpoints for Google and Apple.

Starting a flow returns the provider's authorization URL and sets a state
cookie on the browser; the callback requires that cookie to match the record
the service stored when the flow began, which is what stops a captured callback
URL from being replayed against a different browser.

Everything the callback needs beyond the authorization code is read from that
server-side record, never from the `state` parameter, so the destination of the
final redirect cannot be steered by editing the callback URL. Error responses
from the provider follow the same rule: the redirect target comes from the
stored record, and falls back to the application's own origin when no valid
state accompanies the error.
"""

from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from ezauth.config import settings
from ezauth.cookies import set_session_cookies
from ezauth.dependencies import AppDep, DbSession, RedisDep
from ezauth.models.application import Application
from ezauth.redirects import app_base_url, safe_redirect_url
from ezauth.schemas.oauth import OAuthAuthorizeResponse
from ezauth.services.auth import AuthError
from ezauth.services.oauth import (
    consume_state,
    decode_state,
    exchange_code,
    get_authorization_url,
)

router = APIRouter()


def _set_state_cookie(response: Response, state_secret: str) -> None:
    response.set_cookie(
        key=settings.oauth_state_cookie_name,
        value=state_secret,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        max_age=settings.oauth_state_ttl_seconds,
    )


def _clear_state_cookie(response: Response) -> None:
    response.delete_cookie(key=settings.oauth_state_cookie_name)


@router.get("/oauth/{provider}/authorize")
async def oauth_authorize(
    provider: str,
    response: Response,
    db: DbSession,
    app: AppDep,
    redis: RedisDep,
    redirect_url: str = "",
):
    """Return the provider authorization URL and bind the flow to this browser."""
    try:
        url, state_secret = await get_authorization_url(db, app, redis, provider, redirect_url)
    except AuthError as e:
        raise HTTPException(status_code=400, detail=e.message)

    _set_state_cookie(response, state_secret)
    return OAuthAuthorizeResponse(authorization_url=url)


async def _app_from_state(db, state: str) -> Application:
    """Resolve the application from the publishable key embedded in the state."""
    state_data = decode_state(state)
    pk = state_data.get("pk")
    if not pk:
        raise AuthError("Missing publishable key in OAuth state", code="invalid_state")

    result = await db.execute(select(Application).where(Application.publishable_key == pk))
    app = result.scalars().first()
    if app is None:
        raise AuthError("Invalid publishable key in OAuth state", code="invalid_state")
    return app


async def _provider_error_redirect(db, redis, state: str, params: dict):
    """Send the browser back to the stored redirect target with error details."""
    target = "/"
    try:
        app = await _app_from_state(db, state) if state else None
        if app is not None:
            record = await consume_state(redis, state)
            target = await safe_redirect_url(db, app, record.get("redirect_url") or None)
    except AuthError:
        target = "/"
    except Exception:
        target = "/"

    sep = "&" if "?" in target else "?"
    response = RedirectResponse(url=f"{target}{sep}{urlencode(params)}", status_code=302)
    _clear_state_cookie(response)
    return response


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
    """Handle the OAuth callback delivered as a GET redirect (Google)."""
    if error:
        return await _provider_error_redirect(
            db, redis, state, {"error": error, "error_description": error_description}
        )
    return await _handle_callback(provider, request, db, redis, code, state)


@router.post("/oauth/{provider}/callback")
async def oauth_callback_post(
    provider: str,
    request: Request,
    db: DbSession,
    redis: RedisDep,
):
    """Handle the OAuth callback delivered as a form post (Apple)."""
    form = await request.form()
    code = form.get("code", "")
    state = form.get("state", "")
    error_val = form.get("error", "")

    if error_val:
        return await _provider_error_redirect(db, redis, state, {"error": error_val})

    return await _handle_callback(provider, request, db, redis, code, state)


async def _handle_callback(
    provider: str,
    request: Request,
    db,
    redis,
    code: str,
    state: str,
):
    """Verify the callback, exchange the code and open a session."""
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state parameter")

    try:
        app = await _app_from_state(db, state)
    except AuthError as e:
        raise HTTPException(status_code=400, detail=e.message)

    state_secret = request.cookies.get(settings.oauth_state_cookie_name)

    try:
        record = await consume_state(redis, state)
    except AuthError as e:
        raise HTTPException(status_code=400, detail=e.message)

    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")

    try:
        user, session, access_jwt, raw_refresh, redirect_url = await exchange_code(
            db,
            redis,
            app,
            provider,
            code,
            record,
            state_secret,
            ip_address=ip,
            user_agent=ua,
        )
    except AuthError as e:
        target = await safe_redirect_url(db, app, record.get("redirect_url") or None)
        sep = "&" if "?" in target else "?"
        params = urlencode({"error": e.code, "error_description": e.message})
        response = RedirectResponse(url=f"{target}{sep}{params}", status_code=302)
        _clear_state_cookie(response)
        return response

    final_url = await safe_redirect_url(db, app, redirect_url or None) or app_base_url(app)
    response = set_session_cookies(
        RedirectResponse(url=final_url, status_code=302),
        access_jwt=access_jwt,
        refresh_token=raw_refresh,
        app=app,
    )
    _clear_state_cookie(response)
    return response
