"""Tests for dashboard session auth: identity sessions, superadmin codes, expiry."""

import time

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from ezauth.crypto import hash_token
from ezauth.dashboard import auth as dash_auth


def make_request(session_id: str | None = None) -> Request:
    headers = []
    if session_id:
        headers.append((b"cookie", f"__dashboard_session={session_id}".encode()))
    return Request({"type": "http", "headers": headers, "method": "GET", "path": "/"})


@pytest.fixture(autouse=True)
def clean_state():
    dash_auth._dashboard_sessions.clear()
    dash_auth._admin_codes.clear()
    dash_auth._send_cooldown.clear()
    yield
    dash_auth._dashboard_sessions.clear()
    dash_auth._admin_codes.clear()
    dash_auth._send_cooldown.clear()


def test_no_cookie_redirects():
    with pytest.raises(HTTPException) as exc:
        dash_auth.require_dashboard_auth(make_request())
    assert exc.value.status_code == 302


def test_unknown_session_redirects():
    with pytest.raises(HTTPException) as exc:
        dash_auth.require_dashboard_auth(make_request("nope"))
    assert exc.value.status_code == 302


def test_valid_session_returns_identity():
    dash_auth._dashboard_sessions["sid1"] = {
        "email": "owner@example.com",
        "is_super": False,
        "expires": time.time() + 100,
    }
    result = dash_auth.require_dashboard_auth(make_request("sid1"))
    assert result.email == "owner@example.com"
    assert result.is_super is False


def test_expired_session_redirects_and_is_removed():
    dash_auth._dashboard_sessions["sid2"] = {
        "email": "owner@example.com",
        "is_super": False,
        "expires": time.time() - 1,
    }
    with pytest.raises(HTTPException):
        dash_auth.require_dashboard_auth(make_request("sid2"))
    assert "sid2" not in dash_auth._dashboard_sessions


def test_require_superadmin_rejects_owner():
    dash_auth._dashboard_sessions["sid3"] = {
        "email": "owner@example.com",
        "is_super": False,
        "expires": time.time() + 100,
    }
    with pytest.raises(HTTPException) as exc:
        dash_auth.require_superadmin(make_request("sid3"))
    assert exc.value.status_code == 403


def test_require_superadmin_allows_super():
    dash_auth._dashboard_sessions["sid4"] = {
        "email": "admin@example.com",
        "is_super": True,
        "expires": time.time() + 100,
    }
    result = dash_auth.require_superadmin(make_request("sid4"))
    assert result.is_super is True


def test_admin_emails_parsing(monkeypatch):
    monkeypatch.setattr(
        dash_auth.settings, "dashboard_admin_emails", "A@x.com, b@y.com ,,"
    )
    assert dash_auth._admin_emails() == {"a@x.com", "b@y.com"}


async def test_admin_memory_code_consumed_once(db):
    dash_auth._admin_codes["admin@x.com"] = {
        "hash": hash_token("123456"),
        "expires": time.time() + 100,
        "attempts": 0,
    }
    assert await dash_auth._verify_code(db, "admin@x.com", "123456") is True
    # Single use: the same code must not verify twice.
    assert await dash_auth._verify_code(db, "admin@x.com", "123456") is False


async def test_admin_memory_code_attempt_limit(db):
    dash_auth._admin_codes["admin@x.com"] = {
        "hash": hash_token("123456"),
        "expires": time.time() + 100,
        "attempts": 0,
    }
    for _ in range(dash_auth._MAX_CODE_ATTEMPTS + 1):
        assert await dash_auth._verify_code(db, "admin@x.com", "000000") is False
    # Code is burned after too many wrong attempts.
    assert await dash_auth._verify_code(db, "admin@x.com", "123456") is False


async def test_admin_memory_code_expired(db):
    dash_auth._admin_codes["admin@x.com"] = {
        "hash": hash_token("123456"),
        "expires": time.time() - 1,
        "attempts": 0,
    }
    assert await dash_auth._verify_code(db, "admin@x.com", "123456") is False
