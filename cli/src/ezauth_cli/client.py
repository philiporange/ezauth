import httpx


class EZAuthClient:
    def __init__(self, server_url: str, publishable_key: str):
        self.http = httpx.Client(
            base_url=server_url.rstrip("/"),
            headers={"X-Publishable-Key": publishable_key},
            timeout=30.0,
        )

    def request_challenge(self) -> dict:
        resp = self.http.post("/v1/challenges")
        resp.raise_for_status()
        return resp.json()

    def signup(self, email: str, password: str | None, hashcash: dict) -> dict:
        body: dict = {"email": email, "hashcash": hashcash}
        if password:
            body["password"] = password
        resp = self.http.post("/v1/signups", json=body)
        resp.raise_for_status()
        return resp.json()

    def signin(self, email: str, password: str | None = None, strategy: str = "magic_link") -> dict:
        body: dict = {"email": email, "strategy": strategy}
        if password:
            body["password"] = password
        resp = self.http.post("/v1/signins", json=body)
        resp.raise_for_status()
        return resp.json()

    def verify_code(self, email: str, code: str) -> dict:
        resp = self.http.post("/v1/verify-code", json={"email": email, "code": code})
        resp.raise_for_status()
        return resp.json()

    def me(self, access_token: str) -> dict:
        resp = self.http.get(
            "/v1/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        resp.raise_for_status()
        return resp.json()

    def logout(self, access_token: str) -> dict:
        resp = self.http.post(
            "/v1/sessions/logout",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        resp.raise_for_status()
        return resp.json()

    def refresh(self, refresh_token: str) -> dict:
        resp = self.http.post("/v1/tokens/session", json={"refresh_token": refresh_token})
        resp.raise_for_status()
        return resp.json()
