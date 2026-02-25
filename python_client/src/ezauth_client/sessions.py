from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ._client import BaseClient


class Sessions:
    def __init__(self, client: BaseClient):
        self._client = client

    def revoke(self, session_id: str) -> dict:
        return self._client._fetch(
            "/v1/sessions/revoke",
            method="POST",
            query={"session_id": session_id},
        )

    def create_sign_in_token(
        self,
        user_id: str,
        *,
        expires_in_seconds: int | None = None,
    ) -> dict:
        return self._client._fetch(
            "/v1/sign_in_tokens",
            method="POST",
            body={
                "user_id": user_id,
                "expires_in_seconds": expires_in_seconds,
            },
        )
