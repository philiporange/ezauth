"""FastAPI dependencies for database sessions, application resolution and auth.

Three kinds of caller reach the API and each is resolved here. A frontend
caller presents a publishable key (or arrives on a verified custom domain) plus
a session cookie or bearer access token; a backend caller presents a secret key;
a dashboard administrator presents an admin JWT signed with the application's
own key. `resolve_app_auth` accepts any of them and reports which it was, so
route handlers can apply the right scope.

Session tokens are verified against the application's public key and then, when
`session_revocation_check` is on, against the sessions table, so logout and
revocation take effect immediately rather than when the short-lived JWT
expires. Admin JWTs are additionally checked for the issuer and for a `jti`
that has not been placed on the Redis deny-list by an admin logout. Public keys
are derived once per application key id and cached, since deriving one from the
stored PEM on every request is expensive.
"""

import uuid
from dataclasses import dataclass
from typing import Annotated

import redis.asyncio as aioredis
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from fastapi import Depends, Header, HTTPException, Request
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ezauth.config import settings
from ezauth.cookies import session_cookie_name
from ezauth.db.engine import async_session_factory
from ezauth.db.redis import get_redis as _get_redis
from ezauth.models.application import Application
from ezauth.models.domain import Domain
from ezauth.services import keys as key_service
from ezauth.services.sessions import is_session_active

ADMIN_TOKEN_ISSUER = "ezauth-admin"
ADMIN_DENYLIST_PREFIX = "admin_jti_revoked"

# Derived public keys, keyed by the application's jwk_kid.
_public_key_cache: dict[str, str] = {}


async def get_db():
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_redis_dep() -> aioredis.Redis:
    return _get_redis()


DbSession = Annotated[AsyncSession, Depends(get_db)]
RedisDep = Annotated[aioredis.Redis, Depends(get_redis_dep)]


def public_pem_for_key(kid: str, private_pem: str) -> str:
    """Public key PEM for a signing key, derived once per key id."""
    cached = _public_key_cache.get(kid)
    if cached is not None:
        return cached

    private_key = load_pem_private_key(private_pem.encode(), password=None)
    public_pem = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    _public_key_cache[kid] = public_pem
    return public_pem


async def decode_with_app_keys(
    db: AsyncSession, app: Application, token: str, **decode_kwargs
) -> dict | None:
    """Decode a token against any key the application still publishes.

    A token signed just before a rotation must keep verifying, so every
    non-dropped key is tried rather than only the active one.
    """
    for key in await key_service.verification_keys(db, app):
        try:
            return jwt.decode(
                token,
                public_pem_for_key(key.kid, key.private_pem),
                algorithms=["RS256"],
                **decode_kwargs,
            )
        except JWTError:
            continue
    return None


async def resolve_application(
    db: DbSession,
    request: Request,
    x_publishable_key: str | None = Header(None, alias="X-Publishable-Key"),
) -> Application:
    """Resolve the application from publishable key header or Host-based domain lookup."""
    if x_publishable_key:
        result = await db.execute(
            select(Application).where(Application.publishable_key == x_publishable_key)
        )
        app = result.scalars().first()
        if app is None:
            raise HTTPException(status_code=401, detail="Invalid publishable key")
        return app

    # Fallback: Host-based domain lookup
    host = request.headers.get("host", "").split(":")[0]
    if host:
        result = await db.execute(
            select(Domain).where(Domain.domain == host, Domain.verified.is_(True))
        )
        domain = result.scalars().first()
        if domain:
            app_result = await db.execute(
                select(Application).where(Application.id == domain.app_id)
            )
            app = app_result.scalars().first()
            if app:
                return app

    raise HTTPException(status_code=401, detail="Could not resolve application")


AppDep = Annotated[Application, Depends(resolve_application)]


async def _try_admin_jwt(db: AsyncSession, token: str) -> Application | None:
    """Decode a token as an admin JWT, returning its Application when valid."""
    try:
        unverified = jwt.get_unverified_claims(token)
    except JWTError:
        return None
    if not unverified.get("admin") or "aud" not in unverified:
        return None
    try:
        app_id = uuid.UUID(unverified["aud"])
    except (ValueError, TypeError):
        return None

    result = await db.execute(select(Application).where(Application.id == app_id))
    app = result.scalars().first()
    if app is None:
        return None

    payload = await decode_with_app_keys(
        db, app, token, audience=str(app.id), issuer=ADMIN_TOKEN_ISSUER
    )
    if payload is None or not payload.get("admin"):
        return None

    jti = payload.get("jti")
    if not jti:
        return None
    try:
        revoked = await _get_redis().exists(f"{ADMIN_DENYLIST_PREFIX}:{jti}")
    except Exception:
        # A Redis outage must not silently widen access.
        raise HTTPException(status_code=503, detail="Authentication backend unavailable")
    if revoked:
        return None

    return app


