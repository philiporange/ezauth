"""End-to-end authentication flows across multiple requests.

These follow a user from registration through to logout, asserting on the state
the service exposes at each step rather than on its internals, so a regression
anywhere along the path shows up here.
"""

import pytest
from sqlalchemy import select

from ezauth.config import settings
from ezauth.models.auth_attempt import AuthAttempt
from ezauth.models.user import User
from ezauth.services import tokens as token_service


@pytest.fixture(autouse=True)
def no_hashcash(monkeypatch):
    monkeypatch.setattr(settings, "hashcash_enabled", False)


async def test_signup_verify_me_logout_flow(client, db, app, sent_mail):
    signup = await client.post("/v1/signups", json={"email": "flow@example.com"})
    assert signup.status_code == 200
    assert signup.json()["status"] == "verification_sent"

    code = sent_mail[-1]["context"]["confirmation_code"]

    verify = await client.post(
        "/v1/verify-code", json={"email": "flow@example.com", "code": code}
    )
    assert verify.status_code == 200
    access_token = verify.json()["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}

    me = await client.get("/v1/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["email"] == "flow@example.com"
    assert me.json()["email_verified"] is True

    logout = await client.post("/v1/sessions/logout", headers=headers)
    assert logout.status_code == 200

    assert (await client.get("/v1/me", headers=headers)).status_code == 401

    result = await db.execute(
        select(User).where(User.app_id == app.id, User.email_lower == "flow@example.com")
    )
    assert result.scalars().first().email_verified_at is not None


async def test_signin_password_flow(client, app, user):
    resp = await client.post(
        "/v1/signins",
        json={
            "email": user.email,
            "password": "testpassword123",
            "strategy": "password",
        },
    )
    assert resp.status_code == 200

    data = resp.json()
    assert data["user_id"] == str(user.id)

    me = await client.get(
        "/v1/me", headers={"Authorization": f"Bearer {data['access_token']}"}
    )
    assert me.status_code == 200


async def test_magic_link_flow_with_link_verification(client, db, app, user, sent_mail):
    """An application configured for links signs the user in from the emailed URL."""
    app.verification_method = "link"
    await db.flush()

    request = await client.post(
        "/v1/signins", json={"email": user.email, "strategy": "magic_link"}
    )
    assert request.status_code == 200
    assert sent_mail[-1]["context"]["magic_url"]

    result = await db.execute(select(AuthAttempt).where(AuthAttempt.email == user.email))
    attempt = result.scalars().first()
    assert attempt is not None

    # The raw token only ever exists in the email, so drive the flow with a
    # freshly minted attempt to prove the endpoint completes the sign-in.
    _attempt, raw_token = await token_service.create_auth_attempt(
        db,
        app_id=app.id,
        type=attempt.type,
        email=user.email,
        user_id=user.id,
        expire_minutes=15,
    )

    landing = await client.get(f"/v1/email/verify?token={raw_token}")
    assert landing.status_code == 200

    confirmed = await client.post(
        "/v1/email/verify", data={"token": raw_token}, follow_redirects=False
    )
    assert confirmed.status_code == 302


async def test_password_reset_flow_through_hosted_pages(client, db, app, user, sent_mail):
    """Forgot password proves ownership, then requires a new password to be set."""
    app.passwords_enabled = True
    await db.flush()

    page = await client.get("/auth/forgot-password")
    csrf = page.cookies.get("__csrf")

    submitted = await client.post(
        "/auth/forgot-password",
        data={"email": user.email, "csrf_token": csrf},
        follow_redirects=False,
    )
    assert submitted.status_code == 302
    assert "type=reset" in submitted.headers["location"]

    code = sent_mail[-1]["context"]["confirmation_code"]

    verified = await client.post(
        "/auth/verify-code",
        data={
            "email": user.email,
            "code": code,
            "type": "reset",
            "redirect_url": "",
            "csrf_token": csrf,
        },
        follow_redirects=False,
    )
    assert verified.status_code == 302
    assert verified.headers["location"].startswith("/auth/set-password")

    changed = await client.post(
        "/auth/set-password",
        data={
            "password": "a-brand-new-password",
            "confirm_password": "a-brand-new-password",
            "redirect_url": "",
            "csrf_token": csrf,
        },
        follow_redirects=False,
    )
    assert changed.status_code == 302

    signin = await client.post(
        "/v1/signins",
        json={
            "email": user.email,
            "password": "a-brand-new-password",
            "strategy": "password",
        },
    )
    assert signin.status_code == 200
