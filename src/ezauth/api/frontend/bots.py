"""Bot signup and authentication endpoints.

Bots register with a confirmed confirmations.info donation challenge and an
Ed25519 public key. They authenticate by signing a message containing their
bot ID and a timestamp.
"""

from fastapi import APIRouter, HTTPException, Request

from ezauth.dependencies import AppDep, DbSession, RedisDep
from ezauth.schemas.auth import SessionResponse
from ezauth.schemas.bot import BotAuthRequest, BotSignupRequest, BotSignupResponse
from ezauth.services.auth import AuthError
from ezauth.services.bots import auth_bot, signup_bot

router = APIRouter()


@router.post("/bot/signup", response_model=BotSignupResponse)
async def bot_signup(
    body: BotSignupRequest,
    request: Request,
    db: DbSession,
    redis: RedisDep,
    app: AppDep,
):
    try:
        result = await signup_bot(
            db,
            redis,
            app=app,
            challenge_id=body.challenge_id,
            public_key_b64=body.public_key,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
        return BotSignupResponse(**result)
    except AuthError as e:
        status_map = {
            "rate_limited": 429,
            "challenge_used": 409,
            "key_exists": 409,
            "challenge_not_found": 404,
            "challenge_not_confirmed": 400,
            "upstream_error": 502,
            "invalid_key": 400,
        }
        raise HTTPException(
            status_code=status_map.get(e.code, 400),
            detail=e.message,
        )


@router.post("/bot/auth", response_model=SessionResponse)
async def bot_auth(
    body: BotAuthRequest,
    request: Request,
    db: DbSession,
    redis: RedisDep,
    app: AppDep,
):
    try:
        user, session, access_jwt, raw_refresh = await auth_bot(
            db,
            redis,
            app=app,
            bot_id=body.bot_id,
            timestamp=body.timestamp,
            signature_b64=body.signature,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
        return SessionResponse(
            access_token=access_jwt,
            refresh_token=raw_refresh,
            user_id=str(user.id),
            session_id=str(session.id),
        )
    except AuthError as e:
        status_map = {
            "rate_limited": 429,
            "timestamp_expired": 401,
            "bot_not_found": 404,
            "invalid_bot_id": 400,
            "invalid_signature": 401,
        }
        raise HTTPException(
            status_code=status_map.get(e.code, 400),
            detail=e.message,
        )
