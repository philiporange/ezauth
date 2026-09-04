"""Backend session endpoints, authenticated with an application secret key.

Sign-in tokens let a trusted backend hand its own user a session without the
user re-authenticating. Their lifetime is clamped to the configured maximum,
because a self-contained token that outlives the revocation window cannot be
withdrawn once issued.
"""

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from ezauth.config import settings
from ezauth.dependencies import DbSession, SecretKeyApp
from ezauth.models.user import User
from ezauth.schemas.auth import SignInTokenRequest
from ezauth.services.sessions import create_session, revoke_session

router = APIRouter()


@router.post("/sessions/revoke")
async def revoke(
    db: DbSession,
    app: SecretKeyApp,
    session_id: uuid.UUID | None = None,
):
    if session_id is None:
        raise HTTPException(status_code=400, detail="session_id required")

    revoked = await revoke_session(db, session_id=session_id)
    if not revoked:
        raise HTTPException(status_code=404, detail="Session not found or already revoked")
    return {"status": "revoked"}


@router.post("/sign_in_tokens")
async def create_sign_in_token(
    body: SignInTokenRequest,
    db: DbSession,
    app: SecretKeyApp,
):
    """Create a short-lived sign-in token for a user (server-to-server)."""
    try:
        user_uuid = uuid.UUID(body.user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="user_id must be a UUID")

    user_result = await db.execute(
        select(User).where(User.id == user_uuid, User.app_id == app.id)
    )
    user = user_result.scalars().first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    lifetime = min(body.expires_in_seconds, settings.max_signin_token_lifetime_seconds)
    session, access_jwt, raw_refresh = await create_session(
        db, app=app, user=user, jwt_lifetime_seconds=lifetime,
    )

    return {
        "token": access_jwt,
        "refresh_token": raw_refresh,
        "user_id": str(user.id),
        "session_id": str(session.id),
        "expires_at": (
            datetime.now(timezone.utc) + timedelta(seconds=lifetime)
        ).isoformat(),
    }
