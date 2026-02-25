import uuid

from sqlalchemy import ForeignKey, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ezauth.db.base import Base, TimestampMixin, UUIDPrimaryKey


class CustomRow(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "custom_rows"
    __table_args__ = (
        Index("ix_custom_rows_app_table", "app_id", "table_id"),
    )

    app_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=False
    )
    table_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("custom_tables.id", ondelete="CASCADE"), nullable=False
    )
    data: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")

    table: Mapped["CustomTable"] = relationship(back_populates="rows")

    def __repr__(self) -> str:
        return f"<CustomRow {self.id} table_id={self.table_id}>"
