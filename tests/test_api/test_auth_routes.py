"""End-to-end tests for the authentication HTTP routes.

These exercise the real ASGI application with the test database and a fake
Redis, so routing, dependency resolution, status codes and cookie behaviour are
covered rather than only the service functions underneath them.
"""

import pytest
from sqlalchemy import select

from ezauth.config import settings
from ezauth.cookies import session_cookie_name
from ezauth.models.auth_attempt import AuthAttempt, AuthAttemptType
from ezauth.models.user import User
from ezauth.services import sessions as session_service
from ezauth.services import tokens as token_service


@pytest.fixture(autouse=True)
def no_hashcash(monkeypatch):
    """Signup proof of work is exercised separately; disable it by default."""
    monkeypatch.setattr(settings, "hashcash_enabled", False)


# --- Signup ---


async def test_signup_creates_a_user_and_sends_a_code(client, db, app, sent_mail):
    response = await client.post("/v1/signups", json={"email": "new@example.com"})

    assert response.status_code == 200
    assert response.json() == {"status": "verification_sent", "user_id": None}

    result = await db.execute(
        select(User).where(User.app_id == app.id, User.email_lower == "new@example.com")
    )
    assert result.scalars().first() is not None
    assert sent_mail and sent_mail[-1]["to"] == "new@example.com"


async def test_signup_does_not_reveal_existing_accounts(client, user, sent_mail):
    existing = await client.post("/v1/signups", json={"email": user.email})
    fresh = await client.post("/v1/signups", json={"email": "unseen@example.com"})

    assert existing.status_code == fresh.status_code == 200
    assert existing.json() == fresh.json()


async def test_signup_rejects_a_foreign_redirect(client):
    response = await client.post(
        "/v1/signups",
        json={"email": "redir@example.com", "redirect_url": "https://evil.com"},
    )
    assert response.status_code == 400


async def test_signup_requires_proof_of_work_when_enabled(client, monkeypatch):
    monkeypatch.setattr(settings, "hashcash_enabled", True)
    response = await client.post("/v1/signups", json={"email": "pow@example.com"})
    assert response.status_code == 422


# --- Code verification ---


async def _issue_code(db, app, email, code, user_id=None):
    await token_service.create_auth_attempt(
        db,
        app_id=app.id,
        type=AuthAttemptType.signin,
        email=email,
        user_id=user_id,
        expire_minutes=15,
        code=code,
    )


