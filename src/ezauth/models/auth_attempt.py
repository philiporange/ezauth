import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ezauth.db.base import Base, UUIDPrimaryKey


class AuthAttemptType(str, enum.Enum):
    signup = "signup"
    signin = "signin"
    verify_email = "verify_email"


class AuthAttemptStatus(str, enum.Enum):
    pending = "pending"
    consumed = "consumed"
    expired = "expired"
    revoked = "revoked"


class AuthAttempt(Base, UUIDPrimaryKey):
    __tablename__ = "auth_attempts"
    __table_args__ = (
        Index(
            "ix_auth_attempts_pending_expires",
            "token_hash",
            "status",
            "expires_at",
            postgresql_where="status = 'pending'",
        ),
    )

    app_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type: Mapped[AuthAttemptType] = mapped_column(
        Enum(AuthAttemptType, name="auth_attempt_type_enum"), nullable=False
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[AuthAttemptStatus] = mapped_column(
        Enum(AuthAttemptStatus, name="auth_attempt_status_enum"),
        nullable=False,
        default=AuthAttemptStatus.pending,
    )
    redirect_url: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metadata_json: Mapped[dict | None] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default="now()",
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<AuthAttempt {self.id} type={self.type} status={self.status}>"
