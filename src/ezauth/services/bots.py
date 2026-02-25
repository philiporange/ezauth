"""Bot authentication via Ed25519 public key signatures.

Bots sign up by presenting a confirmed donation challenge from the confirmations
API and an Ed25519 public key. They authenticate by signing a canonical message
containing the app ID, bot ID, and timestamp. The server verifies the signature
against the stored public key and issues a standard session.
"""

import base64
import time
import uuid

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ezauth.config import settings
from ezauth.models.application import Application
from ezauth.models.session import Session
from ezauth.models.user import User
from ezauth.ratelimiter import RateLimiter
from ezauth.services import audit, sessions
from ezauth.services.auth import AuthError, _parse_rate_limit


def _validate_public_key(public_key_b64: str) -> bytes:
    """Decode and validate a base64-encoded Ed25519 public key. Returns raw 32 bytes."""
    try:
        raw = base64.b64decode(public_key_b64)
    except Exception:
        raise AuthError("Invalid public key encoding (expected base64)", code="invalid_key")
    if len(raw) != 32:
        raise AuthError("Invalid Ed25519 public key (expected 32 bytes)", code="invalid_key")
    # Verify it's a valid Ed25519 key by loading it
    try:
        Ed25519PublicKey.from_public_bytes(raw)
    except Exception:
        raise AuthError("Invalid Ed25519 public key", code="invalid_key")
    return raw


async def _verify_challenge(challenge_id: str) -> None:
    """Verify a challenge is confirmed via the confirmations API."""
    url = f"{settings.confirmations_api_url}/challenges/{challenge_id}"
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.get(url)
        except httpx.HTTPError:
            raise AuthError("Failed to reach confirmations API", code="upstream_error")

    if resp.status_code == 404:
        raise AuthError("Challenge not found", code="challenge_not_found")
    if resp.status_code != 200:
        raise AuthError("Failed to verify challenge", code="upstream_error")

    data = resp.json()
    status = data.get("status", "")
    if status != "CONFIRMED":
        raise AuthError(
            f"Challenge not confirmed (status: {status})",
            code="challenge_not_confirmed",
        )


async def signup_bot(
    db: AsyncSession,
    redis,
    *,
    app: Application,
    challenge_id: str,
    public_key_b64: str,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> dict:
    """Register a bot user with a confirmed donation challenge and Ed25519 public key."""
    # Rate limit by IP
    ip_limiter = RateLimiter(
        redis,
        _parse_rate_limit(settings.signup_rate_limit_ip),
        user_id=ip_address or "unknown",
        namespace=f"{app.id}:bot",
    )
    if not await ip_limiter.check_and_consume():
        raise AuthError("Too many signup attempts", code="rate_limited")

    # Validate the public key
    _validate_public_key(public_key_b64)

    # Check challenge_id not already used
    existing = await db.execute(
        select(User).where(User.challenge_id == challenge_id)
    )
    if existing.scalars().first() is not None:
        raise AuthError("Challenge already used", code="challenge_used")

    # Check public key not already registered for this app
    existing_key = await db.execute(
        select(User).where(
            User.app_id == app.id,
            User.public_key_ed25519 == public_key_b64,
        )
    )
    if existing_key.scalars().first() is not None:
        raise AuthError("Public key already registered", code="key_exists")

    # Verify challenge with confirmations API
    await _verify_challenge(challenge_id)

    # Create bot user
    user = User(
        app_id=app.id,
        is_bot=True,
        public_key_ed25519=public_key_b64,
        challenge_id=challenge_id,
    )
    db.add(user)
    await db.flush()

    await audit.log_event(
        db,
        app_id=app.id,
        event_type="bot.signup",
        user_id=user.id,
        ip_address=ip_address,
        user_agent=user_agent,
    )

    logger.info(f"Bot {user.id} signed up for app {app.id}")
    return {"bot_id": str(user.id), "public_key": public_key_b64}


async def auth_bot(
    db: AsyncSession,
    redis,
    *,
    app: Application,
    bot_id: str,
    timestamp: int,
    signature_b64: str,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> tuple[User, Session, str, str]:
    """Authenticate a bot via Ed25519 signature.

    Returns (user, session, access_jwt, raw_refresh_token).
    """
    # Rate limit by IP
    ip_limiter = RateLimiter(
        redis,
        _parse_rate_limit(settings.signin_rate_limit_ip),
        user_id=ip_address or "unknown",
        namespace=f"{app.id}:bot",
    )
    if not await ip_limiter.check_and_consume():
        raise AuthError("Too many auth attempts", code="rate_limited")

    # Check timestamp is within tolerance
    now = int(time.time())
    if abs(now - timestamp) > settings.bot_auth_timestamp_tolerance:
        raise AuthError("Timestamp out of range", code="timestamp_expired")

    # Parse bot_id
    try:
        bot_uuid = uuid.UUID(bot_id)
    except ValueError:
        raise AuthError("Invalid bot_id", code="invalid_bot_id")

    # Look up bot user
    result = await db.execute(
        select(User).where(
            User.id == bot_uuid,
            User.app_id == app.id,
            User.is_bot.is_(True),
        )
    )
    user = result.scalars().first()
    if user is None:
        raise AuthError("Bot not found", code="bot_not_found")

    # Verify signature
    message = f"ezauth:bot_auth:{app.id}:{bot_id}:{timestamp}"
    try:
        sig_bytes = base64.b64decode(signature_b64)
    except Exception:
        raise AuthError("Invalid signature encoding", code="invalid_signature")

    try:
        key = Ed25519PublicKey.from_public_bytes(base64.b64decode(user.public_key_ed25519))
        key.verify(sig_bytes, message.encode())
    except InvalidSignature:
        raise AuthError("Invalid signature", code="invalid_signature")
    except Exception:
        raise AuthError("Signature verification failed", code="invalid_signature")

    # Create session
    session, access_jwt, raw_refresh = await sessions.create_session(
        db, app=app, user=user
    )

    await audit.log_event(
        db,
        app_id=app.id,
        event_type="bot.auth",
        user_id=user.id,
        session_id=session.id,
        ip_address=ip_address,
        user_agent=user_agent,
    )

    return user, session, access_jwt, raw_refresh
