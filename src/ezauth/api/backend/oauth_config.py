from copy import deepcopy

from fastapi import APIRouter, HTTPException

from ezauth.dependencies import DbSession, SecretKeyApp
from ezauth.schemas.oauth import OAuthProviderConfig, OAuthProviderListResponse

router = APIRouter()

SUPPORTED_PROVIDERS = {"google", "apple"}


def _redact_config(config: dict) -> dict:
    """Return a copy with secret values redacted."""
    redacted = {}
    for k, v in config.items():
        if k in ("client_secret", "private_key") and v:
            redacted[k] = "***"
        else:
            redacted[k] = v
    return redacted


@router.get("/oauth/providers")
async def list_oauth_providers(
    app: SecretKeyApp,
) -> OAuthProviderListResponse:
    """List configured OAuth providers (secrets redacted)."""
    providers = {}
    oauth_config = (app.settings_json or {}).get("oauth_providers", {})
    for provider, config in oauth_config.items():
        providers[provider] = _redact_config(config)
    return OAuthProviderListResponse(providers=providers)


@router.put("/oauth/providers/{provider}")
async def configure_oauth_provider(
    provider: str,
    body: OAuthProviderConfig,
    db: DbSession,
    app: SecretKeyApp,
):
    """Configure OAuth credentials for a provider."""
    if provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported provider: {provider}. "
            f"Supported: {', '.join(sorted(SUPPORTED_PROVIDERS))}",
        )

    settings_json = deepcopy(app.settings_json or {})
    if "oauth_providers" not in settings_json:
        settings_json["oauth_providers"] = {}

    settings_json["oauth_providers"][provider] = body.model_dump(exclude_none=True)
    app.settings_json = settings_json
    await db.flush()

    return {"status": "configured", "provider": provider}


@router.delete("/oauth/providers/{provider}")
async def remove_oauth_provider(
    provider: str,
    db: DbSession,
    app: SecretKeyApp,
):
    """Remove a provider's OAuth configuration."""
    settings_json = deepcopy(app.settings_json or {})
    oauth_providers = settings_json.get("oauth_providers", {})

    if provider not in oauth_providers:
        raise HTTPException(status_code=404, detail=f"Provider '{provider}' is not configured")

    del oauth_providers[provider]
    settings_json["oauth_providers"] = oauth_providers
    app.settings_json = settings_json
    await db.flush()

    return {"status": "removed", "provider": provider}
