import asyncio
import uuid
from typing import Any

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from ezauth.models.audit_log import AuditLog


async def log_event(
    db: AsyncSession,
    *,
    app_id: uuid.UUID,
    event_type: str,
    user_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Write an audit log entry. Designed to be called via fire-and-forget."""
    try:
        entry = AuditLog(
            app_id=app_id,
            event_type=event_type,
            user_id=user_id,
            session_id=session_id,
            ip_address=ip_address,
            user_agent=user_agent,
            metadata_json=metadata or {},
        )
        db.add(entry)
        await db.flush()
    except Exception:
        logger.exception(f"Failed to write audit log: {event_type}")


def fire_and_forget_audit(
    db: AsyncSession,
    **kwargs,
) -> None:
    """Schedule an audit log write as a background task."""
    asyncio.create_task(log_event(db, **kwargs))
