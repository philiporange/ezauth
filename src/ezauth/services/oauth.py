import base64
import hashlib
import json
import secrets
import time
from datetime import datetime, timezone

import httpx
from jose import JWTError
from jose import jwt as jose_jwt
from loguru import logger
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ezauth.config import settings
from ezauth.models.application import Application
from ezauth.models.oauth_identity import OAuthIdentity
from ezauth.models.user import User
from ezauth.services import audit, sessions
from ezauth.services.auth import AuthError

# In-memory JWKS cache: provider -> (keys_dict, fetched_timestamp)
_jwks_cache: dict[str, tuple[dict, float]] = {}
_JWKS_CACHE_TTL = 3600  # 1 hour

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"

APPLE_AUTH_URL = "https://appleid.apple.com/auth/authorize"
APPLE_TOKEN_URL = "https://appleid.apple.com/auth/token"
APPLE_JWKS_URL = "https://appleid.apple.com/auth/keys"


def get_oauth_config(app: Application, provider: str) -> dict | None:
    """Read OAuth provider config from app.settings_json."""
    if not app.settings_json:
        return None
    providers = app.settings_json.get("oauth_providers")
    if not providers:
        return None
    return providers.get(provider)


def decode_state(state: str) -> dict:
    """Base64-decode and JSON-parse the state parameter."""
    try:
        padded = state + "=" * (-len(state) % 4)
        raw = base64.urlsafe_b64decode(padded)
        return json.loads(raw)
    except Exception as e:
        raise AuthError("Invalid OAuth state", code="invalid_state") from e


def _build_redirect_uri(app: Application, provider: str) -> str:
    """Build the OAuth callback redirect URI for a provider."""
    if app.primary_domain:
        base = f"https://{app.primary_domain}"
    else:
        base = "http://localhost:8000"
    return f"{base}/v1/oauth/{provider}/callback"


async def get_authorization_url(
    app: Application,
    redis,
    provider: str,
    redirect_url: str,
) -> str:
    """Build the OAuth authorization URL for a provider."""
    config = get_oauth_config(app, provider)
    if not config:
        raise AuthError(
            f"OAuth provider '{provider}' is not configured",
            code="provider_not_configured",
        )

    # Generate CSRF nonce and store in Redis
    nonce = secrets.token_urlsafe(32)
    nonce_hash = hashlib.sha256(nonce.encode()).hexdigest()
    await redis.set(f"oauth_state:{nonce_hash}", "1", ex=settings.oauth_state_ttl_seconds)

    # Build state payload
    state_payload = {
        "nonce": nonce,
        "redirect_url": redirect_url,
        "pk": app.publishable_key,
    }
    state = base64.urlsafe_b64encode(json.dumps(state_payload).encode()).decode().rstrip("=")

    redirect_uri = _build_redirect_uri(app, provider)

    if provider == "google":
        from urllib.parse import urlencode
        params = {
            "response_type": "code",
            "client_id": config["client_id"],
            "redirect_uri": redirect_uri,
            "scope": "openid email profile",
            "state": state,
            "access_type": "offline",
            "prompt": "select_account",
        }
        return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"

    elif provider == "apple":
        from urllib.parse import urlencode
        params = {
            "response_type": "code",
            "client_id": config["client_id"],
            "redirect_uri": redirect_uri,
            "scope": "name email",
            "state": state,
            "response_mode": "form_post",
        }
        return f"{APPLE_AUTH_URL}?{urlencode(params)}"

    else:
        raise AuthError(f"Unsupported OAuth provider: {provider}", code="unsupported_provider")


def _generate_apple_client_secret(config: dict) -> str:
    """Generate a short-lived JWT client secret for Apple Sign-In."""
    now = int(time.time())
    headers = {"kid": config["key_id"], "alg": "ES256"}
    claims = {
        "iss": config["team_id"],
        "sub": config["client_id"],
        "aud": "https://appleid.apple.com",
        "iat": now,
        "exp": now + 300,  # 5 min
    }
    return jose_jwt.encode(claims, config["private_key"], algorithm="ES256", headers=headers)


