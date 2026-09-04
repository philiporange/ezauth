"""Creation and consumption of one-time auth attempts (magic links and codes).

An `AuthAttempt` row backs every out-of-band credential the service issues: a
magic-link token, an email verification code, a dashboard or admin login code.
Only digests reach the database, so a leaked backup or replica yields nothing
usable: link tokens are stored as a SHA-256 `token_hash`, and short numeric
codes are stored as a `code_hash` in the attempt metadata and compared in
constant time.

Codes are only six digits, so guessing is bounded on two axes. Issuing a new
code for an address revokes that address's earlier pending attempts of the same
type, which stops an attacker from stacking many simultaneously valid codes,
and each surviving attempt carries an attempt counter that revokes it once
`settings.max_code_attempts` wrong guesses have been made against it. Consuming
a code takes a row lock on the candidate attempts so concurrent guesses cannot
race past the counter. Every consume path is scoped to the application that
issued the attempt, so a token minted by one application can never mint a
session in another.
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ezauth.config import settings
from ezauth.crypto import constant_time_compare, generate_token, hash_token
from ezauth.models.auth_attempt import AuthAttempt, AuthAttemptStatus, AuthAttemptType

INVALID_CODE = "invalid_code"
TOO_MANY_ATTEMPTS = "too_many_attempts"


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
    code: str | None = None,
) -> tuple[AuthAttempt, str]:
    """Create an auth attempt and return (attempt, raw_token).

    The raw token is returned for inclusion in emails and links; only its hash
    is stored. When `code` is given its hash is stored alongside, and the raw
    code is never persisted.
    """
    raw_token = generate_token()
    token_hash = hash_token(raw_token)

    meta = dict(metadata or {})
    if code is not None:
        meta["code_hash"] = hash_token(code)
        meta["attempts"] = 0

    attempt = AuthAttempt(
        app_id=app_id,
        type=type,
        email=email,
        user_id=user_id,
        token_hash=token_hash,
        status=AuthAttemptStatus.pending,
        redirect_url=redirect_url,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=expire_minutes),
        metadata_json=meta,
    )
    db.add(attempt)
    await db.flush()
    return attempt, raw_token


async def revoke_pending_attempts(
    db: AsyncSession,
    *,
    app_id: uuid.UUID,
    email: str,
    type: AuthAttemptType | None = None,
) -> int:
    """Revoke an address's pending attempts so only the newest code is live."""
    conditions = [
        AuthAttempt.app_id == app_id,
        AuthAttempt.email == email,
        AuthAttempt.status == AuthAttemptStatus.pending,
    ]
    if type is not None:
        conditions.append(AuthAttempt.type == type)

    result = await db.execute(
        update(AuthAttempt).where(*conditions).values(status=AuthAttemptStatus.revoked)
    )
    return result.rowcount or 0


async def consume_auth_attempt_by_code(
    db: AsyncSession,
    *,
    email: str,
    code: str,
    app_id: uuid.UUID,
    expected_types: list[AuthAttemptType] | None = None,
) -> tuple[AuthAttempt | None, str | None]:
    """Consume a pending attempt whose code matches, under a row lock.

    Returns (attempt, None) on success, or (None, reason) where reason is
    `INVALID_CODE` or `TOO_MANY_ATTEMPTS`.
    """
    now = datetime.now(timezone.utc)

    conditions = [
        AuthAttempt.app_id == app_id,
        AuthAttempt.email == email,
        AuthAttempt.status == AuthAttemptStatus.pending,
        AuthAttempt.expires_at > now,
    ]
    if expected_types:
        conditions.append(AuthAttempt.type.in_(expected_types))

    result = await db.execute(
        select(AuthAttempt).where(*conditions).with_for_update()
    )
    candidates = list(result.scalars().all())
    if not candidates:
        return None, INVALID_CODE

    code_hash = hash_token(code)
    exhausted = False

    for attempt in candidates:
        meta = dict(attempt.metadata_json or {})
        stored = meta.get("code_hash")
        if stored and constant_time_compare(stored, code_hash):
            attempt.status = AuthAttemptStatus.consumed
            await db.flush()
            return attempt, None

    for attempt in candidates:
        meta = dict(attempt.metadata_json or {})
        if not meta.get("code_hash"):
            continue
        meta["attempts"] = int(meta.get("attempts", 0)) + 1
        if meta["attempts"] >= settings.max_code_attempts:
            attempt.status = AuthAttemptStatus.revoked
            exhausted = True
        attempt.metadata_json = meta

    await db.flush()
    return None, TOO_MANY_ATTEMPTS if exhausted else INVALID_CODE


async def consume_admin_login_code(
    db: AsyncSession, *, email: str, code: str
) -> tuple[list[uuid.UUID], str | None]:
    """Consume the admin login attempts an address holds across applications.

    One code is issued per application the address owns, all sharing the same
    digits, so a successful guess consumes every matching attempt at once.

    Returns (app_ids, None) on success, or ([], reason) on failure.
    """
    now = datetime.now(timezone.utc)

    result = await db.execute(
        select(AuthAttempt)
        .where(
            AuthAttempt.type == AuthAttemptType.admin_login,
            AuthAttempt.email == email,
            AuthAttempt.status == AuthAttemptStatus.pending,
            AuthAttempt.expires_at > now,
        )
        .with_for_update()
    )
    candidates = list(result.scalars().all())
    if not candidates:
        return [], INVALID_CODE

    code_hash = hash_token(code)
    matched = [
        a
        for a in candidates
        if (a.metadata_json or {}).get("code_hash")
        and constant_time_compare((a.metadata_json or {})["code_hash"], code_hash)
    ]

    if matched:
        for attempt in matched:
            attempt.status = AuthAttemptStatus.consumed
        await db.flush()
        return [a.app_id for a in matched], None

    exhausted = False
    for attempt in candidates:
        meta = dict(attempt.metadata_json or {})
        if not meta.get("code_hash"):
            continue
        meta["attempts"] = int(meta.get("attempts", 0)) + 1
        if meta["attempts"] >= settings.max_code_attempts:
            attempt.status = AuthAttemptStatus.revoked
            exhausted = True
        attempt.metadata_json = meta

    await db.flush()
    return [], TOO_MANY_ATTEMPTS if exhausted else INVALID_CODE


async def consume_auth_attempt(
    db: AsyncSession,
    *,
    raw_token: str,
    app_id: uuid.UUID,
    expected_type: AuthAttemptType | None = None,
) -> AuthAttempt | None:
    """Atomically consume a pending auth attempt by its raw link token.

    Scoped to `app_id` so a token issued by one application cannot be redeemed
    against another. Returns the attempt if consumed, None otherwise.
    """
    token_h = hash_token(raw_token)
    now = datetime.now(timezone.utc)

    conditions = [
        AuthAttempt.token_hash == token_h,
        AuthAttempt.app_id == app_id,
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
    return result.scalars().first()
