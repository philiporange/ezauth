"""Session lifecycle: minting access tokens, rotating refresh tokens, revoking.

A session is a database row plus two credentials. The access token is a short
lived RS256 JWT signed with the application's own key and carrying the session
id in `sid`; the refresh token is a random string stored only as a SHA-256
digest and rotated on every refresh, so a captured refresh token stops working
as soon as the legitimate holder uses theirs. Because the access token is
self-contained, revocation would otherwise take effect only at expiry, so
`is_session_active` lets request authentication confirm the row on each call.
Backend-minted sign-in tokens are clamped to `max_signin_token_lifetime_seconds`
so no caller can request a token that outlives the revocation window by much.
"""

import uuid
from datetime import datetime, timedelta, timezone

from jose import jwt
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ezauth.config import settings
from ezauth.crypto import generate_token, hash_token
from ezauth.models.application import Application
from ezauth.models.session import Session
from ezauth.models.user import User
from ezauth.services import keys as key_service


async def create_session(
    db: AsyncSession,
    *,
    app: Application,
    user: User,
    jwt_lifetime_seconds: int | None = None,
) -> tuple[Session, str, str]:
    """Create a new session with JWT and refresh token.

    Returns (session, access_jwt, raw_refresh_token).
    """
    raw_refresh = generate_token(32)
    refresh_hash = hash_token(raw_refresh)

    session = Session(
        app_id=app.id,
        user_id=user.id,
        refresh_token_hash=refresh_hash,
        expires_at=datetime.now(timezone.utc)
        + timedelta(days=settings.jwt_refresh_token_expire_days),
    )
    db.add(session)
    await db.flush()

    signing_key = await key_service.active_key(db, app)
    access_jwt = mint_jwt(
        app=app,
        user=user,
        session_id=session.id,
        signing_kid=signing_key.kid,
        signing_pem=signing_key.private_pem,
        lifetime_seconds=jwt_lifetime_seconds,
    )

    return session, access_jwt, raw_refresh


def mint_jwt(
    *,
    app: Application,
    user: User,
    session_id: uuid.UUID,
    signing_kid: str,
    signing_pem: str,
    lifetime_seconds: int | None = None,
) -> str:
    now = datetime.now(timezone.utc)
    if lifetime_seconds is not None:
        capped = max(1, min(int(lifetime_seconds), settings.max_signin_token_lifetime_seconds))
        exp = now + timedelta(seconds=capped)
    else:
        exp = now + timedelta(minutes=settings.jwt_access_token_expire_minutes)
    claims = {
        "iss": f"https://{app.primary_domain or 'ezauth'}",
        "sub": str(user.id),
        "aud": str(app.id),
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "sid": str(session_id),
        "is_bot": user.is_bot,
    }
    if user.email:
        claims["email"] = user.email
        claims["email_verified"] = user.email_verified_at is not None
    else:
        claims["email_verified"] = False
    return jwt.encode(claims, signing_pem, algorithm="RS256", headers={"kid": signing_kid})


async def refresh_session(
    db: AsyncSession,
    *,
    raw_refresh_token: str,
    app: Application,
) -> tuple[Session, str, str] | None:
    """Refresh a session: rotate the refresh token, mint new JWT.

    Returns (session, new_access_jwt, new_raw_refresh) or None if invalid.
    """
    token_h = hash_token(raw_refresh_token)
    now = datetime.now(timezone.utc)

    stmt = select(Session).where(
        Session.refresh_token_hash == token_h,
        Session.app_id == app.id,
        Session.revoked_at.is_(None),
        Session.expires_at > now,
    )
    result = await db.execute(stmt)
    session = result.scalars().first()
    if session is None:
        return None

    # Load the user
    user_result = await db.execute(select(User).where(User.id == session.user_id))
    user = user_result.scalars().first()
    if user is None:
        return None

    # Rotate refresh token
    new_raw_refresh = generate_token(32)
    session.refresh_token_hash = hash_token(new_raw_refresh)
    session.last_seen_at = now
    session.session_version += 1
    await db.flush()

    signing_key = await key_service.active_key(db, app)
    new_jwt = mint_jwt(
        app=app,
        user=user,
        session_id=session.id,
        signing_kid=signing_key.kid,
        signing_pem=signing_key.private_pem,
    )
    return session, new_jwt, new_raw_refresh


async def is_session_active(
    db: AsyncSession, *, session_id: uuid.UUID, app_id: uuid.UUID
) -> bool:
    """Whether a session row is still usable, so revocation outlives the JWT.

    Access tokens are self-contained and live for minutes, so signature checks
    alone would keep a logged-out session working until expiry. Every
    cookie-authenticated request confirms the row here instead.
    """
    result = await db.execute(
        select(Session.id).where(
            Session.id == session_id,
            Session.app_id == app_id,
            Session.revoked_at.is_(None),
            Session.expires_at > datetime.now(timezone.utc),
        )
    )
    return result.first() is not None


async def revoke_session(db: AsyncSession, *, session_id: uuid.UUID) -> bool:
    now = datetime.now(timezone.utc)
    stmt = (
        update(Session)
        .where(Session.id == session_id, Session.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    result = await db.execute(stmt)
    return result.rowcount > 0


async def revoke_user_sessions(
    db: AsyncSession, *, user_id: uuid.UUID, app_id: uuid.UUID
) -> int:
    """Revoke every live session for a user, used when credentials change."""
    result = await db.execute(
        update(Session)
        .where(
            Session.user_id == user_id,
            Session.app_id == app_id,
            Session.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(timezone.utc))
    )
    return result.rowcount or 0


async def build_jwks(db: AsyncSession, app: Application) -> dict:
    """Publish every key whose signatures are still accepted for an application."""
    app_keys = await key_service.verification_keys(db, app)
    return {
        "keys": [key_service.public_jwk(k.kid, k.private_pem) for k in app_keys]
    }