async def _fetch_jwks(provider: str) -> dict:
    """Fetch and cache JWKS keys for a provider."""
    now = time.time()
    cached = _jwks_cache.get(provider)
    if cached and (now - cached[1]) < _JWKS_CACHE_TTL:
        return cached[0]

    url = GOOGLE_JWKS_URL if provider == "google" else APPLE_JWKS_URL
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, timeout=10)
        resp.raise_for_status()
        jwks = resp.json()

    _jwks_cache[provider] = (jwks, now)
    return jwks


async def _verify_id_token(provider: str, id_token: str, client_id: str) -> dict:
    """Decode and verify an ID token JWT against the provider's JWKS."""
    jwks = await _fetch_jwks(provider)

    if provider == "google":
        issuer = ["https://accounts.google.com", "accounts.google.com"]
    else:
        issuer = "https://appleid.apple.com"

    try:
        claims = jose_jwt.decode(
            id_token,
            jwks,
            algorithms=["RS256", "ES256"],
            audience=client_id,
            issuer=issuer,
        )
    except JWTError as e:
        raise AuthError(f"Invalid ID token: {e}", code="invalid_id_token") from e

    return claims


async def exchange_code(
    db: AsyncSession,
    redis,
    app: Application,
    provider: str,
    code: str,
    state: str,
    id_token_hint: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
):
    """Exchange an OAuth authorization code for a session.

    Returns (user, session, access_jwt, raw_refresh, redirect_url).
    """
    # 1. Decode and validate state
    state_data = decode_state(state)
    nonce = state_data.get("nonce")
    redirect_url = state_data.get("redirect_url", "")

    if not nonce:
        raise AuthError("Missing nonce in OAuth state", code="invalid_state")

    nonce_hash = hashlib.sha256(nonce.encode()).hexdigest()
    deleted = await redis.delete(f"oauth_state:{nonce_hash}")
    if not deleted:
        raise AuthError("Invalid or expired OAuth state", code="invalid_state")

    config = get_oauth_config(app, provider)
    if not config:
        raise AuthError(
            f"OAuth provider '{provider}' is not configured",
            code="provider_not_configured",
        )

    redirect_uri = _build_redirect_uri(app, provider)

    # 2. Exchange code for tokens
    id_token = None

    if provider == "google":
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "client_id": config["client_id"],
                    "client_secret": config["client_secret"],
                },
                timeout=10,
            )
        if resp.status_code != 200:
            logger.error(f"Google token exchange failed: {resp.status_code} {resp.text}")
            raise AuthError("Failed to exchange authorization code", code="token_exchange_failed")
        token_data = resp.json()
        id_token = token_data.get("id_token")

    elif provider == "apple":
        # Apple may send id_token directly via form_post
        if id_token_hint:
            id_token = id_token_hint
        else:
            client_secret = _generate_apple_client_secret(config)
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    APPLE_TOKEN_URL,
                    data={
                        "grant_type": "authorization_code",
                        "code": code,
                        "redirect_uri": redirect_uri,
                        "client_id": config["client_id"],
                        "client_secret": client_secret,
                    },
                    timeout=10,
                )
            if resp.status_code != 200:
                logger.error(f"Apple token exchange failed: {resp.status_code} {resp.text}")
                raise AuthError(
                    "Failed to exchange authorization code",
                    code="token_exchange_failed",
                )
            token_data = resp.json()
            id_token = token_data.get("id_token")

    if not id_token:
        raise AuthError("No ID token received from provider", code="no_id_token")

    # 3. Verify ID token
    claims = await _verify_id_token(provider, id_token, config["client_id"])

    sub = claims.get("sub")
    email = claims.get("email")
    email_verified = claims.get("email_verified", False)

    if not sub:
        raise AuthError("No subject in ID token", code="invalid_id_token")

    # 4. Find or create user
    user = await _find_or_create_user(
        db, app=app, provider=provider, sub=sub,
        email=email, email_verified=email_verified, claims=claims,
    )

    # 5. Create session
    session, access_jwt, raw_refresh = await sessions.create_session(
        db, app=app, user=user
    )

    # 6. Audit log
    await audit.log_event(
        db,
        app_id=app.id,
        event_type="user.signin_oauth",
        user_id=user.id,
        session_id=session.id,
        ip_address=ip_address,
        user_agent=user_agent,
        metadata={"provider": provider},
    )

    return user, session, access_jwt, raw_refresh, redirect_url


