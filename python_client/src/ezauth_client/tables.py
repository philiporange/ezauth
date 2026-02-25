from __future__ import annotations

from typing import TYPE_CHECKING

from ._client import _encode
from .rows import Rows

if TYPE_CHECKING:
    from ._client import BaseClient


class Columns:
    def __init__(self, client: BaseClient):
        self._client = client

    def add(
        self,
        table_id: str,
        name: str,
        type: str,
        *,
        required: bool = False,
        default_value: str | None = None,
        position: int | None = None,
    ) -> dict:
        return self._client._fetch(
            f"/v1/tables/{_encode(table_id)}/columns",
            method="POST",
            body={
                "name": name,
                "type": type,
                "required": required,
                "default_value": default_value,
                "position": position,
            },
        )

    def update(
        self,
        table_id: str,
        column_id: str,
        *,
        name: str | None = None,
        required: bool | None = None,
        default_value: str | None = ...,
        position: int | None = None,
    ) -> dict:
        body: dict = {}
        if name is not None:
            body["name"] = name
        if required is not None:
            body["required"] = required
        if default_value is not ...:
            body["default_value"] = default_value
        if position is not None:
            body["position"] = position
        return self._client._fetch(
            f"/v1/tables/{_encode(table_id)}/columns/{_encode(column_id)}",
            method="PATCH",
            body=body,
        )

    def delete(self, table_id: str, column_id: str) -> None:
        self._client._fetch(
            f"/v1/tables/{_encode(table_id)}/columns/{_encode(column_id)}",
            method="DELETE",
        )


class Tables:
    def __init__(self, client: BaseClient):
        self._client = client
        self.columns = Columns(client)
        self.rows = Rows(client)

    def create(self, name: str, *, columns: list[dict] | None = None) -> dict:
        body: dict = {"name": name}
        if columns is not None:
            body["columns"] = columns
        return self._client._fetch("/v1/tables", method="POST", body=body)

    def list(self) -> dict:
        return self._client._fetch("/v1/tables")

    def get(self, table_id: str) -> dict:
        return self._client._fetch(f"/v1/tables/{_encode(table_id)}")

    def delete(self, table_id: str) -> None:
        self._client._fetch(f"/v1/tables/{_encode(table_id)}", method="DELETE")
