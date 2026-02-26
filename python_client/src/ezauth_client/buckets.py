from __future__ import annotations

from typing import TYPE_CHECKING

from ._client import _encode

if TYPE_CHECKING:
    from ._client import BaseClient


class Objects:
    def __init__(self, client: BaseClient):
        self._client = client

    def put(
        self,
        bucket_id: str,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
        *,
        user_id: str | None = None,
    ) -> dict:
        query = {}
        if user_id is not None:
            query["user_id"] = user_id
        resp = self._client._request(
            f"/v1/buckets/{_encode(bucket_id)}/objects/{key}",
            method="PUT",
            content=data,
            content_type=content_type,
            query=query or None,
        )
        return resp.json()

    def get(
        self,
        bucket_id: str,
        key: str,
        *,
        user_id: str | None = None,
    ) -> tuple[bytes, str]:
        """Download an object. Returns (data, content_type)."""
        query = {}
        if user_id is not None:
            query["user_id"] = user_id
        resp = self._client._request(
            f"/v1/buckets/{_encode(bucket_id)}/objects/{key}",
            method="GET",
            content_type="",
            query=query or None,
        )
        return resp.content, resp.headers.get("content-type", "application/octet-stream")

    def delete(
        self,
        bucket_id: str,
        key: str,
        *,
        user_id: str | None = None,
    ) -> None:
        query = {}
        if user_id is not None:
            query["user_id"] = user_id
        self._client._request(
            f"/v1/buckets/{_encode(bucket_id)}/objects/{key}",
            method="DELETE",
            content_type="",
            query=query or None,
        )

    def list(
        self,
        bucket_id: str,
        *,
        user_id: str | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> dict:
        query = {}
        if user_id is not None:
            query["user_id"] = user_id
        if limit is not None:
            query["limit"] = limit
        if cursor is not None:
            query["cursor"] = cursor
        return self._client._fetch(
            f"/v1/buckets/{_encode(bucket_id)}/objects",
            auth="auto",
            query=query or None,
        )


class Buckets:
    def __init__(self, client: BaseClient):
        self._client = client
        self.objects = Objects(client)

    def create(self, name: str) -> dict:
        return self._client._fetch(
            "/v1/buckets",
            method="POST",
            body={"name": name},
            auth="auto",
        )

    def list(self) -> dict:
        return self._client._fetch("/v1/buckets", auth="auto")

    def get(self, bucket_id: str) -> dict:
        return self._client._fetch(f"/v1/buckets/{_encode(bucket_id)}", auth="auto")

    def delete(self, bucket_id: str) -> None:
        self._client._fetch(f"/v1/buckets/{_encode(bucket_id)}", method="DELETE", auth="auto")
