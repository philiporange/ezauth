"""Google and Apple sign-in, from authorization URL through to a local session.

Starting a flow stores everything security-relevant server-side in Redis under
a random nonce: the PKCE code verifier, the OIDC nonce, the validated redirect
target, and a digest of a secret that is also written to the browser as a
cookie. The `state` parameter carries only the lookup nonce and the publishable
key, so nothing an attacker can edit in the callback URL influences where the
browser is sent or which application is used.

That layout is what defeats the three standard attacks on this flow. The state
cookie binds the callback to the browser that began it, so a captured callback
URL replayed against a victim cannot silently sign them into the attacker's
account. PKCE binds the authorization code to this client, so an intercepted
code is useless. The OIDC nonce is checked against the ID token, so a token
minted for another flow is rejected, and the authorization code is always
exchanged with the provider rather than trusting an ID token posted to the
callback.

Linking an OAuth identity to an existing local account requires the provider to
assert the address is verified and requires the local account to be verified
too. Without both checks, registering an unverified password account for
someone else's address would capture their later OAuth sign-in.
"""

import base64
import hashlib
import json
import secrets
import time
from datetime import datetime, timezone
from urllib.parse import urlencode

import httpx
from jose import JWTError
from jose import jwt as jose_jwt
from loguru import logger
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ezauth.config import settings
from ezauth.crypto import constant_time_compare, hash_token
from ezauth.models.application import Application
from ezauth.models.oauth_identity import OAuthIdentity
from ezauth.models.user import User
from ezauth.redirects import is_allowed_redirect
from ezauth.services import audit, sessions
from ezauth.services.auth import AuthError

# Provider JWKS documents, cached per process as (keys, fetched_at).
_jwks_cache: dict[str, tuple[dict, float]] = {}
_JWKS_CACHE_TTL = 3600

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"

APPLE_AUTH_URL = "https://appleid.apple.com/auth/authorize"
APPLE_TOKEN_URL = "https://appleid.apple.com/auth/token"
APPLE_JWKS_URL = "https://appleid.apple.com/auth/keys"

SUPPORTED_PROVIDERS = ("google", "apple")


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
        data = json.loads(raw)
    except Exception as e:
        raise AuthError("Invalid OAuth state", code="invalid_state") from e
    if not isinstance(data, dict):
        raise AuthError("Invalid OAuth state", code="invalid_state")
    return data


