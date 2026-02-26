import uuid

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ezauth.db.base import Base, TimestampMixin, UUIDPrimaryKey


class Bucket(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "buckets"
    __table_args__ = (
        UniqueConstraint("app_id", "name", name="uq_bucket_app_name"),
    )

    app_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    objects: Mapped[list["StorageObject"]] = relationship(
        back_populates="bucket", cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Bucket {self.id} name={self.name!r}>"
