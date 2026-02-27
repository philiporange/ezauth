import time
import uuid

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from fastapi import APIRouter, HTTPException
from jose import jwt
from pydantic import BaseModel, EmailStr
from sqlalchemy import func, select, update
from datetime import datetime, timezone

from ezauth.crypto import generate_code
from ezauth.dependencies import DbSession
from ezauth.models.application import Application
from ezauth.models.auth_attempt import AuthAttempt, AuthAttemptStatus, AuthAttemptType
from ezauth.services.mail import MailService
from ezauth.services.tokens import create_auth_attempt

router = APIRouter()


class AdminAuthRequest(BaseModel):
    email: EmailStr


class AdminVerifyRequest(BaseModel):
    email: EmailStr
    code: str


@router.post("/admin/auth")
async def send_admin_login_code(body: AdminAuthRequest, db: DbSession):
    """Send a 6-digit login code to the owner email."""
    email = body.email.lower()

    result = await db.execute(
        select(Application).where(func.lower(Application.owner_email) == email)
    )
    apps = result.scalars().all()

    for app in apps:
        code = generate_code(6)
        await create_auth_attempt(
            db,
            app_id=app.id,
            type=AuthAttemptType.admin_login,
            email=email,
            expire_minutes=15,
            metadata={"code": code},
        )

        mail = MailService(
            sender_name=app.email_from_name,
            sender_address=app.email_from_address,
        )
        await mail.send_template(
            "admin_login_code",
            email,
            "Your EZAuth Dashboard Code",
            {
                "confirmation_code": code,
                "app_name": app.name,
                "name": "Admin",
            },
        )

    return {"status": "code_sent"}


@router.post("/admin/verify")
async def verify_admin_login_code(body: AdminVerifyRequest, db: DbSession):
    """Verify a 6-digit code and return an admin JWT."""
    email = body.email.lower()
    code = body.code.strip()
    now = datetime.now(timezone.utc)

    # Find and consume matching pending admin_login attempts
    stmt = (
        update(AuthAttempt)
        .where(
            AuthAttempt.type == AuthAttemptType.admin_login,
            func.lower(AuthAttempt.email) == email,
            AuthAttempt.status == AuthAttemptStatus.pending,
            AuthAttempt.expires_at > now,
            AuthAttempt.metadata_json["code"].astext == code,
        )
        .values(status=AuthAttemptStatus.consumed)
        .returning(AuthAttempt.app_id)
    )
    result = await db.execute(stmt)
    consumed_app_ids = [row[0] for row in result.fetchall()]

    if not consumed_app_ids:
        raise HTTPException(status_code=401, detail="Invalid or expired code")

    # Load the apps and mint admin JWTs
    app_result = await db.execute(
        select(Application).where(Application.id.in_(consumed_app_ids))
    )
    apps = app_result.scalars().all()

    tokens = []
    for app in apps:
        private_key = load_pem_private_key(app.jwk_private_pem.encode(), password=None)
        now_ts = int(time.time())
        claims = {
            "iss": "ezauth-admin",
            "sub": f"admin:{app.id}",
            "aud": str(app.id),
            "admin": True,
            "iat": now_ts,
            "exp": now_ts + 8 * 3600,  # 8 hours
        }
        token = jwt.encode(claims, private_key, algorithm="RS256")
        tokens.append({
            "admin_token": token,
            "app_id": str(app.id),
            "app_name": app.name,
        })

    if len(tokens) == 1:
        return tokens[0]
    return tokens
