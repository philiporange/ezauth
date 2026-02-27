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
from ezauth.db.engine import async_session_factory
from ezauth.db.redis import get_redis as _get_redis
from ezauth.models.application import Application
from ezauth.models.domain import Domain


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


async def _try_admin_jwt(db: DbSession, token: str) -> Application | None:
    """Try to decode a token as an admin JWT. Returns Application if valid, None otherwise."""
    try:
        unverified = jwt.get_unverified_claims(token)
    except JWTError:
        return None
    if not unverified.get("admin") or "aud" not in unverified:
        return None
    app_id = unverified["aud"]
    result = await db.execute(select(Application).where(Application.id == uuid.UUID(app_id)))
    app = result.scalars().first()
    if app is None:
        return None
    private_key = load_pem_private_key(app.jwk_private_pem.encode(), password=None)
    public_key = private_key.public_key()
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    try:
        payload = jwt.decode(token, public_pem, algorithms=["RS256"], audience=str(app.id))
    except JWTError:
        return None
    if not payload.get("admin"):
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

    # Secret key auth
    if token.startswith("sk_"):
        result = await db.execute(
            select(Application).where(Application.secret_key == token)
        )
        app = result.scalars().first()
        if app is None:
            raise HTTPException(status_code=401, detail="Invalid secret key")
        return app

    # Admin JWT auth
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


async def require_session(
    db: DbSession,
    app: AppDep,
    request: Request,
) -> SessionData:
    """Verify session from __session cookie JWT."""
    cookie_name = settings.session_cookie_name
    token = request.cookies.get(cookie_name)

    if not token:
        # Also check Authorization header
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer ") and not auth_header[7:].startswith("sk_"):
            token = auth_header[7:]

    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    private_key = load_pem_private_key(app.jwk_private_pem.encode(), password=None)
    public_key = private_key.public_key()
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()

    try:
        payload = jwt.decode(
            token,
            public_pem,
            algorithms=["RS256"],
            audience=str(app.id),
        )
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid session token")

    return SessionData(
        user_id=uuid.UUID(payload["sub"]),
        session_id=uuid.UUID(payload["sid"]),
        app_id=app.id,
    )


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
    """Accept either secret key (admin) or publishable key + session (user)."""
    # 1. Secret key auth → admin
    if authorization and authorization.startswith("Bearer sk_"):
        secret_key = authorization[7:]
        result = await db.execute(
            select(Application).where(Application.secret_key == secret_key)
        )
        app = result.scalars().first()
        if app is None:
            raise HTTPException(status_code=401, detail="Invalid secret key")
        return AppAuth(app=app)

    # 1b. Admin JWT auth → admin
    if authorization and authorization.startswith("Bearer ") and not authorization[7:].startswith("sk_"):
        admin_app = await _try_admin_jwt(db, authorization[7:])
        if admin_app is not None:
            return AppAuth(app=admin_app)

    # 2. Publishable key / host domain + session → user
    app = await resolve_application(db, request, x_publishable_key)

    cookie_name = settings.session_cookie_name
    token = request.cookies.get(cookie_name)
    if not token:
        auth_header = (authorization or "")
        if auth_header.startswith("Bearer ") and not auth_header[7:].startswith("sk_"):
            token = auth_header[7:]

    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    private_key = load_pem_private_key(app.jwk_private_pem.encode(), password=None)
    public_key = private_key.public_key()
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()

    try:
        payload = jwt.decode(
            token, public_pem, algorithms=["RS256"], audience=str(app.id),
        )
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid session token")

    return AppAuth(
        app=app,
        user_id=uuid.UUID(payload["sub"]),
        session_id=uuid.UUID(payload["sid"]),
    )


AppAuthDep = Annotated[AppAuth, Depends(resolve_app_auth)]
