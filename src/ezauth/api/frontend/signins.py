"""Sign-in endpoint for password and magic-link strategies.

Both strategies are rate limited per IP and per address inside the auth
service, and the magic-link branch returns the same response for unknown
addresses so the endpoint reveals nothing about who has an account.
"""

from fastapi import APIRouter, HTTPException, Request, Response

from ezauth.cookies import set_session_cookies
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
            set_session_cookies(
                response,
                access_jwt=access_jwt,
                refresh_token=raw_refresh,
                app=app,
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
        if e.code == "rate_limited":
            status = 429
        elif e.code in ("invalid_credentials", "email_not_verified"):
            status = 401
        else:
            status = 400
        raise HTTPException(status_code=status, detail=e.message)
