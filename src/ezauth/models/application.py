import enum
import uuid

from sqlalchemy import Boolean, Enum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ezauth.db.base import Base, TimestampMixin, UUIDPrimaryKey


class Environment(str, enum.Enum):
    dev = "dev"
    prod = "prod"


class Application(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "applications"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", "environment", name="uq_app_tenant_name_env"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    environment: Mapped[Environment] = mapped_column(
        Enum(Environment, name="environment_enum"), nullable=False, default=Environment.dev
    )
    publishable_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    secret_key: Mapped[str] = mapped_column(String(128), nullable=False)
    primary_domain: Mapped[str | None] = mapped_column(String(255))
    allowed_origins: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    email_from_name: Mapped[str | None] = mapped_column(String(255))
    email_from_address: Mapped[str | None] = mapped_column(String(255))
    passwords_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    verification_method: Mapped[str] = mapped_column(String(10), nullable=False, server_default="code")
    settings_json: Mapped[dict | None] = mapped_column(JSONB, default=dict)
    jwk_private_pem: Mapped[str] = mapped_column(Text, nullable=False)
    jwk_kid: Mapped[str] = mapped_column(String(64), nullable=False)
    owner_email: Mapped[str | None] = mapped_column(String(320))

    tenant: Mapped["Tenant"] = relationship(back_populates="applications")  # noqa: F821
    users: Mapped[list["User"]] = relationship(  # noqa: F821
        back_populates="application", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Application {self.id} name={self.name!r} env={self.environment}>"
