"""Tests for one-time auth attempt creation and consumption."""

from sqlalchemy.ext.asyncio import AsyncSession

from ezauth.models.auth_attempt import AuthAttemptStatus, AuthAttemptType
from ezauth.services.tokens import consume_auth_attempt, create_auth_attempt


async def test_create_and_consume_auth_attempt(db: AsyncSession, app):
    attempt, raw_token = await create_auth_attempt(
        db,
        app_id=app.id,
        type=AuthAttemptType.verify_email,
        email="test@example.com",
        expire_minutes=60,
    )

    assert attempt.status == AuthAttemptStatus.pending
    assert attempt.token_hash != raw_token

    consumed = await consume_auth_attempt(
        db,
        raw_token=raw_token,
        app_id=app.id,
        expected_type=AuthAttemptType.verify_email,
    )
    assert consumed is not None
    assert consumed.id == attempt.id
    assert consumed.status == AuthAttemptStatus.consumed

    again = await consume_auth_attempt(db, raw_token=raw_token, app_id=app.id)
    assert again is None


async def test_attempt_type_must_match(db: AsyncSession, app):
    _attempt, raw_token = await create_auth_attempt(
        db,
        app_id=app.id,
        type=AuthAttemptType.verify_email,
        email="typed@example.com",
        expire_minutes=60,
    )

    wrong_type = await consume_auth_attempt(
        db, raw_token=raw_token, app_id=app.id, expected_type=AuthAttemptType.signin
    )
    assert wrong_type is None
