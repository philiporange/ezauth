"""Periodic deletion of rows that have outlived their purpose.

Auth attempts, sessions and audit log entries accumulate forever otherwise: the
first two keep spent single-use secrets around long after they can be used, and
the third grows without bound. `run_cleanup` deletes each class of row past the
retention window configured in `ezauth.config` and reports how many went.

`cleanup_loop` runs it every `settings.cleanup_interval_seconds` from the
application lifespan. Several worker processes run the same loop, so each pass
first takes a Redis lock that expires just before the next one is due; whichever
worker gets it does the work and the rest skip the round. A failed pass is
logged and the loop continues, so a cleanup problem can never take the service
down with it.
"""

import asyncio
import secrets
from datetime import datetime, timedelta, timezone

from loguru import logger
from sqlalchemy import delete, or_
from sqlalchemy.ext.asyncio import AsyncSession

from ezauth.config import settings
from ezauth.db.engine import async_session_factory
from ezauth.db.redis import get_redis
from ezauth.models.audit_log import AuditLog
from ezauth.models.auth_attempt import AuthAttempt, AuthAttemptStatus
from ezauth.models.session import Session

LOCK_KEY = "cleanup:lock"


async def run_cleanup(db: AsyncSession) -> dict[str, int]:
    """Delete expired auth attempts, dead sessions and old audit entries."""
    now = datetime.now(timezone.utc)
    attempt_cutoff = now - timedelta(days=settings.auth_attempt_retention_days)
    session_cutoff = now - timedelta(days=settings.expired_session_retention_days)
    audit_cutoff = now - timedelta(days=settings.audit_log_retention_days)

    attempts = await db.execute(
        delete(AuthAttempt).where(
            or_(
                AuthAttempt.expires_at < attempt_cutoff,
                (AuthAttempt.status != AuthAttemptStatus.pending)
                & (AuthAttempt.created_at < attempt_cutoff),
            )
        )
    )
    sessions = await db.execute(
        delete(Session).where(
            or_(
                Session.expires_at < session_cutoff,
                Session.revoked_at < session_cutoff,
            )
        )
    )
    audit = await db.execute(delete(AuditLog).where(AuditLog.created_at < audit_cutoff))
    await db.commit()

    return {
        "auth_attempts": attempts.rowcount or 0,
        "sessions": sessions.rowcount or 0,
        "audit_log": audit.rowcount or 0,
    }


async def _acquire_lock(ttl_seconds: int) -> bool:
    """Take the cleanup lock, so only one worker runs a given pass."""
    try:
        redis = get_redis()
        return bool(
            await redis.set(LOCK_KEY, secrets.token_hex(8), nx=True, ex=max(ttl_seconds, 1))
        )
    except Exception:
        logger.warning("Could not reach Redis for the cleanup lock; skipping this pass")
        return False


async def run_cleanup_pass() -> dict[str, int] | None:
    """One locked cleanup pass. Returns the counts, or None if another worker holds the lock."""
    if not await _acquire_lock(settings.cleanup_interval_seconds - 1):
        return None
    async with async_session_factory() as db:
        deleted = await run_cleanup(db)
    logger.info(
        "Cleanup removed {attempts} auth attempts, {sessions} sessions, {audit} audit entries",
        attempts=deleted["auth_attempts"],
        sessions=deleted["sessions"],
        audit=deleted["audit_log"],
    )
    return deleted


async def cleanup_loop() -> None:
    """Run a cleanup pass forever, one interval apart, surviving any failure."""
    while True:
        await asyncio.sleep(settings.cleanup_interval_seconds)
        try:
            await run_cleanup_pass()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Cleanup pass failed")
