"""Billing recovery must stay authenticated and reachable when tenant usage stops."""

import httpx

from ezauth.config import settings
from ezauth.services import billing


async def test_paused_enforcement_and_recovery(client, db, app):
    account = await billing.get_or_create_account(db, app.tenant_id)
    account.paused = True
    await db.flush()
    for method, path, kwargs in [
        ("post", "/v1/signups", {"json": {"email": "new@example.com"}}),
        ("get", "/v1/users", {"headers": {"Authorization": f"Bearer {app.secret_key}"}}),
        ("get", "/auth/login", {}),
        ("get", "/v1/tables", {"headers": {"Authorization": f"Bearer {app.secret_key}"}}),
    ]:
        response = await getattr(client, method)(path, **kwargs)
        assert response.status_code == 402, response.text
        assert response.json()["detail"]["error"] == "billing_paused"
    assert (await client.get(f"/.well-known/jwks.json?app_id={app.id}")).status_code == 200
    response = await client.get("/v1/billing", headers={
        "Authorization": f"Bearer {app.secret_key}",
    })
    assert response.status_code == 200
    assert response.json()["paused"] is True


async def test_balance_shape(client, app):
    response = await client.get("/v1/billing", headers={
        "Authorization": f"Bearer {app.secret_key}",
    })
    assert response.status_code == 200
    data = response.json()
    assert data["balance_cents"] == settings.billing_welcome_credit_cents
    assert set(data) == {
        "balance_cents", "balance_usd", "paused", "usage", "payment_methods", "crypto_chains",
    }
    assert data["usage"]["users"] == 0
    assert (await client.get("/v1/billing")).status_code == 401


async def test_unconfigured_topup(client, app, monkeypatch):
    monkeypatch.setattr(settings, "stripe_secret_key", "")
    response = await client.post("/v1/billing/topups", headers={
        "Authorization": f"Bearer {app.secret_key}",
    }, json={"amount_usd": "20.00", "method": "stripe"})
    assert response.status_code == 400


async def test_crypto_topup_and_tenant_scope(client, db, app, monkeypatch):
    from ezauth.models.billing import BillingPayment
    from ezauth.models.tenant import Tenant
    from ezauth.services.payments import crypto

    monkeypatch.setattr(settings, "confirmations_api_key", "test-key")
    original_client = httpx.AsyncClient

    def handler(request):
        assert request.headers["X-API-Key"] == "test-key"
        return httpx.Response(200, json={
            "payment_id": "external-payment", "chain": "base", "address": "0x123",
            "amount_wei": "100000", "amount_native": "0.0000000000001",
            "usd_amount": "20.00", "expires_at": "2026-09-09T12:00:00Z",
        })

    monkeypatch.setattr(crypto.httpx, "AsyncClient", lambda **kwargs: original_client(
        **{**kwargs, "transport": httpx.MockTransport(handler)},
    ))
    headers = {"Authorization": f"Bearer {app.secret_key}"}
    response = await client.post("/v1/billing/topups", headers=headers, json={
        "amount_usd": "20.00", "method": "crypto", "chain": "base",
    })
    assert response.status_code == 200, response.text
    assert response.json()["address"] == "0x123"
    for amount in ["0", "4.99", "1000.01", "5.001"]:
        response = await client.post("/v1/billing/topups", headers=headers, json={
            "amount_usd": amount, "method": "crypto", "chain": "base",
        })
        assert response.status_code == 400
    other = Tenant(name="Other")
    db.add(other)
    await db.flush()
    payment = BillingPayment(
        tenant_id=other.id, provider="crypto", provider_ref="other", amount_cents=2000,
        status="pending",
    )
    db.add(payment)
    await db.flush()
    assert (await client.get(
        f"/v1/billing/topups/{payment.id}", headers=headers,
    )).status_code == 404


async def test_billing_disabled_bypasses_pause(client, db, app, monkeypatch):
    account = await billing.get_or_create_account(db, app.tenant_id)
    account.paused = True
    await db.flush()
    monkeypatch.setattr(settings, "billing_enabled", False)
    response = await client.get("/v1/users", headers={
        "Authorization": f"Bearer {app.secret_key}",
    })
    assert response.status_code == 200


async def test_invalid_webhooks(client):
    for provider in ["stripe", "paypal", "crypto"]:
        response = await client.post(f"/v1/billing/webhooks/{provider}", content="not json")
        assert response.status_code == 400
