from ._client import BaseClient, EZAuthError
from .auth import Auth
from .buckets import Buckets
from .sessions import Sessions
from .storage import Storage
from .tables import Tables
from .users import Users


class EZAuth(BaseClient):
    def __init__(
        self,
        base_url: str = "",
        *,
        secret_key: str | None = None,
        publishable_key: str | None = None,
        access_token: str | None = None,
    ):
        super().__init__(base_url, secret_key, publishable_key, access_token)
        self.auth = Auth(self)
        self.users = Users(self)
        self.sessions = Sessions(self)
        self.tables = Tables(self)
        self.buckets = Buckets(self)
        self.storage = Storage(self)


__all__ = ["EZAuth", "EZAuthError"]
