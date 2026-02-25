"""Integration tests for full auth flows.

These require a running PostgreSQL, Redis, and (mocked) SES.
"""
import pytest


@pytest.mark.skipif(True, reason="Requires full infrastructure")
async def test_signup_verify_me_logout_flow(client, app):
    """Test: signup -> verify -> /me -> logout"""
    # 1. Sign up
    signup_resp = await client.post(
        "/v1/signups",
        json={"email": "flow@example.com"},
        headers={"X-Publishable-Key": app.publishable_key},
    )
    assert signup_resp.status_code == 200
    assert signup_resp.json()["status"] == "verification_sent"

    # 2. Verify email (would need to extract token from DB or mock)
    # ... token extraction ...

    # 3. GET /me should return user info

    # 4. Logout should clear session


@pytest.mark.skipif(True, reason="Requires full infrastructure")
async def test_signin_password_flow(client, app, user):
    """Test: signin with password -> session -> /me"""
    resp = await client.post(
        "/v1/signins",
        json={"email": user.email, "password": "testpassword123", "strategy": "password"},
        headers={"X-Publishable-Key": app.publishable_key},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["user_id"] == str(user.id)
