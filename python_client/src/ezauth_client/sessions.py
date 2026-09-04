"""Backend session operations, authenticated with an application secret key.

Optional request fields are left out of the JSON body rather than sent as
null, because the server schema types them as integers with defaults and
rejects an explicit null.
"""

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
        body: dict = {"user_id": user_id}
        if expires_in_seconds is not None:
            body["expires_in_seconds"] = expires_in_seconds
        return self._client._fetch("/v1/sign_in_tokens", method="POST", body=body)
