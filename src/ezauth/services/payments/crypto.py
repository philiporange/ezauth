"""Crypto callbacks are hints only: credit requires authenticated provider status.

The confirmations API owns address allocation and chain observation. Persist the
quoted native amount and validate its identity when polling a completed payment.
"""

from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import httpx
from loguru import logger
from sqlalchemy import select

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


def configured() -> bool:
    return settings.crypto_configured


async def _request(method, path, **kwargs):
    if not configured():
        raise PaymentError("Crypto payments are not configured")
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.request(
                method, f"{settings.confirmations_api_url.rstrip('/')}{path}",
                headers={"X-API-Key": settings.confirmations_api_key}, **kwargs,
            )
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise PaymentError("Malformed provider response")
            return data
    except (httpx.HTTPError, ValueError) as exc:
        raise PaymentError("Confirmations API request failed") from exc


async def create_topup(db, account, amount_cents, *, chain):
    validate_amount(amount_cents)
    if chain not in settings.crypto_chain_list:
        raise PaymentError("Unknown crypto chain")
    data = await _request("POST", "/payments", json={
        "usd_amount": usd(amount_cents), "chain": chain,
        "callback_url": f"{settings.public_base_url}/v1/billing/webhooks/crypto",
    })
    check_amount(data.get("usd_amount"), amount_cents)
    if data.get("chain") != chain or not all(data.get(k) for k in (
        "payment_id", "address", "amount_native", "expires_at",
    )):
        raise PaymentError("Invalid crypto payment response")
    payment = BillingPayment(
        tenant_id=account.tenant_id, provider="crypto", provider_ref=data["payment_id"],
        amount_cents=amount_cents, status="pending",
        details={key: data[key] for key in ("chain", "address", "amount_native", "expires_at")},
    )
    db.add(payment)
    await db.flush()
    return payment


async def confirm(db, payment_id):
    account, payment = await locked_payment(db, "crypto", str(payment_id))
    if payment.status == "completed":
        return payment
    data = await _request("GET", f"/payments/{quote(str(payment_id), safe='')}")
    check_amount(data.get("usd_amount"), payment.amount_cents)
    details = payment.details or {}
    if data.get("payment_id") != payment.provider_ref or any(
        data.get(key) != details.get(key) for key in ("chain", "address", "amount_native")
    ):
        raise PaymentError("Crypto payment identity does not match")
    if data.get("status") == "PAID":
        await complete(db, account, payment, payment.provider_ref, {
            **details, "tx_hash": data.get("tx_hash"),
            "confirmations": data.get("confirmations"),
        })
    elif data.get("status") == "EXPIRED":
        payment.status = "expired"
        await db.flush()
    elif data.get("status") != "PENDING":
        raise PaymentError("Unknown crypto payment status")
    return payment


async def handle_callback(db, body):
    if not isinstance(body, dict) or not isinstance(body.get("payment_id"), str):
        raise PaymentError("Missing payment_id")
    return await confirm(db, body["payment_id"])


async def poll_pending(db):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=48)
    payments = (await db.scalars(select(BillingPayment).where(
        BillingPayment.provider == "crypto", BillingPayment.status == "pending",
    ))).all()
    for payment in payments:
        local_id = payment.id
        try:
            async with db.begin_nested():
                if payment.created_at < cutoff:
                    _, locked = await locked_payment(db, "crypto", payment.provider_ref)
                    if locked.status == "pending":
                        locked.status = "expired"
                        await db.flush()
                else:
                    await confirm(db, payment.provider_ref)
        except Exception:
            logger.exception("Could not poll crypto payment {}", local_id)
