"""Shared payment invariants keep provider completions tied to local attempts.

All rails lock the account before the attempt and credit through the ledger;
provider notifications can therefore race with browser returns and polling.
"""

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy import select

from ezauth.config import settings
from ezauth.models.billing import BillingAccount, BillingPayment


class PaymentError(Exception):
    """A provider request or payment verification could not be completed."""


def validate_amount(amount_cents: int) -> None:
    if not settings.billing_min_topup_cents <= amount_cents <= settings.billing_max_topup_cents:
        raise PaymentError("Top-up amount is outside the allowed range")


def usd(amount_cents: int) -> str:
    return f"{Decimal(amount_cents) / 100:.2f}"


def check_amount(value, amount_cents: int) -> None:
    try:
        valid = Decimal(str(value)) == Decimal(amount_cents) / 100
    except (InvalidOperation, ValueError):
        valid = False
    if not valid:
        raise PaymentError("Payment amount does not match the top-up")


async def locked_payment(db, provider: str, provider_ref: str):
    payment = await db.scalar(select(BillingPayment).where(
        BillingPayment.provider == provider, BillingPayment.provider_ref == provider_ref,
    ))
    if payment is None:
        raise PaymentError("Payment not found")
    account = await db.scalar(select(BillingAccount).where(
        BillingAccount.tenant_id == payment.tenant_id,
    ).with_for_update().execution_options(populate_existing=True))
    if account is None:
        raise PaymentError("Billing account not found")
    await db.refresh(payment, with_for_update=True)
    return account, payment


async def complete(db, account, payment, provider_ref: str, details=None):
    from ezauth.services import billing

    if payment.status == "completed":
        return payment
    await billing.credit(
        db, account, payment.amount_cents, kind="topup", description="Credit top-up",
        provider=payment.provider, provider_ref=provider_ref, details=details,
    )
    payment.status = "completed"
    payment.completed_at = datetime.now(timezone.utc)
    await db.flush()
    return payment