async def test_verify_code_opens_a_session(client, db, app, user):
    await _issue_code(db, app, user.email, "654321", user.id)

    response = await client.post(
        "/v1/verify-code", json={"email": user.email, "code": "654321"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["access_token"] and body["refresh_token"]
    assert session_cookie_name(app) in response.cookies


async def test_verify_code_rejects_a_wrong_code(client, db, app, user):
    await _issue_code(db, app, user.email, "654321", user.id)

    response = await client.post(
        "/v1/verify-code", json={"email": user.email, "code": "000000"}
    )
    assert response.status_code == 400


async def test_verify_code_is_rate_limited(client, db, app, user):
    await _issue_code(db, app, user.email, "654321", user.id)

    statuses = []
    for _ in range(30):
        response = await client.post(
            "/v1/verify-code", json={"email": user.email, "code": "000000"}
        )
        statuses.append(response.status_code)
        if response.status_code == 429:
            break

    assert 429 in statuses


# --- Magic links ---


async def test_magic_link_get_does_not_consume_the_token(client, db, app, user):
    _attempt, raw_token = await token_service.create_auth_attempt(
        db,
        app_id=app.id,
        type=AuthAttemptType.signin,
        email=user.email,
        user_id=user.id,
        expire_minutes=15,
    )

    page = await client.get(f"/v1/email/verify?token={raw_token}")
    assert page.status_code == 200
    assert "text/html" in page.headers["content-type"]

    result = await db.execute(select(AuthAttempt).where(AuthAttempt.email == user.email))
    assert result.scalars().first().status.value == "pending"


async def test_magic_link_post_consumes_the_token(client, db, app, user):
    _attempt, raw_token = await token_service.create_auth_attempt(
        db,
        app_id=app.id,
        type=AuthAttemptType.signin,
        email=user.email,
        user_id=user.id,
        expire_minutes=15,
    )

    response = await client.post(
        "/v1/email/verify", data={"token": raw_token}, follow_redirects=False
    )

    assert response.status_code == 302
    assert session_cookie_name(app) in response.cookies

    second = await client.post(
        "/v1/email/verify", data={"token": raw_token}, follow_redirects=False
    )
    assert second.status_code == 400


# --- Sessions ---


async def test_me_requires_authentication(client):
    response = await client.get("/v1/me")
    assert response.status_code == 401


async def test_me_returns_the_signed_in_user(client, db, app, user):
    _session, access_jwt, _refresh = await session_service.create_session(
        db, app=app, user=user
    )

    response = await client.get(
        "/v1/me", headers={"Authorization": f"Bearer {access_jwt}"}
    )

    assert response.status_code == 200
    assert response.json()["user_id"] == str(user.id)


async def test_logout_invalidates_the_access_token_immediately(client, db, app, user):
    _session, access_jwt, _refresh = await session_service.create_session(
        db, app=app, user=user
    )
    headers = {"Authorization": f"Bearer {access_jwt}"}

    assert (await client.get("/v1/me", headers=headers)).status_code == 200
    assert (await client.post("/v1/sessions/logout", headers=headers)).status_code == 200
    assert (await client.get("/v1/me", headers=headers)).status_code == 401


async def test_refresh_rotates_the_token(client, db, app, user):
    _session, _jwt, raw_refresh = await session_service.create_session(
        db, app=app, user=user
    )

    first = await client.post("/v1/tokens/session", json={"refresh_token": raw_refresh})
    assert first.status_code == 200
    rotated = first.json()["refresh_token"]
    assert rotated != raw_refresh

    reused = await client.post("/v1/tokens/session", json={"refresh_token": raw_refresh})
    assert reused.status_code == 401


# --- Passwords ---


async def test_setting_a_password_requires_the_current_one(client, db, app, user):
    _session, access_jwt, _refresh = await session_service.create_session(
        db, app=app, user=user
    )
    headers = {"Authorization": f"Bearer {access_jwt}"}

    missing = await client.post(
        "/v1/passwords", json={"password": "brand-new-password"}, headers=headers
    )
    assert missing.status_code == 400

    wrong = await client.post(
        "/v1/passwords",
        json={"password": "brand-new-password", "current_password": "not-it"},
        headers=headers,
    )
    assert wrong.status_code == 401

    ok = await client.post(
        "/v1/passwords",
        json={"password": "brand-new-password", "current_password": "testpassword123"},
        headers=headers,
    )
    assert ok.status_code == 200


# --- SSO ---


async def test_sso_bridge_rejects_an_unverified_return_to(client, db, app, user):
    _session, access_jwt, _refresh = await session_service.create_session(
        db, app=app, user=user
    )

    response = await client.get(
        "/v1/sso/bridge",
        params={"return_to": "https://evil.com/land"},
        headers={"Authorization": f"Bearer {access_jwt}"},
        follow_redirects=False,
    )
    assert response.status_code == 400


async def test_sso_exchange_rejects_an_unknown_token(client):
    response = await client.post("/v1/sso/exchange", json={"token": "made-up"})
    assert response.status_code == 401


# --- JWKS ---


async def test_jwks_rejects_a_malformed_app_id(client):
    response = await client.get("/.well-known/jwks.json?app_id=not-a-uuid")
    assert response.status_code == 400


async def test_jwks_publishes_the_application_key(client, app):
    response = await client.get(f"/.well-known/jwks.json?app_id={app.id}")
    assert response.status_code == 200
    assert response.json()["keys"][0]["kid"] == app.jwk_kid


# --- Hosted pages ---


async def test_hosted_login_requires_a_csrf_token(client):
    response = await client.post(
        "/auth/login",
        data={"email": "someone@example.com", "strategy": "magic_link"},
        follow_redirects=False,
    )
    assert response.status_code == 403


async def test_hosted_login_accepts_a_matching_csrf_token(client, sent_mail, user):
    page = await client.get("/auth/login")
    assert page.status_code == 200

    token = page.cookies.get("__csrf")
    assert token

    response = await client.post(
        "/auth/login",
        data={
            "email": user.email,
            "strategy": "magic_link",
            "csrf_token": token,
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
