"""Tests for DB constraints — requires test database."""
import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ezauth.models.user import User


@pytest.mark.skipif(True, reason="Requires test database")
async def test_duplicate_email_same_app(db: AsyncSession, app):
    user1 = User(app_id=app.id, email="Test@Example.com")
    db.add(user1)
    await db.flush()

    user2 = User(app_id=app.id, email="test@example.com")
    db.add(user2)
    with pytest.raises(IntegrityError):
        await db.flush()
