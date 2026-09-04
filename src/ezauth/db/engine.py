"""Async SQLAlchemy engine and session factory.

The pool is sized from `ezauth.config` and configured to survive a database
restart: `pool_pre_ping` validates a connection before it is handed to a
request, and `pool_recycle` retires connections before Postgres or an
intervening proxy drops them for being idle.
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ezauth.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_pre_ping=True,
    pool_recycle=settings.db_pool_recycle_seconds,
)

async_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def database_healthy() -> bool:
    """True when a pooled connection can execute a trivial statement."""
    try:
        async with async_session_factory() as session:
            await session.execute(text("SELECT 1"))
    except Exception:
        return False
    return True
