"""Stripe Checkout and saved cards share the payment-intent ledger key.

The small async adapter isolates synchronous SDK calls from the event loop and
lets tests replace provider I/O without bypassing completion validation.
"""

import asyncio
import uuid

import stripe as sdk
from sqlalchemy import select

from ezauth.config import settings
from ezauth.models.billing import BillingAccount, BillingPayment
from ezauth.models.tenant import Tenant
from ezauth.services.payments import PaymentError, complete, locked_payment, validate_amount


class _StripeAPI:
    async def create_customer(self, **kwargs):
        return await asyncio.to_thread(
            sdk.Customer.create, api_key=settings.stripe_secret_key, **kwargs,
        )

    async def create_checkout(self, **kwargs):
        return await asyncio.to_thread(
            sdk.checkout.Session.create, api_key=settings.stripe_secret_key, **kwargs,
        )

    async def retrieve_intent(self, intent_id):
        return await asyncio.to_thread(
            sdk.PaymentIntent.retrieve, intent_id, api_key=settings.stripe_secret_key,
        )

    async def retrieve_method(self, method_id):
        return await asyncio.to_thread(
            sdk.PaymentMethod.retrieve, method_id, api_key=settings.stripe_secret_key,
        )

    async def create_intent(self, **kwargs):
        return await asyncio.to_thread(
            sdk.PaymentIntent.create, api_key=settings.stripe_secret_key, **kwargs,
        )

    async def detach_method(self, method_id):
        return await asyncio.to_thread(
            sdk.PaymentMethod.detach, method_id, api_key=settings.stripe_secret_key,
        )


_api = _StripeAPI()


def configured() -> bool:
    return settings.stripe_configured


async def create_topup(db, account, amount_cents, *, save_card, success_url, cancel_url):
    from ezauth.services.billing import owner_emails_for_tenant

    validate_amount(amount_cents)
    if not configured():
        raise PaymentError("Card payments are not configured")
    # Serialize customer creation against concurrent top-ups for this tenant.
    await db.refresh(account, with_for_update=True)
    payment_id = uuid.uuid4()
    try:
        if not account.stripe_customer_id:
            tenant = await db.get(Tenant, account.tenant_id)
            emails = await owner_emails_for_tenant(db, tenant)
            customer = await _api.create_customer(
                **({"email": emails[0]} if emails else {}),
                metadata={"tenant_id": str(account.tenant_id)},
            )
            account.stripe_customer_id = customer["id"]
        options = {
            "mode": "payment", "customer": account.stripe_customer_id,
            "success_url": success_url, "cancel_url": cancel_url,
            "metadata": {"tenant_id": str(account.tenant_id), "payment_id": str(payment_id)},
            "line_items": [{"quantity": 1, "price_data": {
                "currency": settings.billing_currency, "unit_amount": amount_cents,
                "product_data": {"name": "ezAuth credit"},
            }}],
        }
        if save_card:
            options["payment_intent_data"] = {"setup_future_usage": "off_session"}
        session = await _api.create_checkout(**options)
        payment = BillingPayment(
            id=payment_id, tenant_id=account.tenant_id, provider="stripe",
            provider_ref=session["id"], amount_cents=amount_cents, status="pending",
            details={"url": session["url"], "save_card": bool(save_card),
                     "customer_id": account.stripe_customer_id},
        )
    except Exception as exc:
        raise PaymentError("Could not create card checkout") from exc
    db.add(payment)
    await db.flush()
    return payment


async def handle_webhook(db, payload: bytes, sig_header: str):
    if not settings.stripe_webhook_secret:
        raise PaymentError("Stripe webhooks are not configured")
    try:
        event = sdk.Webhook.construct_event(payload, sig_header, settings.stripe_webhook_secret)
    except Exception as exc:
        raise PaymentError("Invalid Stripe signature") from exc
    try:
        await _handle_event(db, event)
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        raise PaymentError("Malformed Stripe event") from exc


async def _handle_event(db, event):
    from ezauth.services import billing

    obj = event["data"]["object"]
    if event["type"] == "checkout.session.completed" and obj.get("payment_status") == "paid":
        account, payment = await locked_payment(db, "stripe", obj["id"])
        metadata = obj.get("metadata") or {}
        customer_id = (payment.details or {}).get("customer_id", account.stripe_customer_id)
        if (metadata.get("tenant_id") != str(account.tenant_id)
                or metadata.get("payment_id") != str(payment.id)
                or obj.get("amount_total") != payment.amount_cents
                or obj.get("currency") != settings.billing_currency
                or obj.get("customer") != customer_id
                or not isinstance(obj.get("payment_intent"), str)):
            raise PaymentError("Stripe payment does not match the top-up")
        if payment.status == "completed":
            return
        if (payment.details or {}).get("save_card"):
            try:
                intent = await _api.retrieve_intent(obj["payment_intent"])
                method_id = intent["payment_method"]
                method = await _api.retrieve_method(method_id)
                if method.get("customer") != customer_id:
                    raise PaymentError("Saved card belongs to another customer")
                account.stripe_customer_id = customer_id
                account.stripe_payment_method_id = method_id
                account.card_brand = method["card"]["brand"]
                account.card_last4 = method["card"]["last4"]
                account.auto_reload_failed_at = None
            except Exception as exc:
                raise PaymentError("Could not retrieve saved card") from exc
        await complete(db, account, payment, obj["payment_intent"])
    elif event["type"] == "payment_intent.succeeded":
        metadata = obj.get("metadata") or {}
        if not metadata.get("tenant_id") or metadata.get("auto_reload") != "1":
            return
        try:
            tenant_id = uuid.UUID(metadata["tenant_id"])
        except (ValueError, TypeError) as exc:
            raise PaymentError("Invalid tenant metadata") from exc
        account = await db.scalar(select(BillingAccount).where(
            BillingAccount.tenant_id == tenant_id,
        ).with_for_update().execution_options(populate_existing=True))
        amount = obj.get("amount_received")
        # A signed intent carries our tenant binding even after card removal.
        if (account is None or obj.get("currency") != settings.billing_currency
                or not isinstance(amount, int) or amount <= 0):
            raise PaymentError("Invalid auto-reload payment")
        await billing.credit(db, account, amount, kind="topup", description="Automatic card top-up",
                             provider="stripe", provider_ref=obj["id"])


async def charge_saved_card(account, amount_cents) -> str:
    validate_amount(amount_cents)
    if not configured() or not account.stripe_payment_method_id:
        raise PaymentError("No saved card available")
    try:
        intent = await _api.create_intent(
            amount=amount_cents, currency=settings.billing_currency,
            customer=account.stripe_customer_id, payment_method=account.stripe_payment_method_id,
            off_session=True, confirm=True,
            metadata={"tenant_id": str(account.tenant_id), "auto_reload": "1"},
        )
        if intent.get("status") != "succeeded":
            raise PaymentError("Card charge was not successful")
        return intent["id"]
    except Exception as exc:
        raise PaymentError("Card auto-reload failed") from exc


async def detach_card(account):
    if account.stripe_payment_method_id:
        try:
            await _api.detach_method(account.stripe_payment_method_id)
        except Exception as exc:
            raise PaymentError("Could not remove card") from exc
    account.stripe_customer_id = None
    account.stripe_payment_method_id = None
    account.card_brand = None
    account.card_last4 = None
    account.auto_reload_failed_at = None