async def require_secret_key(
    db: DbSession,
    authorization: str | None = Header(None),
) -> Application:
    """Authenticate via secret key in Authorization: Bearer sk_... or admin JWT."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing secret key")

    token = authorization[7:]

    if token.startswith("sk_"):
        result = await db.execute(
            select(Application).where(Application.secret_key == token)
        )
        app = result.scalars().first()
        if app is None:
            raise HTTPException(status_code=401, detail="Invalid secret key")
        return app

    app = await _try_admin_jwt(db, token)
    if app is not None:
        return app

    raise HTTPException(status_code=401, detail="Invalid secret key")


SecretKeyApp = Annotated[Application, Depends(require_secret_key)]


class SessionData:
    def __init__(self, user_id: uuid.UUID, session_id: uuid.UUID, app_id: uuid.UUID):
        self.user_id = user_id
        self.session_id = session_id
        self.app_id = app_id


def _bearer_session_token(
    request: Request, authorization: str | None, app: Application
) -> str | None:
    """Session token from the cookie, falling back to a non-secret bearer token."""
    token = request.cookies.get(session_cookie_name(app))
    if token:
        return token
    header = authorization
    if header is None:
        header = request.headers.get("authorization", "")
    if header and header.startswith("Bearer ") and not header[7:].startswith("sk_"):
        return header[7:]
    return None


async def _verify_session_token(
    db: AsyncSession, app: Application, token: str
) -> tuple[uuid.UUID, uuid.UUID]:
    """Verify a session JWT and confirm the session has not been revoked."""
    payload = await decode_with_app_keys(db, app, token, audience=str(app.id))
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid session token")

    if payload.get("admin"):
        raise HTTPException(status_code=401, detail="Invalid session token")

    try:
        user_id = uuid.UUID(payload["sub"])
        session_id = uuid.UUID(payload["sid"])
    except (KeyError, ValueError, TypeError):
        raise HTTPException(status_code=401, detail="Invalid session token")

    if settings.session_revocation_check:
        if not await is_session_active(db, session_id=session_id, app_id=app.id):
            raise HTTPException(status_code=401, detail="Session has been revoked")

    return user_id, session_id


async def require_session(
    db: DbSession,
    app: AppDep,
    request: Request,
) -> SessionData:
    """Verify the session cookie or bearer access token for the resolved app."""
    token = _bearer_session_token(request, None, app)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    user_id, session_id = await _verify_session_token(db, app, token)
    return SessionData(user_id=user_id, session_id=session_id, app_id=app.id)


SessionDep = Annotated[SessionData, Depends(require_session)]


@dataclass
class AppAuth:
    app: Application
    user_id: uuid.UUID | None = None
    session_id: uuid.UUID | None = None

    @property
    def is_admin(self) -> bool:
        return self.user_id is None


async def resolve_app_auth(
    db: DbSession,
    request: Request,
    authorization: str | None = Header(None),
    x_publishable_key: str | None = Header(None, alias="X-Publishable-Key"),
) -> AppAuth:
    """Accept either secret key or admin JWT (admin), or publishable key plus session (user)."""
    if authorization and authorization.startswith("Bearer sk_"):
        secret_key = authorization[7:]
        result = await db.execute(
            select(Application).where(Application.secret_key == secret_key)
        )
        app = result.scalars().first()
        if app is None:
            raise HTTPException(status_code=401, detail="Invalid secret key")
        return AppAuth(app=app)

    if (
        authorization
        and authorization.startswith("Bearer ")
        and not authorization[7:].startswith("sk_")
    ):
        admin_app = await _try_admin_jwt(db, authorization[7:])
        if admin_app is not None:
            return AppAuth(app=admin_app)

    app = await resolve_application(db, request, x_publishable_key)

    token = _bearer_session_token(request, authorization, app)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    user_id, session_id = await _verify_session_token(db, app, token)
    return AppAuth(app=app, user_id=user_id, session_id=session_id)


AppAuthDep = Annotated[AppAuth, Depends(resolve_app_auth)]
