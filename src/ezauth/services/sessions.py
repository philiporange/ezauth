import base64
import uuid
from datetime import datetime, timedelta, timezone

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from jose import jwt
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ezauth.config import settings
from ezauth.crypto import generate_token, hash_token
from ezauth.models.application import Application
from ezauth.models.session import Session
from ezauth.models.user import User


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

    access_jwt = mint_jwt(
        app=app, user=user, session_id=session.id,
        lifetime_seconds=jwt_lifetime_seconds,
    )

    return session, access_jwt, raw_refresh


def mint_jwt(
    *,
    app: Application,
    user: User,
    session_id: uuid.UUID,
    lifetime_seconds: int | None = None,
) -> str:
    now = datetime.now(timezone.utc)
    if lifetime_seconds is not None:
        exp = now + timedelta(seconds=lifetime_seconds)
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
    return jwt.encode(claims, app.jwk_private_pem, algorithm="RS256", headers={"kid": app.jwk_kid})


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

    new_jwt = mint_jwt(app=app, user=user, session_id=session.id)
    return session, new_jwt, new_raw_refresh


async def revoke_session(db: AsyncSession, *, session_id: uuid.UUID) -> bool:
    now = datetime.now(timezone.utc)
    stmt = (
        update(Session)
        .where(Session.id == session_id, Session.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    result = await db.execute(stmt)
    return result.rowcount > 0


def build_jwks(app: Application) -> dict:
    """Build JWKS response for an application."""
    private_key = load_pem_private_key(app.jwk_private_pem.encode(), password=None)
    public_key = private_key.public_key()
    public_numbers = public_key.public_numbers()

    n_bytes = (public_numbers.n.bit_length() + 7) // 8
    e_bytes = (public_numbers.e.bit_length() + 7) // 8

    def _int_to_base64url(n: int, length: int) -> str:
        data = n.to_bytes(length, byteorder="big")
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    jwk_public = {
        "kty": "RSA",
        "kid": app.jwk_kid,
        "use": "sig",
        "alg": "RS256",
        "n": _int_to_base64url(public_numbers.n, n_bytes),
        "e": _int_to_base64url(public_numbers.e, e_bytes),
    }

    return {"keys": [jwk_public]}
