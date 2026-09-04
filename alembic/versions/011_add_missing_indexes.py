"""Add missing indexes on foreign keys

Adds the index the OAuthIdentity model declares on ``app_id`` but which the
oauth_identities migration never created, so that a database built by
``alembic upgrade head`` matches one built by ``Base.metadata.create_all``.
Also indexes the foreign keys that carry no index of their own and are used
for lookups and ``ON DELETE`` cascades: the owning application and user of a
storage object, the owning application of a custom column, and the user and
session referenced by an audit log row.

Foreign keys that are already the leading column of a composite or unique
index are left alone: ``storage_objects.bucket_id`` leads
``ix_storage_objects_bucket_user`` and ``buckets.app_id`` leads the unique
index behind ``uq_bucket_app_name``.

Revision ID: 011
Revises: 010
Create Date: 2026-09-04
"""

from alembic import op

revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None

INDEXES = [
    ("ix_oauth_identities_app_id", "oauth_identities", ["app_id"]),
    ("ix_storage_objects_app_id", "storage_objects", ["app_id"]),
    ("ix_storage_objects_user_id", "storage_objects", ["user_id"]),
    ("ix_custom_columns_app_id", "custom_columns", ["app_id"]),
    ("ix_audit_log_user_id", "audit_log", ["user_id"]),
    ("ix_audit_log_session_id", "audit_log", ["session_id"]),
]


def upgrade() -> None:
    for name, table, columns in INDEXES:
        op.create_index(name, table, columns)


def downgrade() -> None:
    for name, table, _columns in reversed(INDEXES):
        op.drop_index(name, table_name=table)
