from fastapi import APIRouter, HTTPException, Request, Response

from ezauth.config import settings
from ezauth.dependencies import AppDep, DbSession, RedisDep
from ezauth.schemas.auth import AuthResponse, SessionResponse, SigninRequest
from ezauth.services.auth import AuthError, signin_magic_link, signin_password

router = APIRouter()


@router.post("/signins")
async def create_signin(
    body: SigninRequest,
    request: Request,
    response: Response,
    db: DbSession,
    redis: RedisDep,
    app: AppDep,
):
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")

    try:
        if body.strategy == "password" and body.password:
            user, session, access_jwt, raw_refresh = await signin_password(
                db,
                redis,
                app=app,
                email=body.email,
                password=body.password,
                ip_address=ip,
                user_agent=ua,
            )
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
        else:
            result = await signin_magic_link(
                db,
                redis,
                app=app,
                email=body.email,
                redirect_url=body.redirect_url,
                ip_address=ip,
                user_agent=ua,
            )
            return AuthResponse(**result)
    except AuthError as e:
        status = 429 if e.code == "rate_limited" else 401 if e.code == "invalid_credentials" else 400
        raise HTTPException(status_code=status, detail=e.message)
