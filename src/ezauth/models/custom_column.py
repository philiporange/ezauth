import enum
import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ezauth.db.base import Base, TimestampMixin, UUIDPrimaryKey


class ColumnType(str, enum.Enum):
    text = "text"
    int = "int"
    float = "float"
    bool = "bool"
    timestamptz = "timestamptz"
    json = "json"


class CustomColumn(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "custom_columns"
    __table_args__ = (
        UniqueConstraint("table_id", "name", name="uq_custom_column_table_name"),
    )

    app_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=False
    )
    table_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("custom_tables.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    default_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    table: Mapped["CustomTable"] = relationship(back_populates="columns")

    def __repr__(self) -> str:
        return f"<CustomColumn {self.id} name={self.name!r} type={self.type!r}>"
