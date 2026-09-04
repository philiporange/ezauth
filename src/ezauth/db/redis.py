"""Redis client lifecycle.

One asyncio Redis client is built from `settings.redis_url` at startup and
shared by every request through `get_redis`. `init_redis` pings the server
before publishing the client, so an unreachable or misconfigured Redis stops
the process from starting instead of surfacing as a failure on the first rate
limit check. `redis_healthy` gives the health endpoint a cheap liveness probe
that never raises.
"""

import redis.asyncio as aioredis

from ezauth.config import settings

redis_pool: aioredis.Redis | None = None


async def init_redis() -> aioredis.Redis:
    """Connect to Redis and verify the connection with a PING."""
    global redis_pool
    client = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        await client.ping()
    except Exception:
        await client.aclose()
        raise
    redis_pool = client
    return redis_pool


async def close_redis() -> None:
    global redis_pool
    if redis_pool:
        await redis_pool.aclose()
        redis_pool = None


def get_redis() -> aioredis.Redis:
    if redis_pool is None:
        raise RuntimeError("Redis is not initialised")
    return redis_pool


async def redis_healthy() -> bool:
    """True when the shared client exists and answers a PING."""
    if redis_pool is None:
        return False
    try:
        await redis_pool.ping()
    except Exception:
        return False
    return True
