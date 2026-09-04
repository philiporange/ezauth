"""Tests for database-level constraints."""

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ezauth.models.user import User


async def test_duplicate_email_same_app(db: AsyncSession, app):
    db.add(User(app_id=app.id, email="Test@Example.com"))
    await db.flush()

    db.add(User(app_id=app.id, email="test@example.com"))
    with pytest.raises(IntegrityError):
        await db.flush()


async def test_same_email_in_two_apps_is_allowed(db: AsyncSession, app, tenant):
    from ezauth.models.application import Application, Environment
    from ezauth.services import keys as key_service

    pem, kid, _ = key_service.generate_jwk_pair()
    second = Application(
        tenant_id=tenant.id,
        name="Second App",
        environment=Environment.dev,
        publishable_key=key_service.generate_publishable_key("dev"),
        secret_key=key_service.generate_secret_key("dev"),
        jwk_private_pem=pem,
        jwk_kid=kid,
    )
    db.add(second)
    await db.flush()

    db.add(User(app_id=app.id, email="shared@example.com"))
    db.add(User(app_id=second.id, email="shared@example.com"))
    await db.flush()
