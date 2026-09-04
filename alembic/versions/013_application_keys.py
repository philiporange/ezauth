"""Track application signing keys in their own table.

Applications previously carried a single signing key inline, which left no way
to rotate without invalidating every token signed by the old key at the moment
of the change. Keys move to `application_keys`, where one row is active and
retired rows keep verifying until they are dropped.

Revision ID: 013
Revises: 012
"""

import sqlalchemy as sa

from alembic import op

revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "application_keys",
        sa.Column(
            "id",
            sa.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "app_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("applications.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kid", sa.String(64), nullable=False),
        sa.Column("private_pem", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_application_keys_app_id", "application_keys", ["app_id"])
    op.create_index("ix_application_keys_kid", "application_keys", ["kid"], unique=True)

    op.execute(
        """
        INSERT INTO application_keys (id, app_id, kid, private_pem, is_active, created_at)
        SELECT gen_random_uuid(), id, jwk_kid, jwk_private_pem, true, now()
        FROM applications
        """
    )


def downgrade() -> None:
    op.drop_index("ix_application_keys_kid", table_name="application_keys")
    op.drop_index("ix_application_keys_app_id", table_name="application_keys")
    op.drop_table("application_keys")
