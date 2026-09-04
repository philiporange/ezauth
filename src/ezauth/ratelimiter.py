"""Fixed-window rate limiting backed by Redis.

Counters live in Redis rather than process memory so a limit is shared by every
worker and every host behind the load balancer; a per-process counter would let
an attacker multiply their allowance by the number of workers. Each configured
window is an INCR against a key that expires when the window does.

Limits are configured as "window_seconds:max_count" strings and parsed by
`parse_limits`. A caller identifies the subject (an IP address, an email
address) and an optional namespace, usually the application id, so that one
application's traffic cannot exhaust another's budget.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import redis.asyncio as aioredis


def parse_limits(config_str: str) -> list[tuple[int, int]]:
    """Parse a "window_seconds:max_count" setting into limiter windows."""
    try:
        window, count = config_str.split(":")
        return [(int(window), int(count))]
    except (ValueError, TypeError) as e:
        raise ValueError(
            f"Invalid rate limit format {config_str!r}, expected 'window:count'"
        ) from e


class RateLimiter:
    DB_PREFIX = "rl"

    def __init__(
        self,
        redis_conn: "aioredis.Redis",
        limits: list[tuple[int, int]],
        user_id: str = "global",
        namespace: str = "",
    ):
        self.redis = redis_conn
        self.limits = limits
        self.user_id = user_id
        self.namespace = namespace

    def _get_key(self, window_size: int) -> str:
        parts = [self.DB_PREFIX]
        if self.namespace:
            parts.append(self.namespace)
        parts.extend([self.user_id, str(window_size)])
        return ":".join(parts)

    async def check_and_consume(self) -> bool:
        pipe = self.redis.pipeline()

        for window_size, _limit in self.limits:
            key = self._get_key(window_size)
            pipe.incr(key)
            pipe.expire(key, window_size, nx=True)

        results = await pipe.execute()

        for i, (_window_size, limit) in enumerate(self.limits):
            if results[i * 2] > limit:
                return False

        return True

    async def get_remaining(self) -> list[int]:
        pipe = self.redis.pipeline()

        for window_size, _limit in self.limits:
            key = self._get_key(window_size)
            pipe.get(key)

        results = await pipe.execute()

        remaining = []
        for i, (_window_size, limit) in enumerate(self.limits):
            count = int(results[i] or 0)
            remaining.append(max(0, limit - count))

        return remaining
