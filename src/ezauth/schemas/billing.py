"""Billing responses expose decimal USD while all mutations use exact integer cents."""

import uuid
from datetime import datetime
from decimal import Decimal, DecimalException
from typing import Literal

from pydantic import BaseModel, ConfigDict

from ezauth.config import settings


def usd_to_cents(value: Decimal) -> int:
    try:
        if not value.is_finite() or abs(value) > Decimal(2**63 - 1) / 100:
            raise ValueError("Amount is outside the supported range")
        cents = value * 100
        if cents != cents.to_integral_value():
            raise ValueError("Amount must have at most two decimal places")
        return int(cents)
    except DecimalException as exc:
        raise ValueError("Invalid amount") from exc


def validate_topup_amount(value: Decimal) -> int:
    cents = usd_to_cents(value)
    if not settings.billing_min_topup_cents <= cents <= settings.billing_max_topup_cents:
        raise ValueError("Amount is outside the allowed top-up range")
    return cents


class TopupRequest(BaseModel):
    amount_usd: Decimal
    method: Literal["crypto", "stripe", "paypal"]
    chain: str | None = None


class UsageResponse(BaseModel):
    users: int
    storage_bytes: int
    estimated_monthly_cost_cents: Decimal


class BalanceResponse(BaseModel):
    balance_cents: int
    balance_usd: Decimal
    paused: bool
    usage: UsageResponse
    payment_methods: list[str]
    crypto_chains: list[str]


class TopupResponse(BaseModel):
    payment_id: uuid.UUID
    method: str
    status: str
    amount_usd: Decimal
    url: str | None = None
    chain: str | None = None
    address: str | None = None
    amount_native: str | None = None
    expires_at: str | None = None

    @classmethod
    def from_payment(cls, payment):
        details = payment.details or {}
        return cls(
            payment_id=payment.id, method=payment.provider, status=payment.status,
            amount_usd=Decimal(payment.amount_cents) / 100,
            url=details.get("url") or details.get("checkout_url") or details.get("approve_url"),
            **{key: details.get(key) for key in
               ("chain", "address", "amount_native", "expires_at")},
        )


class TransactionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    amount_cents: int
    balance_after_cents: int
    description: str
    provider: str | None
    provider_ref: str | None
    details: dict | None
    created_at: datetime
