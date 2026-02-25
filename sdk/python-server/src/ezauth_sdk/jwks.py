import time
from typing import Any

import httpx


class JWKSClient:
    """Fetches and caches JWKS from a EZAuth auth domain."""

    def __init__(self, auth_domain: str, cache_ttl: int = 3600):
        self.jwks_url = f"https://{auth_domain}/.well-known/jwks.json"
        self.cache_ttl = cache_ttl
        self._cache: dict[str, Any] | None = None
        self._cache_time: float = 0
        self._client = httpx.AsyncClient()

    async def get_signing_key(self, kid: str) -> dict:
        """Get the JWK for a given key ID, refreshing cache if needed."""
        jwks = await self._get_jwks()

        for key in jwks.get("keys", []):
            if key.get("kid") == kid:
                return key

        # Kid not found — force refresh
        self._cache = None
        jwks = await self._get_jwks()
        for key in jwks.get("keys", []):
            if key.get("kid") == kid:
                return key

        raise ValueError(f"Key with kid={kid!r} not found in JWKS")

    async def _get_jwks(self) -> dict:
        now = time.time()
        if self._cache and (now - self._cache_time) < self.cache_ttl:
            return self._cache

        response = await self._client.get(self.jwks_url)
        response.raise_for_status()
        self._cache = response.json()
        self._cache_time = now
        return self._cache

    async def close(self):
        await self._client.aclose()
