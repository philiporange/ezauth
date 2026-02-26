from __future__ import annotations

from typing import TYPE_CHECKING

from ._client import _encode

if TYPE_CHECKING:
    from ._client import BaseClient


class Rows:
    def __init__(self, client: BaseClient):
        self._client = client

    def insert(self, table_id: str, data: dict, *, user_id: str | None = None) -> dict:
        body: dict = {"data": data}
        if user_id is not None:
            body["user_id"] = user_id
        return self._client._fetch(
            f"/v1/tables/{_encode(table_id)}/rows",
            method="POST",
            body=body,
            auth="auto",
        )

    def get(self, table_id: str, row_id: str) -> dict:
        return self._client._fetch(
            f"/v1/tables/{_encode(table_id)}/rows/{_encode(row_id)}",
            auth="auto",
        )

    def update(self, table_id: str, row_id: str, data: dict) -> dict:
        return self._client._fetch(
            f"/v1/tables/{_encode(table_id)}/rows/{_encode(row_id)}",
            method="PATCH",
            body={"data": data},
            auth="auto",
        )

    def delete(self, table_id: str, row_id: str) -> None:
        self._client._fetch(
            f"/v1/tables/{_encode(table_id)}/rows/{_encode(row_id)}",
            method="DELETE",
            auth="auto",
        )

    def query(
        self,
        table_id: str,
        *,
        filter: dict | None = None,
        sort: dict | list | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> dict:
        body: dict = {}
        if filter is not None:
            body["filter"] = filter
        if sort is not None:
            body["sort"] = sort
        if limit is not None:
            body["limit"] = limit
        if cursor is not None:
            body["cursor"] = cursor
        return self._client._fetch(
            f"/v1/tables/{_encode(table_id)}/rows/query",
            method="POST",
            body=body,
            auth="auto",
        )
