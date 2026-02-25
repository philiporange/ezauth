from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ezauth.config import settings
from ezauth.dependencies import AppDep, DbSession, SessionDep
from ezauth.models.user import User
from ezauth.schemas.auth import MeResponse, RefreshRequest, SessionResponse
from ezauth.services.auth import logout
from ezauth.services.sessions import refresh_session

router = APIRouter()


@router.get("/me", response_model=MeResponse)
async def get_me(
    db: DbSession,
    session: SessionDep,
):
    result = await db.execute(select(User).where(User.id == session.user_id))
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
    session: SessionDep,
):
    await logout(
        db,
        session_id=session.session_id,
        app_id=session.app_id,
        user_id=session.user_id,
    )
    response.delete_cookie(key=settings.session_cookie_name)
    return {"status": "logged_out"}


@router.post("/tokens/session", response_model=SessionResponse)
async def refresh_token(
    body: RefreshRequest,
    db: DbSession,
    app: AppDep,
):
    result = await refresh_session(db, raw_refresh_token=body.refresh_token, app=app)
    if result is None:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

    session, access_jwt, new_refresh = result
    return SessionResponse(
        access_token=access_jwt,
        refresh_token=new_refresh,
        user_id=str(session.user_id),
        session_id=str(session.id),
    )
