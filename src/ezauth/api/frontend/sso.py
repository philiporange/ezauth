import uuid

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from ezauth.config import settings
from ezauth.crypto import generate_token, hash_token
from ezauth.dependencies import AppDep, DbSession, RedisDep, SessionDep
from ezauth.models.user import User
from ezauth.services.sessions import create_session

router = APIRouter()


@router.get("/sso/bridge")
async def sso_bridge(
    return_to: str,
    request: Request,
    db: DbSession,
    redis: RedisDep,
    session: SessionDep,
):
    """Generate a one-time SSO token for cross-domain auth transfer."""
    token = generate_token(32)
    token_hash = hash_token(token)

    # Store user_id and app_id (for cross-app validation on exchange)
    await redis.setex(
        f"sso:{token_hash}",
        60,
        f"{session.user_id}:{session.app_id}",
    )

    separator = "&" if "?" in return_to else "?"
    redirect_url = f"{return_to}{separator}__sso_token={token}"
    return RedirectResponse(url=redirect_url, status_code=302)


@router.post("/sso/exchange")
async def sso_exchange(
    request: Request,
    response: Response,
    db: DbSession,
    redis: RedisDep,
    app: AppDep,
):
    """Exchange a one-time SSO token for a session cookie."""
    body = await request.json()
    token = body.get("token")
    if not token:
        raise HTTPException(status_code=400, detail="Missing token")

    token_hash = hash_token(token)
    key = f"sso:{token_hash}"

    # Atomic get + delete
    pipe = redis.pipeline()
    pipe.get(key)
    pipe.delete(key)
    results = await pipe.execute()

    stored = results[0]
    if not stored:
        raise HTTPException(status_code=401, detail="Invalid or expired SSO token")

    parts = stored.split(":")
    if len(parts) != 2:
        raise HTTPException(status_code=401, detail="Malformed SSO token data")

    user_id_str, source_app_id_str = parts

    # Validate the source app belongs to the same tenant as the target app
    from ezauth.models.application import Application

    source_app_result = await db.execute(
        select(Application).where(Application.id == uuid.UUID(source_app_id_str))
    )
    source_app = source_app_result.scalars().first()
    if source_app is None or source_app.tenant_id != app.tenant_id:
        raise HTTPException(status_code=403, detail="Cross-tenant SSO is not allowed")

    user_result = await db.execute(
        select(User).where(User.id == uuid.UUID(user_id_str))
    )
    user = user_result.scalars().first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    # Create a new session on the satellite domain
    session, access_jwt, raw_refresh = await create_session(db, app=app, user=user)

    response.set_cookie(
        key=settings.session_cookie_name,
        value=access_jwt,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
    )

    return {
        "access_token": access_jwt,
        "refresh_token": raw_refresh,
        "user_id": str(user.id),
        "session_id": str(session.id),
    }
