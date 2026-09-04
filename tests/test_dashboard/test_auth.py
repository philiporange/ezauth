"""Tests for dashboard session auth: Redis sessions, superadmin codes, CSRF."""

import json

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from ezauth.dashboard import auth as dash_auth


def make_request(session_id: str | None = None, method: str = "GET") -> Request:
    headers = []
    if session_id:
        headers.append((b"cookie", f"__dashboard_session={session_id}".encode()))
    return Request(
        {"type": "http", "headers": headers, "method": method, "path": "/dashboard/"}
    )


async def test_no_cookie_redirects(redis):
    with pytest.raises(HTTPException) as exc:
        await dash_auth.require_dashboard_auth(make_request(), redis)
    assert exc.value.status_code == 302


async def test_unknown_session_redirects(redis):
    with pytest.raises(HTTPException) as exc:
        await dash_auth.require_dashboard_auth(make_request("nope"), redis)
    assert exc.value.status_code == 302


async def test_valid_session_returns_identity(redis):
    session_id, _ = await dash_auth.create_dashboard_session(
        redis, "owner@example.com", False
    )
    result = await dash_auth.require_dashboard_auth(make_request(session_id), redis)
    assert result.email == "owner@example.com"
    assert result.is_super is False


async def test_session_survives_a_new_process(redis):
    """Nothing about a session lives in memory: only the Redis key matters."""
    session_id, csrf = await dash_auth.create_dashboard_session(redis, "a@x.com", True)
    stored = json.loads(await redis.get(f"dash:session:{session_id}"))
    assert stored == {"email": "a@x.com", "is_super": True, "csrf": csrf}


async def test_destroyed_session_redirects(redis):
    session_id, _ = await dash_auth.create_dashboard_session(redis, "owner@x.com", False)
    await dash_auth.destroy_dashboard_session(redis, session_id)
    with pytest.raises(HTTPException) as exc:
        await dash_auth.require_dashboard_auth(make_request(session_id), redis)
    assert exc.value.status_code == 302


async def test_expired_session_redirects(redis):
    session_id, _ = await dash_auth.create_dashboard_session(redis, "owner@x.com", False)
    await redis.expire(f"dash:session:{session_id}", 0)
    with pytest.raises(HTTPException):
        await dash_auth.require_dashboard_auth(make_request(session_id), redis)


async def test_require_superadmin_rejects_owner():
    auth = dash_auth.DashboardAuth(email="owner@example.com", is_super=False)
    with pytest.raises(HTTPException) as exc:
        await dash_auth.require_superadmin(auth)
    assert exc.value.status_code == 403


async def test_require_superadmin_allows_super():
    auth = dash_auth.DashboardAuth(email="admin@example.com", is_super=True)
    assert (await dash_auth.require_superadmin(auth)).is_super is True


def test_admin_emails_parsing(monkeypatch):
    monkeypatch.setattr(
        dash_auth.settings, "dashboard_admin_emails", "A@x.com, b@y.com ,,"
    )
    assert dash_auth._admin_emails() == {"a@x.com", "b@y.com"}


async def test_admin_code_consumed_once(redis):
    await dash_auth._store_admin_code(redis, "admin@x.com", "123456")
    assert await dash_auth._consume_admin_code(redis, "admin@x.com", "123456") is True
    assert await dash_auth._consume_admin_code(redis, "admin@x.com", "123456") is False


async def test_admin_code_attempt_limit(redis):
    await dash_auth._store_admin_code(redis, "admin@x.com", "123456")
    for _ in range(dash_auth.settings.max_code_attempts + 1):
        assert await dash_auth._consume_admin_code(redis, "admin@x.com", "000000") is False
    assert await dash_auth._consume_admin_code(redis, "admin@x.com", "123456") is False


async def test_admin_code_is_stored_hashed(redis):
    await dash_auth._store_admin_code(redis, "admin@x.com", "123456")
    stored = await redis.get("dash:code:admin@x.com")
    assert "123456" not in stored


async def test_admin_code_expires(redis):
    await dash_auth._store_admin_code(redis, "admin@x.com", "123456")
    await redis.expire("dash:code:admin@x.com", 0)
    assert await dash_auth._consume_admin_code(redis, "admin@x.com", "123456") is False
