from datetime import datetime, timezone

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from ezauth.config import settings
from ezauth.db.base import Base
from ezauth.models import Application, Tenant, User  # noqa: F401 — register models
from ezauth.services.keys import generate_jwk_pair, generate_publishable_key, generate_secret_key

# Use a separate test database
TEST_DATABASE_URL = settings.database_url.replace("/ezauth", "/ezauth_test")


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
    """A session whose writes are always rolled back.

    The session is bound to an outer transaction on a dedicated connection and
    joins it as a savepoint, so a commit inside the code under test releases a
    savepoint rather than persisting anything. Rolling the outer transaction
    back at teardown leaves the database exactly as the test found it, which is
    what keeps tests independent of the order they run in.
    """
    async with test_engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        try:
            yield session
        finally:
            await session.close()
            if transaction.is_active:
                await transaction.rollback()


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
async def client(db, redis, app):
    """AsyncClient wired to the test database and a fake Redis.

    The database session and Redis dependencies are overridden rather than
    connecting to live infrastructure, and the lifespan is not run, so route
    behaviour can be exercised end to end without external services.
    """
    from ezauth.dependencies import get_db, get_redis_dep
    from ezauth.main import create_app

    fastapi_app = create_app()
    fastapi_app.state.s3 = None

    async def _override_db():
        yield db

    async def _override_redis():
        return redis

    fastapi_app.dependency_overrides[get_db] = _override_db
    fastapi_app.dependency_overrides[get_redis_dep] = _override_redis

    transport = ASGITransport(app=fastapi_app)
    async with AsyncClient(
        transport=transport,
        base_url="https://localhost",
        headers={"X-Publishable-Key": app.publishable_key},
    ) as c:
        yield c
    fastapi_app.dependency_overrides.clear()


@pytest_asyncio.fixture(autouse=True)
def no_outbound_mail(monkeypatch):
    """Keep tests from reaching SES; record what would have been sent."""
    sent = []

    async def _capture(self, template, to, subject, context):
        sent.append(
            {"template": template, "to": to, "subject": subject, "context": context}
        )

    monkeypatch.setattr("ezauth.services.mail.MailService.send_template", _capture)
    return sent


@pytest_asyncio.fixture
def sent_mail(no_outbound_mail):
    return no_outbound_mail
