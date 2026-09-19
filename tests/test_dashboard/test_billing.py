"""Billing pages preserve tenant ownership, CSRF and exact-cent settings.

These exercise the real dashboard session dependency so paused tenants can
recover without weakening the dashboard's authorization boundaries.
"""

from decimal import Decimal

import pytest

from ezauth.dashboard.auth import SESSION_COOKIE, create_dashboard_session
from ezauth.models.billing import BillingPayment
from ezauth.models.tenant import Tenant
from ezauth.services import billing


async def _login(client, redis, email="owner@example.com", *, is_super=False):
    session_id, csrf = await create_dashboard_session(redis, email, is_super)
    client.cookies.set(SESSION_COOKIE, session_id)
    return csrf


@pytest.fixture
async def owned_account(db, tenant):
    tenant.owner_email = "owner@example.com"
    await db.flush()
    return await billing.get_or_create_account(db, tenant.id)


async def test_detail_owner_renders_balance(client, redis, tenant, owned_account):
    await _login(client, redis)
    response = await client.get(f"/dashboard/billing/{tenant.id}")
    assert response.status_code == 200
    assert f"${Decimal(owned_account.balance_cents) / 100:.2f}" in response.text
    assert "Auto-reload and alerts" in response.text
    assert "History" in response.text


async def test_detail_non_owner_is_not_found(client, redis, tenant, owned_account):
    await _login(client, redis, "other@example.com")
    response = await client.get(f"/dashboard/billing/{tenant.id}")
    assert response.status_code == 404


async def test_single_tenant_list_redirects(client, redis, tenant, owned_account):
    await _login(client, redis)
    response = await client.get("/dashboard/billing")
    assert response.status_code == 302
    assert response.headers["location"] == f"/dashboard/billing/{tenant.id}"


async def test_settings_persist(client, redis, db, tenant, owned_account):
    csrf = await _login(client, redis)
    response = await client.post(f"/dashboard/billing/{tenant.id}/settings", data={
        "csrf_token": csrf, "low_balance_threshold": "7.25",
        "auto_reload_enabled": "on", "auto_reload_threshold": "8.50",
        "auto_reload_amount": "30.00",
    })
    assert response.status_code == 303
    await db.refresh(owned_account)
    assert owned_account.email_warnings is False
    assert owned_account.low_balance_threshold_cents == 725
    assert owned_account.auto_reload_enabled is True
    assert owned_account.auto_reload_threshold_cents == 850
    assert owned_account.auto_reload_amount_cents == 3000


@pytest.mark.parametrize("amount", ["NaN", "Infinity", "1.234", "-5"])
async def test_settings_reject_invalid_money(client, redis, tenant, owned_account, amount):
    csrf = await _login(client, redis)
    response = await client.post(f"/dashboard/billing/{tenant.id}/settings", data={
        "csrf_token": csrf, "low_balance_threshold": amount,
        "auto_reload_threshold": "5", "auto_reload_amount": "20",
    })
    assert response.status_code == 400


async def test_settings_require_csrf(client, redis, tenant, owned_account):
    await _login(client, redis)
    response = await client.post(f"/dashboard/billing/{tenant.id}/settings", data={})
    assert response.status_code == 403


async def test_app_owner_can_view_but_cannot_change(
    client, redis, db, tenant, app, owned_account,
):
    app.owner_email = "app-owner@example.com"
    await db.flush()
    csrf = await _login(client, redis, "app-owner@example.com")
    response = await client.get(f"/dashboard/billing/{tenant.id}")
    assert response.status_code == 200
    response = await client.post(f"/dashboard/billing/{tenant.id}/settings", data={
        "csrf_token": csrf, "low_balance_threshold": "5",
        "auto_reload_threshold": "5", "auto_reload_amount": "20",
    })
    assert response.status_code == 404


async def test_adjust_rejected_for_non_superadmin(client, redis, tenant, owned_account):
    csrf = await _login(client, redis)
    response = await client.post(f"/dashboard/billing/{tenant.id}/adjust", data={
        "csrf_token": csrf, "amount_usd": "10", "description": "Test grant",
    })
    assert response.status_code == 403


@pytest.mark.parametrize("amount,delta", [("10.01", 1001), ("-2.99", -299)])
async def test_superadmin_adjusts_balance(
    client, redis, db, tenant, owned_account, amount, delta,
):
    before = owned_account.balance_cents
    csrf = await _login(client, redis, is_super=True)
    response = await client.post(f"/dashboard/billing/{tenant.id}/adjust", data={
        "csrf_token": csrf, "amount_usd": amount, "description": "Correction",
    })
    assert response.status_code == 303
    await db.refresh(owned_account)
    assert owned_account.balance_cents == before + delta


async def test_stripe_flash_requires_matching_completed_session(
    client, redis, db, tenant, owned_account,
):
    await _login(client, redis)
    payment = BillingPayment(tenant_id=tenant.id, provider="stripe", provider_ref="cs_paid",
                             amount_cents=2000, status="completed", details={})
    db.add(payment)
    await db.flush()
    url = f"/dashboard/billing/{tenant.id}?status=success&session_id="
    response = await client.get(url + "cs_other")
    assert "Payment is processing" in response.text
    response = await client.get(url + "cs_paid")
    assert "Payment received" in response.text


async def test_paused_overview_links_to_billing(client, redis, db, tenant, owned_account):
    owned_account.paused = True
    await db.flush()
    await _login(client, redis)
    response = await client.get("/dashboard/")
    assert response.status_code == 200
    assert "Add credit in Billing" in response.text


async def test_payment_check_cannot_cross_tenants(
    client, redis, db, tenant, owned_account, monkeypatch,
):
    other = Tenant(name="Other", owner_email="other@example.com")
    db.add(other)
    await db.flush()
    payment = BillingPayment(tenant_id=other.id, provider="crypto", provider_ref="other_pay",
                             amount_cents=2000, status="pending", details={})
    db.add(payment)
    await db.flush()

    async def forbidden(*args, **kwargs):
        pytest.fail("A different tenant's payment must never be confirmed")

    monkeypatch.setattr("ezauth.services.payments.crypto.confirm", forbidden)
    csrf = await _login(client, redis)
    response = await client.post(
        f"/dashboard/billing/{tenant.id}/payments/{payment.id}/check",
        data={"csrf_token": csrf},
    )
    assert response.status_code == 404


async def test_paypal_return_cannot_cross_tenants(
    client, redis, db, tenant, owned_account, monkeypatch,
):
    other = Tenant(name="Other", owner_email="other@example.com")
    db.add(other)
    await db.flush()
    payment = BillingPayment(tenant_id=other.id, provider="paypal", provider_ref="other_order",
                             amount_cents=2000, status="pending", details={})
    db.add(payment)
    await db.flush()

    async def forbidden(*args, **kwargs):
        pytest.fail("A different tenant's order must never be captured")

    monkeypatch.setattr("ezauth.services.payments.paypal.capture", forbidden)
    await _login(client, redis)
    response = await client.get(
        f"/dashboard/billing/{tenant.id}/paypal/return?token=other_order"
    )
    assert response.status_code == 404
