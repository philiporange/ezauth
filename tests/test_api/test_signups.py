import pytest
from httpx import ASGITransport, AsyncClient


@pytest.mark.skipif(True, reason="Requires live DB+Redis+SES")
async def test_signup_success(client, app):
    resp = await client.post(
        "/v1/signups",
        json={"email": "new@example.com", "redirect_url": "https://example.com/welcome"},
        headers={"X-Publishable-Key": app.publishable_key},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "verification_sent"
    assert "user_id" in data


@pytest.mark.skipif(True, reason="Requires live DB+Redis+SES")
async def test_signup_duplicate(client, app, user):
    resp = await client.post(
        "/v1/signups",
        json={"email": user.email},
        headers={"X-Publishable-Key": app.publishable_key},
    )
    assert resp.status_code == 409
