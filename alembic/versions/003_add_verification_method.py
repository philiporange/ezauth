"""Add verification_method to applications

Revision ID: 003
Revises: 002
Create Date: 2026-02-21
"""

from alembic import op
import sqlalchemy as sa

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "applications",
        sa.Column("verification_method", sa.String(10), nullable=False, server_default="code"),
    )


def downgrade() -> None:
    op.drop_column("applications", "verification_method")
