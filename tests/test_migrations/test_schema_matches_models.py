"""Guards that the migration chain and the ORM metadata describe one schema.

The test suite builds its schema with `create_all`, so a migration that drifts
from the models is invisible to every other test and only surfaces in
production, where the migrations are the schema. This applies the chain to a
throwaway database and asks alembic whether any further operation would be
needed to reach the model metadata.
"""

import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from ezauth.config import settings


async def _database_available() -> bool:
    engine = create_async_engine(settings.database_url.rsplit("/", 1)[0] + "/postgres")
    try:
        async with engine.connect() as conn:
            await conn.execute(text("select 1"))
        return True
    except Exception:
        return False
    finally:
        await engine.dispose()


@pytest.fixture
async def scratch_database():
    if not await _database_available():
        pytest.skip("PostgreSQL is not reachable")

    name = f"ezauth_mig_{uuid.uuid4().hex[:12]}"
    admin_url = settings.database_url.rsplit("/", 1)[0] + "/postgres"
    engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")

    async with engine.connect() as conn:
        await conn.execute(text(f'CREATE DATABASE "{name}"'))
    await engine.dispose()

    yield settings.database_url.rsplit("/", 1)[0] + f"/{name}"

    engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    async with engine.connect() as conn:
        await conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    await engine.dispose()


def _run_alembic(database_url: str, *args: str) -> None:
    """Run an alembic command in a subprocess pointed at a scratch database."""
    import subprocess

    env = {**os.environ, "DATABASE_URL": database_url, "PYTHONPATH": "src"}
    result = subprocess.run(
        ["python", "-m", "alembic", *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=os.getcwd(),
    )
    if result.returncode != 0:
        raise AssertionError(
            f"alembic {' '.join(args)} failed:\n{result.stdout}\n{result.stderr}"
        )


def test_migrations_reach_the_model_schema(scratch_database):
    _run_alembic(scratch_database, "upgrade", "head")
    _run_alembic(scratch_database, "check")


def test_migrations_are_reversible(scratch_database):
    _run_alembic(scratch_database, "upgrade", "head")
    _run_alembic(scratch_database, "downgrade", "base")
    _run_alembic(scratch_database, "upgrade", "head")
