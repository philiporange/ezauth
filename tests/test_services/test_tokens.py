import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ezauth.models.auth_attempt import AuthAttempt, AuthAttemptStatus, AuthAttemptType
from ezauth.services.tokens import consume_auth_attempt, create_auth_attempt


@pytest.mark.skipif(True, reason="Requires test database")
async def test_create_and_consume_auth_attempt(db: AsyncSession, app):
    attempt, raw_token = await create_auth_attempt(
        db,
        app_id=app.id,
        type=AuthAttemptType.verify_email,
        email="test@example.com",
        expire_minutes=60,
    )

    assert attempt.status == AuthAttemptStatus.pending
    assert attempt.token_hash != raw_token  # stored as hash

    # Consume
    consumed = await consume_auth_attempt(
        db,
        raw_token=raw_token,
        expected_type=AuthAttemptType.verify_email,
    )
    assert consumed is not None
    assert consumed.id == attempt.id
    assert consumed.status == AuthAttemptStatus.consumed

    # Cannot consume again
    again = await consume_auth_attempt(db, raw_token=raw_token)
    assert again is None
