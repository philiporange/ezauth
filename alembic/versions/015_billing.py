"""Introduce prepaid billing with a welcome grant for existing tenants.

Revision ID: 015
Revises: 014
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None


def _common():
    return [
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "tenant_id", sa.UUID(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "billing_accounts",
        *_common(),
        sa.Column("balance_cents", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("accrued_cents", sa.Numeric(18, 6), nullable=False, server_default="0"),
        sa.Column("paused", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("paused_at", sa.DateTime(timezone=True)),
        sa.Column("last_metered_at", sa.DateTime(timezone=True)),
        sa.Column("email_warnings", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "low_balance_threshold_cents", sa.Integer(), nullable=False, server_default="500"
        ),
        sa.Column("low_balance_warned_at", sa.DateTime(timezone=True)),
        sa.Column(
            "auto_reload_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "auto_reload_threshold_cents", sa.Integer(), nullable=False, server_default="500"
        ),
        sa.Column("auto_reload_amount_cents", sa.Integer(), nullable=False, server_default="2000"),
        sa.Column("auto_reload_failed_at", sa.DateTime(timezone=True)),
        sa.Column("stripe_customer_id", sa.String(255)),
        sa.Column("stripe_payment_method_id", sa.String(255)),
        sa.Column("card_brand", sa.String(32)),
        sa.Column("card_last4", sa.String(4)),
        sa.UniqueConstraint("tenant_id"),
    )
    op.create_table(
        "billing_transactions",
        *_common(),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("amount_cents", sa.BigInteger(), nullable=False),
        sa.Column("balance_after_cents", sa.BigInteger(), nullable=False),
        sa.Column("description", sa.String(255), nullable=False),
        sa.Column("provider", sa.String(32)),
        sa.Column("provider_ref", sa.String(255), unique=True),
        sa.Column("details", postgresql.JSONB()),
    )
    op.create_index("ix_billing_transactions_tenant_id", "billing_transactions", ["tenant_id"])
    op.create_index(
        "ix_billing_transactions_tenant_created",
        "billing_transactions",
        ["tenant_id", "created_at"],
    )
    op.create_table(
        "billing_payments",
        *_common(),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("provider_ref", sa.String(255), nullable=False, unique=True),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("details", postgresql.JSONB()),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_billing_payments_tenant_id", "billing_payments", ["tenant_id"])
    op.execute(
        "INSERT INTO billing_accounts (tenant_id, balance_cents) SELECT id, 500 FROM tenants"
    )
    op.execute("""
        INSERT INTO billing_transactions
            (tenant_id, kind, amount_cents, balance_after_cents, description, provider)
        SELECT id, 'grant', 500, 500, 'Welcome credit', 'system' FROM tenants
    """)


def downgrade() -> None:
    op.drop_table("billing_payments")
    op.drop_table("billing_transactions")
    op.drop_table("billing_accounts")
