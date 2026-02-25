from fastapi import APIRouter, HTTPException, Request

from ezauth.config import settings
from ezauth.dependencies import AppDep, DbSession, RedisDep
from ezauth.schemas.auth import AuthResponse, SignupRequest
from ezauth.services.auth import AuthError, signup
from ezauth.services.hashcash import HashcashError, verify_proof

router = APIRouter()


@router.post("/signups", response_model=AuthResponse)
async def create_signup(
    body: SignupRequest,
    request: Request,
    db: DbSession,
    redis: RedisDep,
    app: AppDep,
):
    if settings.hashcash_enabled:
        if body.hashcash is None:
            raise HTTPException(
                status_code=422,
                detail="Proof of work required. Request a challenge from POST /v1/challenges first.",
            )
        try:
            await verify_proof(redis, body.hashcash.challenge, body.hashcash.nonce)
        except HashcashError as e:
            status = 410 if e.code == "challenge_expired" else 400
            raise HTTPException(status_code=status, detail=e.message)

    try:
        result = await signup(
            db,
            redis,
            app=app,
            email=body.email,
            password=body.password,
            redirect_url=body.redirect_url,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
        return AuthResponse(**result)
    except AuthError as e:
        status = 429 if e.code == "rate_limited" else 409 if e.code == "user_exists" else 400
        raise HTTPException(status_code=status, detail=e.message)
