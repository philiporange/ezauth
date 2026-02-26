from pydantic import BaseModel


class OAuthAuthorizeResponse(BaseModel):
    authorization_url: str


class OAuthProviderConfig(BaseModel):
    client_id: str
    client_secret: str | None = None
    team_id: str | None = None
    key_id: str | None = None
    private_key: str | None = None


class OAuthProviderListResponse(BaseModel):
    providers: dict[str, dict]
