"""Initial schema

Revision ID: 001
Revises:
Create Date: 2026-02-20
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enums
    environment_enum = postgresql.ENUM("dev", "prod", name="environment_enum", create_type=False)
    environment_enum.create(op.get_bind(), checkfirst=True)

    auth_attempt_type_enum = postgresql.ENUM(
        "signup", "signin", "verify_email", name="auth_attempt_type_enum", create_type=False
    )
    auth_attempt_type_enum.create(op.get_bind(), checkfirst=True)

    auth_attempt_status_enum = postgresql.ENUM(
        "pending", "consumed", "expired", "revoked",
        name="auth_attempt_status_enum", create_type=False,
    )
    auth_attempt_status_enum.create(op.get_bind(), checkfirst=True)

    domain_type_enum = postgresql.ENUM(
        "primary", "satellite", name="domain_type_enum", create_type=False
    )
    domain_type_enum.create(op.get_bind(), checkfirst=True)

    # tenants
    op.create_table(
        "tenants",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    # applications
    op.create_table(
        "applications",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("environment", environment_enum, nullable=False),
        sa.Column("publishable_key", sa.String(64), nullable=False),
        sa.Column("secret_key", sa.String(128), nullable=False),
        sa.Column("primary_domain", sa.String(255), nullable=True),
        sa.Column("allowed_origins", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("email_from_name", sa.String(255), nullable=True),
        sa.Column("email_from_address", sa.String(255), nullable=True),
        sa.Column("settings_json", postgresql.JSONB(), nullable=True),
        sa.Column("jwk_private_pem", sa.Text(), nullable=False),
        sa.Column("jwk_kid", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("tenant_id", "name", "environment", name="uq_app_tenant_name_env"),
        sa.UniqueConstraint("publishable_key"),
    )
    op.create_index("ix_applications_tenant_id", "applications", ["tenant_id"])
    op.create_index("ix_applications_publishable_key", "applications", ["publishable_key"])

    # users
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("app_id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("email_lower", sa.String(320), sa.Computed("lower(email)"), nullable=False),
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("password_hash", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["app_id"], ["applications.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("app_id", "email_lower", name="uq_user_app_email"),
    )
    op.create_index("ix_users_app_id", "users", ["app_id"])

    # auth_attempts
    op.create_table(
        "auth_attempts",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("app_id", sa.Uuid(), nullable=False),
        sa.Column("type", auth_attempt_type_enum, nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("status", auth_attempt_status_enum, nullable=False),
        sa.Column("redirect_url", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["app_id"], ["applications.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_auth_attempts_app_id", "auth_attempts", ["app_id"])
    op.create_index("ix_auth_attempts_token_hash", "auth_attempts", ["token_hash"])
    op.create_index(
        "ix_auth_attempts_pending_expires",
        "auth_attempts",
        ["token_hash", "status", "expires_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )

    # sessions
    op.create_table(
        "sessions",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("app_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("refresh_token_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("session_version", sa.Integer(), nullable=False, server_default="1"),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["app_id"], ["applications.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_sessions_app_id", "sessions", ["app_id"])
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])
    op.create_index("ix_sessions_refresh_token_hash", "sessions", ["refresh_token_hash"])

    # domains
    op.create_table(
        "domains",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("app_id", sa.Uuid(), nullable=False),
        sa.Column("domain", sa.String(255), nullable=False),
        sa.Column("type", domain_type_enum, nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cname_target", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["app_id"], ["applications.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("domain"),
    )
    op.create_index("ix_domains_app_id", "domains", ["app_id"])

    # audit_log
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("app_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("session_id", sa.Uuid(), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["app_id"], ["applications.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_audit_log_app_event_created",
        "audit_log",
        ["app_id", "event_type", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("audit_log")
    op.drop_table("domains")
    op.drop_table("sessions")
    op.drop_table("auth_attempts")
    op.drop_table("users")
    op.drop_table("applications")
    op.drop_table("tenants")
    op.execute("DROP TYPE IF EXISTS domain_type_enum")
    op.execute("DROP TYPE IF EXISTS auth_attempt_status_enum")
    op.execute("DROP TYPE IF EXISTS auth_attempt_type_enum")
    op.execute("DROP TYPE IF EXISTS environment_enum")