def _encode_state(payload: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")


def _build_redirect_uri(app: Application, provider: str) -> str:
    """Build the OAuth callback redirect URI registered with the provider."""
    if app.primary_domain:
        base = f"https://{app.primary_domain}"
    else:
        base = settings.public_base_url.rstrip("/")
    return f"{base}/v1/oauth/{provider}/callback"


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def _state_key(nonce: str) -> str:
    return f"oauth_state:{hashlib.sha256(nonce.encode()).hexdigest()}"


async def get_authorization_url(
    db: AsyncSession,
    app: Application,
    redis,
    provider: str,
    redirect_url: str,
) -> tuple[str, str]:
    """Build the provider authorization URL.

    Returns (authorization_url, state_secret). The caller must set state_secret
    as a cookie on the browser it is redirecting, so the callback can prove it
    belongs to the same browser that started the flow.
    """
    if provider not in SUPPORTED_PROVIDERS:
        raise AuthError(f"Unsupported OAuth provider: {provider}", code="unsupported_provider")

    config = get_oauth_config(app, provider)
    if not config:
        raise AuthError(
            f"OAuth provider '{provider}' is not configured",
            code="provider_not_configured",
        )

    if redirect_url and not await is_allowed_redirect(db, app, redirect_url):
        raise AuthError(
            "redirect_url is not an allowed domain for this application",
            code="invalid_redirect_url",
        )

    nonce = secrets.token_urlsafe(32)
    state_secret = secrets.token_urlsafe(32)
    oidc_nonce = secrets.token_urlsafe(32)
    verifier, challenge = _pkce_pair()

    await redis.set(
        _state_key(nonce),
        json.dumps(
            {
                "app_id": str(app.id),
                "provider": provider,
                "redirect_url": redirect_url or "",
                "code_verifier": verifier,
                "oidc_nonce": oidc_nonce,
                "state_secret_hash": hash_token(state_secret),
            }
        ),
        ex=settings.oauth_state_ttl_seconds,
    )

    state = _encode_state({"nonce": nonce, "pk": app.publishable_key})
    redirect_uri = _build_redirect_uri(app, provider)

    common = {
        "response_type": "code",
        "client_id": config["client_id"],
        "redirect_uri": redirect_uri,
        "state": state,
        "nonce": oidc_nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }

    if provider == "google":
        params = {
            **common,
            "scope": "openid email profile",
            "access_type": "offline",
            "prompt": "select_account",
        }
        return f"{GOOGLE_AUTH_URL}?{urlencode(params)}", state_secret

    params = {**common, "scope": "name email", "response_mode": "form_post"}
    return f"{APPLE_AUTH_URL}?{urlencode(params)}", state_secret


async def consume_state(redis, state: str) -> dict:
    """Atomically read and delete the server-side record for a state nonce."""
    state_data = decode_state(state)
    nonce = state_data.get("nonce")
    if not nonce or not isinstance(nonce, str):
        raise AuthError("Missing nonce in OAuth state", code="invalid_state")

    key = _state_key(nonce)
    pipe = redis.pipeline()
    pipe.get(key)
    pipe.delete(key)
    results = await pipe.execute()

    stored = results[0]
    if not stored:
        raise AuthError("Invalid or expired OAuth state", code="invalid_state")

    try:
        return json.loads(stored)
    except json.JSONDecodeError as e:
        raise AuthError("Invalid or expired OAuth state", code="invalid_state") from e


def _generate_apple_client_secret(config: dict) -> str:
    """Generate a short-lived JWT client secret for Apple Sign-In."""
    now = int(time.time())
    headers = {"kid": config["key_id"], "alg": "ES256"}
    claims = {
        "iss": config["team_id"],
        "sub": config["client_id"],
        "aud": "https://appleid.apple.com",
        "iat": now,
        "exp": now + 300,
    }
    return jose_jwt.encode(claims, config["private_key"], algorithm="ES256", headers=headers)


async def _fetch_jwks(provider: str, force: bool = False) -> dict:
    """Fetch provider JWKS, refreshing when a key id is not in the cache."""
    now = time.time()
    cached = _jwks_cache.get(provider)
    if cached and not force and (now - cached[1]) < _JWKS_CACHE_TTL:
        return cached[0]

    url = GOOGLE_JWKS_URL if provider == "google" else APPLE_JWKS_URL
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, timeout=10)
        resp.raise_for_status()
        jwks = resp.json()

    _jwks_cache[provider] = (jwks, now)
    return jwks


def _kid_present(jwks: dict, id_token: str) -> bool:
    try:
        header = jose_jwt.get_unverified_header(id_token)
    except JWTError:
        return True
    kid = header.get("kid")
    if not kid:
        return True
    return any(key.get("kid") == kid for key in jwks.get("keys", []))


async def _verify_id_token(
    provider: str, id_token: str, client_id: str, expected_nonce: str
) -> dict:
    """Verify an ID token against the provider's JWKS and the flow's nonce."""
    jwks = await _fetch_jwks(provider)
    if not _kid_present(jwks, id_token):
        jwks = await _fetch_jwks(provider, force=True)

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
        raise AuthError("Invalid ID token", code="invalid_id_token") from e

    token_nonce = claims.get("nonce")
    if not token_nonce or not constant_time_compare(str(token_nonce), expected_nonce):
        raise AuthError("ID token nonce mismatch", code="invalid_id_token")

    return claims


async def _request_tokens(provider: str, config: dict, data: dict) -> dict:
    url = GOOGLE_TOKEN_URL if provider == "google" else APPLE_TOKEN_URL
    async with httpx.AsyncClient() as client:
        resp = await client.post(url, data=data, timeout=10)
    if resp.status_code != 200:
        logger.error("{} token exchange failed with status {}", provider, resp.status_code)
        raise AuthError("Failed to exchange authorization code", code="token_exchange_failed")
    return resp.json()


