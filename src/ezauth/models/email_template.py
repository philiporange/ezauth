from sqlalchemy import String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ezauth.db.base import Base, TimestampMixin, UUIDPrimaryKey


class EmailTemplate(Base, UUIDPrimaryKey, TimestampMixin):
    """An instance-wide override for one packaged mail template.

    A row shadows `mail/templates/<name>.<format>`; with no row the packaged
    file is used. `updated_at` doubles as the cache version the mail service
    keys its rendered-template cache on.
    """

    __tablename__ = "email_templates"
    __table_args__ = (UniqueConstraint("name", "format", name="uq_email_template_name_format"),)

    name: Mapped[str] = mapped_column(String(64), nullable=False)
    format: Mapped[str] = mapped_column(String(8), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    def __repr__(self) -> str:
        return f"<EmailTemplate {self.name}.{self.format}>"
