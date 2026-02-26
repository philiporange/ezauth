import uuid

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ezauth.db.base import Base, TimestampMixin, UUIDPrimaryKey


class OAuthIdentity(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "oauth_identities"
    __table_args__ = (
        UniqueConstraint(
            "app_id", "provider", "provider_user_id",
            name="uq_oauth_identity_app_provider_sub",
        ),
    )

    app_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    provider_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
