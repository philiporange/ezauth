"""Provider fixtures verify that retries credit once and forged callbacks cannot pay."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import func, select

from ezauth.config import settings
from ezauth.models.billing import BillingPayment, BillingTransaction
from ezauth.services import billing
from ezauth.services.payments import PaymentError, crypto, paypal, stripe


async def pending(db, tenant, provider, **kwargs):
    account = await billing.get_or_create_account(db, tenant.id)
    payment = BillingPayment(tenant_id=tenant.id, provider=provider, provider_ref=f"{provider}_123",
                             amount_cents=2000, status="pending", **kwargs)
    db.add(payment)
    await db.flush()
    return account, payment


def mock_http(monkeypatch, module, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(module.httpx, "AsyncClient", lambda **kwargs: original(
        transport=httpx.MockTransport(handler), **kwargs,
    ))


@pytest.mark.asyncio
async def test_stripe_checkout_credits_once_and_saves_card(db, tenant, monkeypatch):
    account, payment = await pending(db, tenant, "stripe", details={"save_card": True})
    account.stripe_customer_id = "cus_1"
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_test")
    event = {"type": "checkout.session.completed", "data": {"object": {
        "id": payment.provider_ref, "payment_status": "paid", "payment_intent": "pi_1",
        "metadata": {"tenant_id": str(tenant.id), "payment_id": str(payment.id)},
        "amount_total": 2000, "currency": "usd", "customer": "cus_1",
    }}}
    monkeypatch.setattr(stripe.sdk.Webhook, "construct_event", lambda *args: event)
    monkeypatch.setattr(stripe._api, "retrieve_intent", AsyncMock(return_value={
        "payment_method": "pm_1",
    }))
    monkeypatch.setattr(stripe._api, "retrieve_method", AsyncMock(return_value={
        "customer": "cus_1", "card": {"brand": "visa", "last4": "4242"},
    }))
    await stripe.handle_webhook(db, b"event", "signature")
    await stripe.handle_webhook(db, b"event", "signature")
    assert account.balance_cents == settings.billing_welcome_credit_cents + 2000
    assert account.stripe_payment_method_id == "pm_1"
    assert account.card_last4 == "4242"
    assert payment.status == "completed"
    assert await db.scalar(select(func.count(BillingTransaction.id)).where(
        BillingTransaction.provider_ref == "pi_1",
    )) == 1


@pytest.mark.asyncio
async def test_stripe_rejects_mismatched_amount(db, tenant, monkeypatch):
    account, payment = await pending(db, tenant, "stripe")
    account.stripe_customer_id = "cus_1"
    monkeypatch.setattr(settings, "stripe_webhook_secret", "secret")
    monkeypatch.setattr(stripe.sdk.Webhook, "construct_event", lambda *args: {
        "type": "checkout.session.completed", "data": {"object": {
            "id": payment.provider_ref, "payment_status": "paid", "payment_intent": "pi_1",
            "metadata": {"tenant_id": str(tenant.id), "payment_id": str(payment.id)},
            "amount_total": 1, "currency": "usd", "customer": "cus_1",
        }},
    })
    with pytest.raises(PaymentError):
        await stripe.handle_webhook(db, b"event", "signature")
    assert payment.status == "pending"


@pytest.mark.asyncio
async def test_paypal_capture_credits_completed_order(db, tenant, monkeypatch):
    account, payment = await pending(db, tenant, "paypal")
    monkeypatch.setattr(settings, "paypal_client_id", "client")
    monkeypatch.setattr(settings, "paypal_client_secret", "secret")
    monkeypatch.setattr(paypal, "_token", None)

    def handler(request):
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "token", "expires_in": 3600})
        assert request.url.path == f"/v2/checkout/orders/{payment.provider_ref}/capture"
        return httpx.Response(200, json={
            "id": payment.provider_ref, "status": "COMPLETED", "purchase_units": [{
                "reference_id": str(payment.id), "payments": {"captures": [{
                    "id": "capture_1", "status": "COMPLETED",
                    "amount": {"currency_code": "USD", "value": "20.00"},
                }]},
            }],
        })

    mock_http(monkeypatch, paypal, handler)
    await paypal.capture(db, payment.provider_ref)
    await paypal.capture(db, payment.provider_ref)
    assert account.balance_cents == settings.billing_welcome_credit_cents + 2000
    assert payment.status == "completed"


@pytest.mark.asyncio
async def test_crypto_callback_does_not_trust_body_and_poll_can_pay(db, tenant, monkeypatch):
    details = {"chain": "base", "address": "0xabc", "amount_native": "0.01",
               "expires_at": "2026-10-01T00:00:00Z"}
    account, payment = await pending(db, tenant, "crypto", details=details)
    monkeypatch.setattr(settings, "confirmations_api_key", "key")
    status = {"value": "PENDING"}

    def handler(request):
        assert request.headers["X-API-Key"] == "key"
        return httpx.Response(200, json={
            "payment_id": payment.provider_ref, "status": status["value"],
            "chain": "base", "address": "0xabc", "amount_native": "0.01",
            "usd_amount": "20.00", "tx_hash": "0xtx", "confirmations": 4,
        })

    mock_http(monkeypatch, crypto, handler)
    await crypto.handle_callback(db, {"payment_id": payment.provider_ref, "status": "PAID"})
    assert account.balance_cents == settings.billing_welcome_credit_cents
    assert payment.status == "pending"
    status["value"] = "PAID"
    await crypto.confirm(db, payment.provider_ref)
    await crypto.confirm(db, payment.provider_ref)
    assert account.balance_cents == settings.billing_welcome_credit_cents + 2000
    assert payment.details["expires_at"] == details["expires_at"]
    entry = await db.scalar(select(BillingTransaction).where(
        BillingTransaction.provider_ref == payment.provider_ref,
    ))
    assert entry.details["tx_hash"] == "0xtx"


@pytest.mark.asyncio
async def test_crypto_poll_expires_stale_attempt_without_request(db, tenant, monkeypatch):
    _, payment = await pending(db, tenant, "crypto",
                               created_at=datetime.now(timezone.utc) - timedelta(hours=49))
    request = AsyncMock(side_effect=AssertionError("Must not poll stale attempts"))
    monkeypatch.setattr(crypto, "_request", request)
    await crypto.poll_pending(db)
    assert payment.status == "expired"
    request.assert_not_called()


@pytest.mark.asyncio
async def test_paypal_unverified_webhook_rejected(db, monkeypatch):
    monkeypatch.setattr(settings, "paypal_webhook_id", "hook")
    monkeypatch.setattr(paypal, "_request", AsyncMock(return_value={
        "verification_status": "FAILURE",
    }))
    with pytest.raises(PaymentError, match="signature"):
        await paypal.handle_webhook(db, {}, {"event_type": "PAYMENT.CAPTURE.COMPLETED"})


@pytest.mark.asyncio
async def test_detach_clears_card_and_pending_saved_checkout_can_complete(db, tenant, monkeypatch):
    account, payment = await pending(db, tenant, "stripe", details={
        "save_card": True, "customer_id": "cus_pending",
    })
    account.stripe_customer_id = "cus_pending"
    account.stripe_payment_method_id = "pm_old"
    account.card_brand = "visa"
    account.card_last4 = "1111"
    account.auto_reload_failed_at = datetime.now(timezone.utc)
    detach = AsyncMock()
    monkeypatch.setattr(stripe._api, "detach_method", detach)
    await stripe.detach_card(account)
    detach.assert_awaited_once_with("pm_old")
    assert account.stripe_customer_id is None
    assert account.stripe_payment_method_id is None
    assert account.card_brand is None
    assert account.card_last4 is None
    assert account.auto_reload_failed_at is None
    monkeypatch.setattr(settings, "stripe_webhook_secret", "secret")
    monkeypatch.setattr(stripe.sdk.Webhook, "construct_event", lambda *args: {
        "type": "checkout.session.completed", "data": {"object": {
            "id": payment.provider_ref, "payment_status": "paid", "payment_intent": "pi_pending",
            "metadata": {"tenant_id": str(tenant.id), "payment_id": str(payment.id)},
            "amount_total": 2000, "currency": "usd", "customer": "cus_pending",
        }},
    })
    monkeypatch.setattr(stripe._api, "retrieve_intent", AsyncMock(return_value={
        "payment_method": "pm_new",
    }))
    monkeypatch.setattr(stripe._api, "retrieve_method", AsyncMock(return_value={
        "customer": "cus_pending", "card": {"brand": "visa", "last4": "4242"},
    }))
    await stripe.handle_webhook(db, b"event", "signature")
    assert account.stripe_customer_id == "cus_pending"
    assert account.stripe_payment_method_id == "pm_new"
    assert payment.status == "completed"


@pytest.mark.asyncio
async def test_malformed_verified_stripe_event_is_payment_error(db, monkeypatch):
    monkeypatch.setattr(settings, "stripe_webhook_secret", "secret")
    monkeypatch.setattr(stripe.sdk.Webhook, "construct_event", lambda *args: {"data": None})
    with pytest.raises(PaymentError, match="Malformed"):
        await stripe.handle_webhook(db, b"event", "signature")


@pytest.mark.asyncio
async def test_delayed_auto_reload_credits_after_customer_changes(db, tenant, monkeypatch):
    account = await billing.get_or_create_account(db, tenant.id)
    account.stripe_customer_id = "cus_replacement"
    monkeypatch.setattr(settings, "stripe_webhook_secret", "secret")
    monkeypatch.setattr(stripe.sdk.Webhook, "construct_event", lambda *args: {
        "type": "payment_intent.succeeded", "data": {"object": {
            "id": "pi_delayed", "customer": "cus_previous", "currency": "usd",
            "amount_received": 2000,
            "metadata": {"tenant_id": str(tenant.id), "auto_reload": "1"},
        }},
    })
    await stripe.handle_webhook(db, b"event", "signature")
    await stripe.handle_webhook(db, b"event", "signature")
    assert account.balance_cents == settings.billing_welcome_credit_cents + 2000
    assert account.stripe_customer_id == "cus_replacement"
