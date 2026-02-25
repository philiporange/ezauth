import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from ezauth.crypto import generate_token, hash_token
from ezauth.models.auth_attempt import AuthAttempt, AuthAttemptStatus, AuthAttemptType


async def create_auth_attempt(
    db: AsyncSession,
    *,
    app_id: uuid.UUID,
    type: AuthAttemptType,
    email: str,
    user_id: uuid.UUID | None = None,
    redirect_url: str | None = None,
    expire_minutes: int = 60,
    metadata: dict | None = None,
) -> tuple[AuthAttempt, str]:
    """Create an auth attempt and return (attempt, raw_token).

    The raw token is returned for inclusion in emails/links.
    Only the hash is stored in the database.
    """
    raw_token = generate_token()
    token_hash = hash_token(raw_token)

    attempt = AuthAttempt(
        app_id=app_id,
        type=type,
        email=email,
        user_id=user_id,
        token_hash=token_hash,
        status=AuthAttemptStatus.pending,
        redirect_url=redirect_url,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=expire_minutes),
        metadata_json=metadata or {},
    )
    db.add(attempt)
    await db.flush()
    return attempt, raw_token


async def consume_auth_attempt_by_code(
    db: AsyncSession,
    *,
    email: str,
    code: str,
    app_id: uuid.UUID,
) -> AuthAttempt | None:
    """Atomically consume a pending auth attempt by matching a 6-digit code.

    Returns the attempt if successfully consumed, None otherwise.
    """
    now = datetime.now(timezone.utc)

    stmt = (
        update(AuthAttempt)
        .where(
            AuthAttempt.app_id == app_id,
            AuthAttempt.email == email,
            AuthAttempt.status == AuthAttemptStatus.pending,
            AuthAttempt.expires_at > now,
            AuthAttempt.metadata_json["code"].astext == code,
        )
        .values(status=AuthAttemptStatus.consumed)
        .returning(AuthAttempt)
    )
    result = await db.execute(stmt)
    return result.scalars().first()


async def consume_auth_attempt(
    db: AsyncSession,
    *,
    raw_token: str,
    expected_type: AuthAttemptType | None = None,
) -> AuthAttempt | None:
    """Atomically consume a pending auth attempt by its raw token.

    Returns the attempt if successfully consumed, None otherwise.
    """
    token_h = hash_token(raw_token)
    now = datetime.now(timezone.utc)

    conditions = [
        AuthAttempt.token_hash == token_h,
        AuthAttempt.status == AuthAttemptStatus.pending,
        AuthAttempt.expires_at > now,
    ]
    if expected_type is not None:
        conditions.append(AuthAttempt.type == expected_type)

    stmt = (
        update(AuthAttempt)
        .where(*conditions)
        .values(status=AuthAttemptStatus.consumed)
        .returning(AuthAttempt)
    )
    result = await db.execute(stmt)
    row = result.scalars().first()
    return row
