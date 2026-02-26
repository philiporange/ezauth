"""Add user-scoped rows and object storage

Revision ID: 006
Revises: 005
Create Date: 2026-02-26
"""

from alembic import op
import sqlalchemy as sa

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add user_id to custom_rows
    op.add_column(
        "custom_rows",
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
    )
    op.create_index("ix_custom_rows_user_id", "custom_rows", ["user_id"])
    op.create_index("ix_custom_rows_table_user", "custom_rows", ["table_id", "user_id"])

    # buckets
    op.create_table(
        "buckets",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("app_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["app_id"], ["applications.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("app_id", "name", name="uq_bucket_app_name"),
    )

    # storage_objects
    op.create_table(
        "storage_objects",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("app_id", sa.Uuid(), nullable=False),
        sa.Column("bucket_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(1024), nullable=False),
        sa.Column("content_type", sa.String(255), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["app_id"], ["applications.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["bucket_id"], ["buckets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("bucket_id", "user_id", "key", name="uq_storage_object_bucket_user_key"),
    )
    op.create_index("ix_storage_objects_bucket_user", "storage_objects", ["bucket_id", "user_id"])


def downgrade() -> None:
    op.drop_table("storage_objects")
    op.drop_table("buckets")
    op.drop_index("ix_custom_rows_table_user", table_name="custom_rows")
    op.drop_index("ix_custom_rows_user_id", table_name="custom_rows")
    op.drop_column("custom_rows", "user_id")
