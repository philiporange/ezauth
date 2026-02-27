"""Add bucket size limits

Revision ID: 009
Revises: 008
Create Date: 2026-02-27
"""

from alembic import op
import sqlalchemy as sa

revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("buckets", sa.Column("max_size_bytes", sa.BigInteger(), nullable=True))
    op.add_column("buckets", sa.Column("max_size_bytes_per_user", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("buckets", "max_size_bytes_per_user")
    op.drop_column("buckets", "max_size_bytes")
