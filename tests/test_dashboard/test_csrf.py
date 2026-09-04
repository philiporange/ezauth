"""Tests for the dashboard CSRF requirement on state-changing requests."""

from urllib.parse import urlencode

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from ezauth.dashboard import auth as dash_auth


def make_request(
    session_id: str,
    method: str = "POST",
    form: dict | None = None,
    csrf_header: str | None = None,
) -> Request:
    body = urlencode(form or {}).encode()
    headers = [
        (b"cookie", f"__dashboard_session={session_id}".encode()),
        (b"content-type", b"application/x-www-form-urlencoded"),
        (b"content-length", str(len(body)).encode()),
    ]
    if csrf_header:
        headers.append((b"x-csrf-token", csrf_header.encode()))

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {
            "type": "http",
            "method": method,
            "path": "/dashboard/tenants",
            "query_string": b"",
            "headers": headers,
        },
        receive,
    )


@pytest.fixture
async def session(redis):
    return await dash_auth.create_dashboard_session(redis, "owner@x.com", False)


async def test_post_without_token_is_rejected(redis, session):
    session_id, _ = session
    with pytest.raises(HTTPException) as exc:
        await dash_auth.require_dashboard_auth(make_request(session_id), redis)
    assert exc.value.status_code == 403


async def test_post_with_wrong_token_is_rejected(redis, session):
    session_id, _ = session
    request = make_request(session_id, form={"csrf_token": "not-the-token"})
    with pytest.raises(HTTPException) as exc:
        await dash_auth.require_dashboard_auth(request, redis)
    assert exc.value.status_code == 403


async def test_post_with_form_token_is_accepted(redis, session):
    session_id, csrf_token = session
    request = make_request(session_id, form={"csrf_token": csrf_token, "name": "Acme"})
    auth = await dash_auth.require_dashboard_auth(request, redis)
    assert auth.email == "owner@x.com"
    # The body stays readable by the route handler.
    assert (await request.form())["name"] == "Acme"


async def test_post_with_header_token_is_accepted(redis, session):
    session_id, csrf_token = session
    request = make_request(session_id, csrf_header=csrf_token)
    assert (await dash_auth.require_dashboard_auth(request, redis)).email == "owner@x.com"


async def test_token_of_another_session_is_rejected(redis, session):
    session_id, _ = session
    _, other_token = await dash_auth.create_dashboard_session(redis, "other@x.com", False)
    request = make_request(session_id, csrf_header=other_token)
    with pytest.raises(HTTPException) as exc:
        await dash_auth.require_dashboard_auth(request, redis)
    assert exc.value.status_code == 403


async def test_get_needs_no_token(redis, session):
    session_id, csrf_token = session
    request = make_request(session_id, method="GET")
    auth = await dash_auth.require_dashboard_auth(request, redis)
    assert auth.email == "owner@x.com"
    # The token is exposed to the template so every form can carry it.
    assert request.state.csrf_token == csrf_token