async def exchange_code(
    db: AsyncSession,
    redis,
    app: Application,
    provider: str,
    code: str,
    state_record: dict,
    state_secret: str | None,
    ip_address: str | None = None,
    user_agent: str | None = None,
):
    """Exchange an authorization code for a local session.

    `state_record` is the server-side record returned by `consume_state` and
    `state_secret` is the value from the browser's state cookie.

    Returns (user, session, access_jwt, raw_refresh, redirect_url).
    """
    expected_hash = state_record.get("state_secret_hash")
    if not expected_hash or not state_secret:
        raise AuthError("OAuth state is not bound to this browser", code="invalid_state")
    if not constant_time_compare(expected_hash, hash_token(state_secret)):
        raise AuthError("OAuth state is not bound to this browser", code="invalid_state")

    if state_record.get("app_id") != str(app.id):
        raise AuthError("OAuth state belongs to another application", code="invalid_state")
    if state_record.get("provider") != provider:
        raise AuthError("OAuth state belongs to another provider", code="invalid_state")

    config = get_oauth_config(app, provider)
    if not config:
        raise AuthError(
            f"OAuth provider '{provider}' is not configured",
            code="provider_not_configured",
        )

    redirect_uri = _build_redirect_uri(app, provider)
    token_request = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": config["client_id"],
        "code_verifier": state_record.get("code_verifier", ""),
    }

    if provider == "google":
        token_request["client_secret"] = config["client_secret"]
    else:
        token_request["client_secret"] = _generate_apple_client_secret(config)

    token_data = await _request_tokens(provider, config, token_request)
    id_token = token_data.get("id_token")
    if not id_token:
        raise AuthError("No ID token received from provider", code="no_id_token")

    claims = await _verify_id_token(
        provider, id_token, config["client_id"], state_record.get("oidc_nonce", "")
    )

    sub = claims.get("sub")
    if not sub:
        raise AuthError("No subject in ID token", code="invalid_id_token")

    user = await _find_or_create_user(
        db,
        app=app,
        provider=provider,
        sub=sub,
        email=claims.get("email"),
        email_verified=bool(claims.get("email_verified", False)),
        claims=claims,
    )

    session, access_jwt, raw_refresh = await sessions.create_session(db, app=app, user=user)

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

    return user, session, access_jwt, raw_refresh, state_record.get("redirect_url") or ""


async def _identity_user(db: AsyncSession, app: Application, provider: str, sub: str):
    result = await db.execute(
        select(OAuthIdentity).where(
            OAuthIdentity.app_id == app.id,
            OAuthIdentity.provider == provider,
            OAuthIdentity.provider_user_id == sub,
        )
    )
    identity = result.scalars().first()
    if identity is None:
        return None, None
    user_result = await db.execute(select(User).where(User.id == identity.user_id))
    return identity, user_result.scalars().first()


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
    """Find the user for an OAuth identity, linking or creating as appropriate."""
    metadata = {}
    if claims.get("name"):
        metadata["name"] = claims["name"]
    if claims.get("picture"):
        metadata["picture"] = claims["picture"]

    identity, user = await _identity_user(db, app, provider, sub)
    if identity is not None:
        if metadata and identity.metadata_json != metadata:
            identity.metadata_json = metadata
        if email and identity.email != email:
            identity.email = email
        await db.flush()
        if user is not None:
            return user

    if email:
        result = await db.execute(
            select(User).where(
                User.app_id == app.id,
                User.email_lower == email.lower(),
            )
        )
        existing = result.scalars().first()

        if existing is not None:
            if not email_verified:
                raise AuthError(
                    "The provider has not verified this email address",
                    code="provider_email_unverified",
                )
            if existing.email_verified_at is None and existing.password_hash is not None:
                raise AuthError(
                    "An unverified account already uses this email address. "
                    "Sign in with your password and verify it first.",
                    code="link_requires_verification",
                )

            try:
                db.add(
                    OAuthIdentity(
                        app_id=app.id,
                        user_id=existing.id,
                        provider=provider,
                        provider_user_id=sub,
                        email=email,
                        metadata_json=metadata or None,
                    )
                )
                await db.flush()
            except IntegrityError:
                await db.rollback()
                _identity, raced = await _identity_user(db, app, provider, sub)
                if raced is not None:
                    return raced
                raise AuthError("Failed to link OAuth account", code="link_failed")

            if existing.email_verified_at is None:
                existing.email_verified_at = datetime.now(timezone.utc)
                await db.flush()
            return existing

    user = User(
        app_id=app.id,
        email=email,
        email_verified_at=datetime.now(timezone.utc) if email_verified and email else None,
    )
    db.add(user)
    await db.flush()

    try:
        db.add(
            OAuthIdentity(
                app_id=app.id,
                user_id=user.id,
                provider=provider,
                provider_user_id=sub,
                email=email,
                metadata_json=metadata or None,
            )
        )
        await db.flush()
    except IntegrityError:
        await db.rollback()
        _identity, raced = await _identity_user(db, app, provider, sub)
        if raced is not None:
            return raced
        raise AuthError("Failed to create OAuth account", code="create_failed")

    return user
