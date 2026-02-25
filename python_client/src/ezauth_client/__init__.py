from ._client import BaseClient, EZAuthError
from .auth import Auth
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
    ):
        super().__init__(base_url, secret_key, publishable_key)
        self.auth = Auth(self)
        self.users = Users(self)
        self.sessions = Sessions(self)
        self.tables = Tables(self)
        self.storage = Storage(self)


__all__ = ["EZAuth", "EZAuthError"]
