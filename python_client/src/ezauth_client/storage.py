from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ._client import BaseClient


class Storage:
    def __init__(self, client: BaseClient):
        self._client = client

    def tables(self) -> dict:
        return self._client._fetch("/v1/tables/storage", auth="auto")

    def objects(self) -> dict:
        return self._client._fetch("/v1/buckets/storage", auth="auto")
