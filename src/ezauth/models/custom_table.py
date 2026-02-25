import uuid

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ezauth.db.base import Base, TimestampMixin, UUIDPrimaryKey


class CustomTable(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "custom_tables"
    __table_args__ = (
        UniqueConstraint("app_id", "name", name="uq_custom_table_app_name"),
    )

    app_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    columns: Mapped[list["CustomColumn"]] = relationship(
        back_populates="table", cascade="all, delete-orphan",
        order_by="CustomColumn.position",
    )
    rows: Mapped[list["CustomRow"]] = relationship(
        back_populates="table", cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<CustomTable {self.id} name={self.name!r}>"
