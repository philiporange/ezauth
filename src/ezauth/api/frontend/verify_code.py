"""Code verification endpoint for the six-digit email codes.

A six-digit code is only a million possibilities, so guessing is bounded on
three axes: this endpoint rate limits by IP and by address, the token service
caps wrong guesses against each individual attempt, and issuing a new code
revokes the previous one so an attacker cannot widen the target by requesting
many at once.
"""

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field

from ezauth.cookies import set_session_cookies
from ezauth.dependencies import AppDep, DbSession, RedisDep
from ezauth.schemas.auth import SessionResponse
from ezauth.services.auth import AuthError, consume_code, enforce_code_rate_limits

router = APIRouter()


class VerifyCodeRequest(BaseModel):
    email: EmailStr
    code: str = Field(min_length=4, max_length=12)


@router.post("/verify-code", response_model=SessionResponse)
async def verify_code(
    body: VerifyCodeRequest,
    request: Request,
    response: Response,
    db: DbSession,
    redis: RedisDep,
    app: AppDep,
):
    ip = request.client.host if request.client else None

    try:
        await enforce_code_rate_limits(redis, app=app, email=body.email, ip_address=ip)
        user, session, access_jwt, raw_refresh, _redirect = await consume_code(
            db,
            email=body.email,
            code=body.code,
            app=app,
            ip_address=ip,
            user_agent=request.headers.get("user-agent"),
        )
    except AuthError as e:
        status = 429 if e.code in ("rate_limited", "too_many_attempts") else 400
        raise HTTPException(status_code=status, detail=e.message)

    set_session_cookies(
        response, access_jwt=access_jwt, refresh_token=raw_refresh, app=app
    )
    return SessionResponse(
        access_token=access_jwt,
        refresh_token=raw_refresh,
        user_id=str(user.id),
        session_id=str(session.id),
    )
