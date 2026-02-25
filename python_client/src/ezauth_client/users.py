from __future__ import annotations

from typing import TYPE_CHECKING

from ._client import _encode

if TYPE_CHECKING:
    from ._client import BaseClient


class Users:
    def __init__(self, client: BaseClient):
        self._client = client

    def list(
        self,
        *,
        limit: int | None = None,
        offset: int | None = None,
        email: str | None = None,
    ) -> dict:
        return self._client._fetch(
            "/v1/users",
            query={"limit": limit, "offset": offset, "email": email},
        )

    def create(self, email: str, *, password: str | None = None) -> dict:
        return self._client._fetch(
            "/v1/users",
            method="POST",
            body={"email": email, "password": password},
        )

    def get(self, user_id: str) -> dict:
        return self._client._fetch(f"/v1/users/{_encode(user_id)}")
