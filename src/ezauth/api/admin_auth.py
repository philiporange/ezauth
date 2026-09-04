"""Administrative login: email a code, exchange it for an admin API token.

An admin token carries the same authority over an application as its secret
key, so the six-digit code that produces one is the weakest link and is
defended accordingly. Requests for a code are rate limited by address and by
IP, and each new code revokes the address's previous pending codes, so an
attacker cannot mail-bomb an owner into having hundreds of simultaneously valid
codes and then guess against the whole set. Verification is rate limited on the
same two axes, and the token service burns an attempt after a handful of wrong
guesses. Only the code's digest is stored.

Issued tokens carry a `jti`, and logging out records that id on a Redis
deny-list which request authentication consults, so a token can be withdrawn
before its eight hours are up without rotating the application's signing key.
"""

import time
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from jose import jwt
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select

from ezauth.config import settings
from ezauth.crypto import generate_code
from ezauth.dependencies import (
    ADMIN_DENYLIST_PREFIX,
    ADMIN_TOKEN_ISSUER,
    DbSession,
    RedisDep,
    SecretKeyApp,
)
from ezauth.models.application import Application
from ezauth.models.auth_attempt import AuthAttemptType
from ezauth.ratelimiter import RateLimiter, parse_limits
from ezauth.services.mail import MailService
from ezauth.services.tokens import (
    TOO_MANY_ATTEMPTS,
    consume_admin_login_code,
    create_auth_attempt,
    revoke_pending_attempts,
)

router = APIRouter()

ADMIN_TOKEN_TTL_SECONDS = 8 * 3600
ADMIN_CODE_EXPIRE_MINUTES = 15


class AdminAuthRequest(BaseModel):
    email: EmailStr


class AdminVerifyRequest(BaseModel):
    email: EmailStr
    code: str = Field(min_length=4, max_length=12)


async def _limit(redis, config: str, key: str, message: str) -> None:
    limiter = RateLimiter(redis, parse_limits(config), user_id=key, namespace="admin")
    if not await limiter.check_and_consume():
        raise HTTPException(status_code=429, detail=message)


@router.post("/admin/auth")
async def send_admin_login_code(
    body: AdminAuthRequest,
    request: Request,
    db: DbSession,
    redis: RedisDep,
):
    """Email a login code to an owner address, if it owns any application."""
    email = body.email.lower()
    ip = request.client.host if request.client else "unknown"

    await _limit(redis, settings.admin_auth_rate_limit_ip, f"auth:{ip}", "Too many requests")
    await _limit(
        redis,
        settings.admin_auth_rate_limit_email,
        f"auth:{email}",
        "Too many requests for this address",
    )

    result = await db.execute(
        select(Application).where(func.lower(Application.owner_email) == email)
    )
    apps = result.scalars().all()

    code = generate_code(6)

    for app in apps:
        await revoke_pending_attempts(
            db, app_id=app.id, email=email, type=AuthAttemptType.admin_login
        )
        await create_auth_attempt(
            db,
            app_id=app.id,
            type=AuthAttemptType.admin_login,
            email=email,
            expire_minutes=ADMIN_CODE_EXPIRE_MINUTES,
            code=code,
        )

    if apps:
        app = apps[0]
        mail = MailService(
            sender_name=app.email_from_name or app.name,
            sender_address=app.email_from_address,
        )
        await mail.send_template(
            "admin_login_code",
            email,
            "Your ezAuth Dashboard Code",
            {"confirmation_code": code, "app_name": app.name, "name": "Admin"},
        )

    return {"status": "code_sent"}


@router.post("/admin/verify")
async def verify_admin_login_code(
    body: AdminVerifyRequest,
    request: Request,
    db: DbSession,
    redis: RedisDep,
):
    """Verify a login code and return an admin token per owned application."""
    email = body.email.lower()
    code = body.code.strip()
    ip = request.client.host if request.client else "unknown"

    await _limit(redis, settings.admin_verify_rate_limit_ip, f"verify:{ip}", "Too many attempts")
    await _limit(
        redis,
        settings.admin_verify_rate_limit_email,
        f"verify:{email}",
        "Too many attempts for this address",
    )

    app_ids, reason = await consume_admin_login_code(db, email=email, code=code)
    if not app_ids:
        status = 429 if reason == TOO_MANY_ATTEMPTS else 401
        detail = (
            "Too many incorrect attempts, request a new code"
            if reason == TOO_MANY_ATTEMPTS
            else "Invalid or expired code"
        )
        raise HTTPException(status_code=status, detail=detail)

    app_result = await db.execute(select(Application).where(Application.id.in_(app_ids)))
    apps = app_result.scalars().all()

    now_ts = int(time.time())
    tokens = []
    for app in apps:
        claims = {
            "iss": ADMIN_TOKEN_ISSUER,
            "sub": f"admin:{app.id}",
            "aud": str(app.id),
            "admin": True,
            "jti": str(uuid.uuid4()),
            "iat": now_ts,
            "exp": now_ts + ADMIN_TOKEN_TTL_SECONDS,
        }
        token = jwt.encode(claims, app.jwk_private_pem, algorithm="RS256")
        tokens.append(
            {"admin_token": token, "app_id": str(app.id), "app_name": app.name}
        )

    if len(tokens) == 1:
        return tokens[0]
    return tokens


@router.post("/admin/logout")
async def admin_logout(request: Request, redis: RedisDep, app: SecretKeyApp):
    """Revoke the presented admin token for the remainder of its lifetime."""
    authorization = request.headers.get("authorization", "")
    if not authorization.startswith("Bearer ") or authorization[7:].startswith("sk_"):
        raise HTTPException(status_code=400, detail="Not an admin token")

    try:
        claims = jwt.get_unverified_claims(authorization[7:])
    except Exception:
        raise HTTPException(status_code=400, detail="Not an admin token")

    jti = claims.get("jti")
    exp = claims.get("exp")
    if not jti:
        raise HTTPException(status_code=400, detail="Token cannot be revoked")

    ttl = ADMIN_TOKEN_TTL_SECONDS
    if isinstance(exp, int):
        ttl = max(1, exp - int(datetime.now(timezone.utc).timestamp()))

    await redis.setex(f"{ADMIN_DENYLIST_PREFIX}:{jti}", ttl, "1")
    return {"status": "revoked"}
