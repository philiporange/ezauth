"""Drop the redundant non-unique index on applications.publishable_key.

The column already carries a unique constraint, which Postgres backs with its
own index, so the separate `ix_applications_publishable_key` index duplicated
that structure and the write cost of maintaining it. Removing it also settles
the only remaining disagreement between the migrations and the model metadata.

Revision ID: 014
Revises: 013
"""

from alembic import op

revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ix_applications_publishable_key", table_name="applications")


def downgrade() -> None:
    op.create_index(
        "ix_applications_publishable_key", "applications", ["publishable_key"]
    )
