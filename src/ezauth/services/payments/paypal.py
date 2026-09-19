"""PayPal orders become credit only after a verified, matching capture.

Browser returns and webhook deliveries converge on the capture ID in the ledger.
OAuth tokens are kept in memory only until shortly before provider expiry.
"""

import json
import time
import uuid
from urllib.parse import quote

import httpx

from ezauth.config import settings
from ezauth.models.billing import BillingPayment
from ezauth.services.payments import (
    PaymentError,
    check_amount,
    complete,
    locked_payment,
    usd,
    validate_amount,
)

_token = None
_token_until = 0
_token_config = None


def configured() -> bool:
    return settings.paypal_configured


async def _access_token():
    global _token, _token_until, _token_config
    config = (settings.paypal_api_base, settings.paypal_client_id, settings.paypal_client_secret)
    if _token and _token_config == config and time.monotonic() < _token_until:
        return _token
    if not configured():
        raise PaymentError("PayPal is not configured")
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                f"{settings.paypal_api_base}/v1/oauth2/token",
                auth=(settings.paypal_client_id, settings.paypal_client_secret),
                data={"grant_type": "client_credentials"},
            )
            response.raise_for_status()
            data = response.json()
            _token = data["access_token"]
            _token_until = time.monotonic() + max(0, int(data["expires_in"]) - 60)
            _token_config = config
            return _token
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        raise PaymentError("PayPal authentication failed") from exc


async def _request(method, path, **kwargs):
    token = await _access_token()
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.request(
                method, f"{settings.paypal_api_base}{path}",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                **kwargs,
            )
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise PaymentError("Malformed provider response")
            return data
    except (httpx.HTTPError, ValueError) as exc:
        raise PaymentError("PayPal request failed") from exc


async def create_topup(db, account, amount_cents, *, return_url, cancel_url):
    validate_amount(amount_cents)
    payment_id = uuid.uuid4()
    data = await _request("POST", "/v2/checkout/orders", json={
        "intent": "CAPTURE", "purchase_units": [{
            "reference_id": str(payment_id),
            "amount": {"currency_code": "USD", "value": usd(amount_cents)},
        }], "payment_source": {"paypal": {"experience_context": {
            "return_url": return_url, "cancel_url": cancel_url, "user_action": "PAY_NOW",
        }}},
    })
    approve_url = next((link.get("href") for link in data.get("links", [])
                        if link.get("rel") in ("payer-action", "approve")), None)
    if not data.get("id") or not approve_url:
        raise PaymentError("PayPal returned no approval URL")
    payment = BillingPayment(
        id=payment_id, tenant_id=account.tenant_id, provider="paypal", provider_ref=data["id"],
        amount_cents=amount_cents, status="pending", details={"approve_url": approve_url},
    )
    db.add(payment)
    await db.flush()
    return payment


async def _complete_capture(db, account, payment, capture_data):
    if capture_data.get("status") != "COMPLETED":
        raise PaymentError("PayPal capture has not completed")
    amount = capture_data.get("amount") or {}
    if amount.get("currency_code") != "USD" or not capture_data.get("id"):
        raise PaymentError("Invalid PayPal capture")
    check_amount(amount.get("value"), payment.amount_cents)
    return await complete(db, account, payment, capture_data["id"])


async def capture(db, order_id):
    account, payment = await locked_payment(db, "paypal", order_id)
    if payment.status == "completed":
        return payment
    path = f"/v2/checkout/orders/{quote(order_id, safe='')}"
    try:
        data = await _request("POST", f"{path}/capture", json={})
    except PaymentError:
        # A provider capture may have succeeded before a lost response or rollback.
        data = await _request("GET", path)
    if data.get("id") != order_id:
        raise PaymentError("PayPal order does not match")
    if data.get("status") != "COMPLETED":
        return payment
    try:
        unit = data["purchase_units"][0]
        if unit.get("reference_id") != str(payment.id):
            raise PaymentError("PayPal purchase unit does not match")
        capture_data = unit["payments"]["captures"][0]
    except (KeyError, IndexError, TypeError) as exc:
        raise PaymentError("Invalid PayPal capture response") from exc
    return await _complete_capture(db, account, payment, capture_data)


async def handle_webhook(db, headers, body):
    try:
        return await _handle_webhook(db, headers, body)
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        raise PaymentError("Malformed PayPal event") from exc


async def _handle_webhook(db, headers, body):
    try:
        event = json.loads(body) if isinstance(body, (bytes, str)) else body
        if not isinstance(event, dict):
            raise ValueError
    except (ValueError, TypeError) as exc:
        raise PaymentError("Invalid PayPal webhook") from exc
    if settings.paypal_webhook_id:
        normalized = {key.lower(): value for key, value in headers.items()}
        data = await _request("POST", "/v1/notifications/verify-webhook-signature", json={
            "auth_algo": normalized.get("paypal-auth-algo"),
            "cert_url": normalized.get("paypal-cert-url"),
            "transmission_id": normalized.get("paypal-transmission-id"),
            "transmission_sig": normalized.get("paypal-transmission-sig"),
            "transmission_time": normalized.get("paypal-transmission-time"),
            "webhook_id": settings.paypal_webhook_id, "webhook_event": event,
        })
        if data.get("verification_status") != "SUCCESS":
            raise PaymentError("Invalid PayPal webhook signature")
    if event.get("event_type") != "PAYMENT.CAPTURE.COMPLETED":
        return
    resource = event.get("resource") or {}
    capture_id = resource.get("id")
    if not isinstance(capture_id, str):
        raise PaymentError("Missing PayPal capture ID")
    # Authenticated retrieval also secures installations without a webhook ID.
    verified = await _request("GET", f"/v2/payments/captures/{quote(capture_id, safe='')}")
    if verified.get("id") != capture_id:
        raise PaymentError("PayPal capture does not match")
    order_id = verified.get("supplementary_data", {}).get("related_ids", {}).get("order_id")
    if not isinstance(order_id, str):
        raise PaymentError("Missing PayPal order ID")
    account, payment = await locked_payment(db, "paypal", order_id)
    return await _complete_capture(db, account, payment, verified)
