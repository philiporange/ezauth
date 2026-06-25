"""Add owner_email to tenants and backfill from applications

Revision ID: 010
Revises: 009
Create Date: 2026-06-11
"""

import sqlalchemy as sa

from alembic import op

revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tenants", sa.Column("owner_email", sa.String(320), nullable=True))
    op.create_index("ix_tenants_owner_email", "tenants", ["owner_email"])
    # Backfill from the applications that already carry an owner_email.
    op.execute(
        """
        UPDATE tenants SET owner_email = (
            SELECT min(lower(applications.owner_email))
            FROM applications
            WHERE applications.tenant_id = tenants.id
              AND applications.owner_email IS NOT NULL
        )
        """
    )


def downgrade() -> None:
    op.drop_index("ix_tenants_owner_email", table_name="tenants")
    op.drop_column("tenants", "owner_email")
