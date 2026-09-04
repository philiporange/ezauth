"""Session endpoints: current user, logout and refresh-token rotation.

Logging out revokes the session row rather than only clearing the cookie,
because the access token is self-contained and would otherwise keep working
until it expired. Both session cookies are cleared with the domain and path
they were set with, so a deployment sharing a parent domain leaves nothing
behind.

Refresh accepts the token either in the request body, for API and native
callers that hold it themselves, or from the refresh cookie, which is what
browser sessions use to outlive the few minutes an access token is valid for.
Every refresh rotates the token and reissues both cookies.
"""

from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy import select

from ezauth.cookies import (
    clear_session_cookies,
    refresh_cookie_name,
    set_session_cookies,
)
from ezauth.dependencies import AppDep, DbSession, SessionDep
from ezauth.models.user import User
from ezauth.schemas.auth import MeResponse, RefreshRequest, SessionResponse
from ezauth.services.auth import logout
from ezauth.services.sessions import refresh_session

router = APIRouter()


@router.get("/me", response_model=MeResponse)
async def get_me(
    db: DbSession,
    app: AppDep,
    session: SessionDep,
):
    result = await db.execute(
        select(User).where(User.id == session.user_id, User.app_id == app.id)
    )
    user = result.scalars().first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return MeResponse(
        user_id=str(user.id),
        email=user.email,
        email_verified=user.email_verified_at is not None,
        is_bot=user.is_bot,
    )


@router.post("/sessions/logout")
async def logout_session(
    response: Response,
    db: DbSession,
    app: AppDep,
    session: SessionDep,
):
    await logout(
        db,
        session_id=session.session_id,
        app_id=session.app_id,
        user_id=session.user_id,
    )
    clear_session_cookies(response, app)
    return {"status": "logged_out"}


@router.post("/tokens/session", response_model=SessionResponse)
async def refresh_token(
    request: Request,
    response: Response,
    db: DbSession,
    app: AppDep,
    body: RefreshRequest | None = None,
):
    raw_refresh = body.refresh_token if body and body.refresh_token else None
    if not raw_refresh:
        raw_refresh = request.cookies.get(refresh_cookie_name(app))
    if not raw_refresh:
        raise HTTPException(status_code=401, detail="Missing refresh token")

    result = await refresh_session(db, raw_refresh_token=raw_refresh, app=app)
    if result is None:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

    session, access_jwt, new_refresh = result
    set_session_cookies(
        response, access_jwt=access_jwt, refresh_token=new_refresh, app=app
    )
    return SessionResponse(
        access_token=access_jwt,
        refresh_token=new_refresh,
        user_id=str(session.user_id),
        session_id=str(session.id),
    )
