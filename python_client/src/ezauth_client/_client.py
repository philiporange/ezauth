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
        access_token: str | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.secret_key = secret_key
        self.publishable_key = publishable_key
        self.access_token = access_token
        self._http = httpx.Client(timeout=30.0)

    def _build_headers(self, auth: str, content_type: str = "application/json") -> dict[str, str]:
        headers: dict[str, str] = {}
        if content_type:
            headers["Content-Type"] = content_type

        if auth == "secret":
            if not self.secret_key:
                raise EZAuthError("secret_key is required for this operation", 0, "missing_key")
            headers["Authorization"] = f"Bearer {self.secret_key}"
        elif auth == "publishable":
            if not self.publishable_key:
                raise EZAuthError("publishable_key is required for this operation", 0, "missing_key")
            headers["X-Publishable-Key"] = self.publishable_key
        elif auth == "auto":
            if self.secret_key:
                headers["Authorization"] = f"Bearer {self.secret_key}"
            elif self.publishable_key:
                headers["X-Publishable-Key"] = self.publishable_key
                if self.access_token:
                    headers["Authorization"] = f"Bearer {self.access_token}"
                else:
                    raise EZAuthError("access_token is required for user operations", 0, "missing_token")
            else:
                raise EZAuthError("secret_key or publishable_key is required", 0, "missing_key")

        return headers

    def _build_url(self, path: str, query: dict | None = None) -> str:
        url = f"{self.base_url}{path}"
        if query:
            params = {k: str(v) for k, v in query.items() if v is not None}
            if params:
                url += "?" + "&".join(f"{k}={v}" for k, v in params.items())
        return url

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
        url = self._build_url(path, query)
        headers = self._build_headers(auth)
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

    def _request(
        self,
        path: str,
        *,
        method: str = "GET",
        content: bytes | None = None,
        content_type: str = "application/octet-stream",
        auth: str = "auto",
        query: dict | None = None,
    ) -> httpx.Response:
        url = self._build_url(path, query)
        headers = self._build_headers(auth, content_type=content_type)

        resp = self._http.request(method, url, headers=headers, content=content)

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

        return resp


def _encode(value: str) -> str:
    return quote(str(value), safe="")
