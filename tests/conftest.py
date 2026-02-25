import asyncio
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ezauth.config import settings
from ezauth.db.base import Base
from ezauth.models import Application, Tenant, User  # noqa: F401 — register models
from ezauth.services.keys import generate_jwk_pair, generate_publishable_key, generate_secret_key

# Use a separate test database
TEST_DATABASE_URL = settings.database_url.replace("/ezauth", "/ezauth_test")


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def test_engine():
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def db(test_engine):
    session_factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        async with session.begin():
            yield session
        await session.rollback()


@pytest_asyncio.fixture
async def redis():
    import fakeredis.aioredis

    fake_redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield fake_redis
    await fake_redis.aclose()


@pytest_asyncio.fixture
async def tenant(db: AsyncSession):
    t = Tenant(name="Test Tenant")
    db.add(t)
    await db.flush()
    return t


@pytest_asyncio.fixture
async def app(db: AsyncSession, tenant: Tenant):
    from ezauth.models.application import Environment

    private_pem, kid, _jwk_pub = generate_jwk_pair()
    a = Application(
        tenant_id=tenant.id,
        name="Test App",
        environment=Environment.dev,
        publishable_key=generate_publishable_key("dev"),
        secret_key=generate_secret_key("dev"),
        primary_domain="localhost",
        jwk_private_pem=private_pem,
        jwk_kid=kid,
    )
    db.add(a)
    await db.flush()
    return a


@pytest_asyncio.fixture
async def user(db: AsyncSession, app: Application):
    from ezauth.services.passwords import hash_password

    u = User(
        app_id=app.id,
        email="test@example.com",
        password_hash=hash_password("testpassword123"),
        email_verified_at=datetime.now(timezone.utc),
    )
    db.add(u)
    await db.flush()
    return u


@pytest_asyncio.fixture
async def client(app):
    """AsyncClient for API testing — requires live DB+Redis, not for unit tests."""
    from ezauth.main import create_app

    fastapi_app = create_app()
    transport = ASGITransport(app=fastapi_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
