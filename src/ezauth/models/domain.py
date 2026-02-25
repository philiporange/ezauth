import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from ezauth.db.base import Base, TimestampMixin, UUIDPrimaryKey


class DomainType(str, enum.Enum):
    primary = "primary"
    satellite = "satellite"


class Domain(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "domains"

    app_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    domain: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    type: Mapped[DomainType] = mapped_column(
        Enum(DomainType, name="domain_type_enum"), nullable=False, default=DomainType.primary
    )
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cname_target: Mapped[str | None] = mapped_column(String(255))

    def __repr__(self) -> str:
        return f"<Domain {self.id} domain={self.domain!r} verified={self.verified}>"
