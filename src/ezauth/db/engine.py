from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ezauth.config import settings

engine = create_async_engine(settings.database_url, echo=False, pool_size=20, max_overflow=10)

async_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
