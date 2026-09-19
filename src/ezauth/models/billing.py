"""Prepaid balances and append-only ledger entries separate usage from payment rails.

Provider references are unique so callbacks and polling can safely converge on
one credit. Fractional usage is retained separately from integer-cent balances.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ezauth.db.base import Base, TimestampMixin, UUIDPrimaryKey


class BillingAccount(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "billing_accounts"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    balance_cents: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    accrued_cents: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=0, server_default="0")
    paused: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_metered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    email_warnings: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    low_balance_threshold_cents: Mapped[int] = mapped_column(
        Integer, default=500, server_default="500"
    )
    low_balance_warned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    auto_reload_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    auto_reload_threshold_cents: Mapped[int] = mapped_column(
        Integer, default=500, server_default="500"
    )
    auto_reload_amount_cents: Mapped[int] = mapped_column(
        Integer, default=2000, server_default="2000"
    )
    auto_reload_failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stripe_customer_id: Mapped[str | None] = mapped_column(String(255))
    stripe_payment_method_id: Mapped[str | None] = mapped_column(String(255))
    card_brand: Mapped[str | None] = mapped_column(String(32))
    card_last4: Mapped[str | None] = mapped_column(String(4))


class BillingTransaction(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "billing_transactions"
    __table_args__ = (Index("ix_billing_transactions_tenant_created", "tenant_id", "created_at"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(32))
    amount_cents: Mapped[int] = mapped_column(BigInteger)
    balance_after_cents: Mapped[int] = mapped_column(BigInteger)
    description: Mapped[str] = mapped_column(String(255))
    provider: Mapped[str | None] = mapped_column(String(32))
    provider_ref: Mapped[str | None] = mapped_column(String(255), unique=True)
    details: Mapped[dict | None] = mapped_column(JSONB)


class BillingPayment(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "billing_payments"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(32))
    provider_ref: Mapped[str] = mapped_column(String(255), unique=True)
    amount_cents: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    details: Mapped[dict | None] = mapped_column(JSONB)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
