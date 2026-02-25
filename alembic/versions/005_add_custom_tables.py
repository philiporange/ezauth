"""Add custom tables feature

Revision ID: 005
Revises: 004
Create Date: 2026-02-25
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # custom_tables
    op.create_table(
        "custom_tables",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("app_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["app_id"], ["applications.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("app_id", "name", name="uq_custom_table_app_name"),
    )
    op.create_index("ix_custom_tables_app_id", "custom_tables", ["app_id"])

    # custom_columns
    op.create_table(
        "custom_columns",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("app_id", sa.Uuid(), nullable=False),
        sa.Column("table_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("default_value", postgresql.JSONB(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["app_id"], ["applications.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["table_id"], ["custom_tables.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("table_id", "name", name="uq_custom_column_table_name"),
    )
    op.create_index("ix_custom_columns_table_id", "custom_columns", ["table_id"])

    # custom_rows
    op.create_table(
        "custom_rows",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("app_id", sa.Uuid(), nullable=False),
        sa.Column("table_id", sa.Uuid(), nullable=False),
        sa.Column("data", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["app_id"], ["applications.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["table_id"], ["custom_tables.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_custom_rows_app_table", "custom_rows", ["app_id", "table_id"])


def downgrade() -> None:
    op.drop_table("custom_rows")
    op.drop_table("custom_columns")
    op.drop_table("custom_tables")
