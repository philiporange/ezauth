import uuid

from sqlalchemy import ForeignKey, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ezauth.db.base import Base, TimestampMixin, UUIDPrimaryKey


class CustomRow(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "custom_rows"
    __table_args__ = (
        Index("ix_custom_rows_app_table", "app_id", "table_id"),
        Index("ix_custom_rows_table_user", "table_id", "user_id"),
    )

    app_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=False
    )
    table_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("custom_tables.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    data: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")

    table: Mapped["CustomTable"] = relationship(back_populates="rows")

    def __repr__(self) -> str:
        return f"<CustomRow {self.id} table_id={self.table_id}>"
