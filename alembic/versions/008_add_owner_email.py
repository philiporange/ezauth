"""Add owner_email to applications and admin_login auth attempt type

Revision ID: 008
Revises: 007
Create Date: 2026-02-26
"""

from alembic import op
import sqlalchemy as sa

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("applications", sa.Column("owner_email", sa.String(320), nullable=True))
    op.execute("ALTER TYPE auth_attempt_type_enum ADD VALUE IF NOT EXISTS 'admin_login'")


def downgrade() -> None:
    op.drop_column("applications", "owner_email")
