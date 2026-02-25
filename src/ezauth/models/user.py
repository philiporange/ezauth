import uuid
from datetime import datetime

from sqlalchemy import Boolean, Computed, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ezauth.db.base import Base, TimestampMixin, UUIDPrimaryKey


class User(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("app_id", "email_lower", name="uq_user_app_email"),
    )

    app_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    email_lower: Mapped[str | None] = mapped_column(
        String(320), Computed("lower(email)"), nullable=True
    )
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    password_hash: Mapped[str | None] = mapped_column(Text)

    # Bot authentication fields
    is_bot: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    public_key_ed25519: Mapped[str | None] = mapped_column(Text, nullable=True)
    challenge_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, unique=True
    )

    application: Mapped["Application"] = relationship(back_populates="users")  # noqa: F821
    sessions: Mapped[list["Session"]] = relationship(  # noqa: F821
        back_populates="user", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        if self.is_bot:
            return f"<User {self.id} bot key={self.public_key_ed25519[:16]}...>"
        return f"<User {self.id} email={self.email!r}>"
