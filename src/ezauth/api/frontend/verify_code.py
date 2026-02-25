from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr

from ezauth.config import settings
from ezauth.dependencies import AppDep, DbSession
from ezauth.schemas.auth import SessionResponse
from ezauth.services.auth import AuthError, consume_code

router = APIRouter()


class VerifyCodeRequest(BaseModel):
    email: EmailStr
    code: str


@router.post("/verify-code", response_model=SessionResponse)
async def verify_code(
    body: VerifyCodeRequest,
    request: Request,
    response: Response,
    db: DbSession,
    app: AppDep,
):
    try:
        user, session, access_jwt, raw_refresh, _redirect = await consume_code(
            db,
            email=body.email,
            code=body.code,
            app=app,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    except AuthError as e:
        raise HTTPException(status_code=400, detail=e.message)

    response.set_cookie(
        key=settings.session_cookie_name,
        value=access_jwt,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        domain=settings.session_cookie_domain or None,
    )
    return SessionResponse(
        access_token=access_jwt,
        refresh_token=raw_refresh,
        user_id=str(user.id),
        session_id=str(session.id),
    )
