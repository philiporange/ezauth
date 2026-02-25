"""Add bot authentication fields to users

Revision ID: 004
Revises: 003
Create Date: 2026-02-25
"""

from alembic import op
import sqlalchemy as sa

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("is_bot", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("users", sa.Column("public_key_ed25519", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("challenge_id", sa.String(64), nullable=True))
    op.create_unique_constraint("uq_user_challenge_id", "users", ["challenge_id"])
    op.alter_column("users", "email", nullable=True)
    op.alter_column("users", "email_lower", nullable=True)


def downgrade() -> None:
    op.alter_column("users", "email_lower", nullable=False)
    op.alter_column("users", "email", nullable=False)
    op.drop_constraint("uq_user_challenge_id", "users", type_="unique")
    op.drop_column("users", "challenge_id")
    op.drop_column("users", "public_key_ed25519")
    op.drop_column("users", "is_bot")
