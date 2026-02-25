from __future__ import annotations

from urllib.parse import quote

import httpx


class EZAuthError(Exception):
    def __init__(self, message: str, status: int = 0, code: str | None = None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code


class BaseClient:
    def __init__(
        self,
        base_url: str = "",
        secret_key: str | None = None,
        publishable_key: str | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.secret_key = secret_key
        self.publishable_key = publishable_key
        self._http = httpx.Client(timeout=30.0)

    def _fetch(
        self,
        path: str,
        *,
        method: str = "GET",
        body: dict | None = None,
        auth: str = "secret",
        query: dict | None = None,
        headers_extra: dict[str, str] | None = None,
    ) -> dict | None:
        url = f"{self.base_url}{path}"

        if query:
            params = {k: str(v) for k, v in query.items() if v is not None}
            if params:
                url += "?" + "&".join(f"{k}={v}" for k, v in params.items())

        headers: dict[str, str] = {"Content-Type": "application/json"}

        if auth == "secret":
            if not self.secret_key:
                raise EZAuthError("secret_key is required for this operation", 0, "missing_key")
            headers["Authorization"] = f"Bearer {self.secret_key}"
        elif auth == "publishable":
            if not self.publishable_key:
                raise EZAuthError("publishable_key is required for this operation", 0, "missing_key")
            headers["X-Publishable-Key"] = self.publishable_key
        if headers_extra:
            headers.update(headers_extra)

        resp = self._http.request(method, url, headers=headers, json=body if body is not None else None)

        if resp.status_code == 204:
            return None

        if resp.status_code >= 400:
            try:
                data = resp.json()
            except Exception:
                data = {}
            raise EZAuthError(
                data.get("detail", f"Request failed: {resp.status_code}"),
                resp.status_code,
                data.get("code"),
            )

        return resp.json()


def _encode(value: str) -> str:
    return quote(str(value), safe="")
