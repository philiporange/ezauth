import uuid

from sqlalchemy import BigInteger, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ezauth.db.base import Base, TimestampMixin, UUIDPrimaryKey


class StorageObject(Base, UUIDPrimaryKey, TimestampMixin):
    __tablename__ = "storage_objects"
    __table_args__ = (
        UniqueConstraint("bucket_id", "user_id", "key", name="uq_storage_object_bucket_user_key"),
        Index("ix_storage_objects_bucket_user", "bucket_id", "user_id"),
    )

    app_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=False
    )
    bucket_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("buckets.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    key: Mapped[str] = mapped_column(String(1024), nullable=False)
    content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)

    bucket: Mapped["Bucket"] = relationship(back_populates="objects")

    def __repr__(self) -> str:
        return f"<StorageObject {self.id} key={self.key!r}>"
