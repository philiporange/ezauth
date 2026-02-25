from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ._client import BaseClient


class Auth:
    def __init__(self, client: BaseClient):
        self._client = client

    def sign_up(
        self,
        email: str,
        *,
        password: str | None = None,
        redirect_url: str | None = None,
        hashcash: dict | None = None,
    ) -> dict:
        body: dict = {"email": email, "password": password, "redirect_url": redirect_url}
        if hashcash is not None:
            body["hashcash"] = hashcash
        return self._client._fetch("/v1/signups", method="POST", auth="publishable", body=body)

    def sign_in(
        self,
        email: str,
        *,
        password: str | None = None,
        strategy: str | None = None,
        redirect_url: str | None = None,
    ) -> dict:
        return self._client._fetch(
            "/v1/signins",
            method="POST",
            auth="publishable",
            body={
                "email": email,
                "password": password,
                "strategy": strategy or ("password" if password else "magic_link"),
                "redirect_url": redirect_url,
            },
        )

    def sign_out(self, *, access_token: str | None = None) -> dict:
        return self._client._fetch(
            "/v1/sessions/logout",
            method="POST",
            auth="publishable",
            headers_extra={"Authorization": f"Bearer {access_token}"} if access_token else None,
        )

    def verify_code(self, email: str, code: str) -> dict:
        return self._client._fetch(
            "/v1/verify-code",
            method="POST",
            auth="publishable",
            body={"email": email, "code": code},
        )

    def get_session(self, *, access_token: str | None = None) -> dict:
        return self._client._fetch(
            "/v1/me",
            auth="publishable",
            headers_extra={"Authorization": f"Bearer {access_token}"} if access_token else None,
        )

    def refresh_token(self, refresh_token: str) -> dict:
        return self._client._fetch(
            "/v1/tokens/session",
            method="POST",
            auth="publishable",
            body={"refresh_token": refresh_token},
        )

    def sso_exchange(self, token: str) -> dict:
        return self._client._fetch(
            "/v1/sso/exchange",
            method="POST",
            auth="publishable",
            body={"token": token},
        )

    def request_challenge(self) -> dict:
        return self._client._fetch("/v1/challenges", method="POST", auth="publishable")