async def _find_or_create_user(
    db: AsyncSession,
    *,
    app: Application,
    provider: str,
    sub: str,
    email: str | None,
    email_verified: bool,
    claims: dict,
) -> User:
    """Find existing user by OAuth identity or email, or create a new one."""
    metadata = {}
    if claims.get("name"):
        metadata["name"] = claims["name"]
    if claims.get("picture"):
        metadata["picture"] = claims["picture"]

    # 1. Look up by OAuth identity
    result = await db.execute(
        select(OAuthIdentity).where(
            OAuthIdentity.app_id == app.id,
            OAuthIdentity.provider == provider,
            OAuthIdentity.provider_user_id == sub,
        )
    )
    identity = result.scalars().first()

    if identity:
        # Update metadata if changed
        if metadata and identity.metadata_json != metadata:
            identity.metadata_json = metadata
        if email and identity.email != email:
            identity.email = email
        await db.flush()

        user_result = await db.execute(select(User).where(User.id == identity.user_id))
        user = user_result.scalars().first()
        if user:
            return user

    # 2. Look up by email (link accounts)
    if email:
        result = await db.execute(
            select(User).where(
                User.app_id == app.id,
                User.email_lower == email.lower(),
            )
        )
        user = result.scalars().first()

        if user:
            # Link OAuth identity to existing user
            try:
                oauth_identity = OAuthIdentity(
                    app_id=app.id,
                    user_id=user.id,
                    provider=provider,
                    provider_user_id=sub,
                    email=email,
                    metadata_json=metadata or None,
                )
                db.add(oauth_identity)
                await db.flush()
            except IntegrityError:
                await db.rollback()
                # Race condition: identity was created concurrently, fetch it
                result = await db.execute(
                    select(OAuthIdentity).where(
                        OAuthIdentity.app_id == app.id,
                        OAuthIdentity.provider == provider,
                        OAuthIdentity.provider_user_id == sub,
                    )
                )
                identity = result.scalars().first()
                if identity:
                    user_result = await db.execute(select(User).where(User.id == identity.user_id))
                    user = user_result.scalars().first()
                    if user:
                        return user
                raise AuthError("Failed to link OAuth account", code="link_failed")
            return user

    # 3. Create new user
    user = User(
        app_id=app.id,
        email=email,
        email_verified_at=datetime.now(timezone.utc) if email_verified and email else None,
    )
    db.add(user)
    await db.flush()

    try:
        oauth_identity = OAuthIdentity(
            app_id=app.id,
            user_id=user.id,
            provider=provider,
            provider_user_id=sub,
            email=email,
            metadata_json=metadata or None,
        )
        db.add(oauth_identity)
        await db.flush()
    except IntegrityError:
        await db.rollback()
        # Race condition: retry lookup
        result = await db.execute(
            select(OAuthIdentity).where(
                OAuthIdentity.app_id == app.id,
                OAuthIdentity.provider == provider,
                OAuthIdentity.provider_user_id == sub,
            )
        )
        identity = result.scalars().first()
        if identity:
            user_result = await db.execute(select(User).where(User.id == identity.user_id))
            user = user_result.scalars().first()
            if user:
                return user
        raise AuthError("Failed to create OAuth account", code="create_failed")

    return user
