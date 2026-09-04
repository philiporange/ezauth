"""Tests for the dashboard user search: LIKE wildcards must not leak through."""

import pytest
from sqlalchemy import select

from ezauth.dashboard.users import email_search_filter
from ezauth.models.user import User


@pytest.fixture
async def users(db, app):
    rows = [
        User(app_id=app.id, email="alice@example.com"),
        User(app_id=app.id, email="bob@example.com"),
    ]
    db.add_all(rows)
    await db.flush()
    return rows


async def _search(db, app, term):
    result = await db.execute(
        select(User).where(User.app_id == app.id).where(email_search_filter(term))
    )
    return {u.email for u in result.scalars().all()}


async def test_substring_search_matches(db, app, users):
    assert await _search(db, app, "ALICE") == {"alice@example.com"}


async def test_percent_matches_nothing(db, app, users):
    assert await _search(db, app, "%") == set()


async def test_underscore_is_literal(db, app, users):
    assert await _search(db, app, "a_ice") == set()


async def test_backslash_is_literal(db, app, users):
    assert await _search(db, app, "\\") == set()
