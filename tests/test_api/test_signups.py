"""Tests for the signup endpoint's externally visible behaviour."""

import pytest
from sqlalchemy import select

from ezauth.config import settings
from ezauth.models.user import User


@pytest.fixture(autouse=True)
def no_hashcash(monkeypatch):
    monkeypatch.setattr(settings, "hashcash_enabled", False)


async def test_signup_success(client, db, app):
    resp = await client.post(
        "/v1/signups",
        json={"email": "new@example.com", "redirect_url": "https://localhost/welcome"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "verification_sent"

    result = await db.execute(
        select(User).where(User.app_id == app.id, User.email_lower == "new@example.com")
    )
    assert result.scalars().first() is not None


async def test_signup_duplicate_is_indistinguishable(client, user):
    """A registered address must not be detectable through the signup endpoint."""
    duplicate = await client.post("/v1/signups", json={"email": user.email})
    novel = await client.post("/v1/signups", json={"email": "nobody-here@example.com"})

    assert duplicate.status_code == 200
    assert duplicate.status_code == novel.status_code
    assert duplicate.json() == novel.json()
