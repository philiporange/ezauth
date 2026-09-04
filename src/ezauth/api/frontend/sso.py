"""Cross-domain single sign-on between applications in the same tenant.

A signed-in browser hits `/sso/bridge` with the satellite domain it wants to
land on. The bridge resolves that domain to an application in the same tenant,
mints a one-time token bound to that specific target application, and redirects
with the token in the query string. The satellite calls `/sso/exchange`, which
consumes the token atomically and issues its own session.

The target is resolved from the tenant's verified domains rather than trusted
from the request, because the token in the redirect is a bearer credential for
the user's identity: an unvalidated `return_to` would let any link hand a
victim's session to an arbitrary host. Binding the token to the target
application also stops a token minted for one satellite from being replayed
against another, and the token is deleted as it is read so it cannot be reused.
"""

import uuid
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from ezauth.cookies import set_session_cookies
from ezauth.crypto import generate_token, hash_token
from ezauth.dependencies import AppDep, DbSession, RedisDep, SessionDep
from ezauth.models.application import Application
from ezauth.models.domain import Domain
from ezauth.models.user import User
from ezauth.services.sessions import create_session

router = APIRouter()

SSO_TOKEN_TTL_SECONDS = 60


async def _resolve_tenant_app_for_url(
    db, tenant_id: uuid.UUID, return_to: str
) -> Application | None:
    """Find the application in this tenant that owns the return_to host."""
    parsed = urlparse(return_to)
    if parsed.scheme not in ("http", "https"):
        return None
    host = (parsed.hostname or "").lower()
    if not host:
        return None

    result = await db.execute(
        select(Application)
        .join(Domain, Domain.app_id == Application.id)
        .where(
            Application.tenant_id == tenant_id,
            Domain.domain == host,
            Domain.verified.is_(True),
        )
    )
    app = result.scalars().first()
    if app is not None:
        return app

    result = await db.execute(
        select(Application).where(
            Application.tenant_id == tenant_id,
            Application.primary_domain == host,
        )
    )
    return result.scalars().first()


@router.get("/sso/bridge")
async def sso_bridge(
    return_to: str,
    request: Request,
    db: DbSession,
    redis: RedisDep,
    app: AppDep,
    session: SessionDep,
):
    """Issue a one-time SSO token for a verified domain in the same tenant."""
    target_app = await _resolve_tenant_app_for_url(db, app.tenant_id, return_to)
    if target_app is None:
        raise HTTPException(
            status_code=400,
            detail="return_to is not a verified domain for this tenant",
        )

    token = generate_token(32)
    token_hash = hash_token(token)

    await redis.setex(
        f"sso:{token_hash}",
        SSO_TOKEN_TTL_SECONDS,
        f"{session.user_id}:{session.app_id}:{target_app.id}",
    )

    separator = "&" if "?" in return_to else "?"
    return RedirectResponse(url=f"{return_to}{separator}__sso_token={token}", status_code=302)


@router.post("/sso/exchange")
async def sso_exchange(
    request: Request,
    response: Response,
    db: DbSession,
    redis: RedisDep,
    app: AppDep,
):
    """Exchange a one-time SSO token for a session on the satellite domain."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    token = body.get("token")
    if not token or not isinstance(token, str):
        raise HTTPException(status_code=400, detail="Missing token")

    key = f"sso:{hash_token(token)}"
    pipe = redis.pipeline()
    pipe.get(key)
    pipe.delete(key)
    results = await pipe.execute()

    stored = results[0]
    if not stored:
        raise HTTPException(status_code=401, detail="Invalid or expired SSO token")

    parts = stored.split(":")
    if len(parts) != 3:
        raise HTTPException(status_code=401, detail="Malformed SSO token data")

    try:
        user_id = uuid.UUID(parts[0])
        source_app_id = uuid.UUID(parts[1])
        target_app_id = uuid.UUID(parts[2])
    except ValueError:
        raise HTTPException(status_code=401, detail="Malformed SSO token data")

    if target_app_id != app.id:
        raise HTTPException(status_code=403, detail="SSO token was issued for another application")

    source_result = await db.execute(
        select(Application).where(Application.id == source_app_id)
    )
    source_app = source_result.scalars().first()
    if source_app is None or source_app.tenant_id != app.tenant_id:
        raise HTTPException(status_code=403, detail="Cross-tenant SSO is not allowed")

    user_result = await db.execute(
        select(User).where(User.id == user_id, User.app_id == source_app_id)
    )
    user = user_result.scalars().first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    session, access_jwt, raw_refresh = await create_session(db, app=app, user=user)

    set_session_cookies(
        response, access_jwt=access_jwt, refresh_token=raw_refresh, app=app
    )

    return {
        "access_token": access_jwt,
        "refresh_token": raw_refresh,
        "user_id": str(user.id),
        "session_id": str(session.id),
    }
