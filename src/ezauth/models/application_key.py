import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ezauth.db.base import Base, UUIDPrimaryKey


class ApplicationKey(Base, UUIDPrimaryKey):
    """One RSA signing key belonging to an application.

    An application has exactly one active key, which signs new tokens, and any
    number of retired keys, which are still published in JWKS so that tokens
    signed before a rotation keep verifying until they expire.
    """

    __tablename__ = "application_keys"

    app_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kid: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    private_pem: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()", nullable=False
    )
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    def __repr__(self) -> str:
        return f"<ApplicationKey {self.kid} app_id={self.app_id} active={self.is_active}>"
