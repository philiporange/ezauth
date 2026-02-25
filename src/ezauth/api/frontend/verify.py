from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from ezauth.config import settings
from ezauth.dependencies import AppDep, DbSession
from ezauth.services.auth import AuthError, consume_email_link_token

router = APIRouter()


@router.get("/email/verify")
async def verify_email(
    token: str,
    request: Request,
    db: DbSession,
    app: AppDep,
):
    try:
        user, session, access_jwt, raw_refresh, redirect_url = await consume_email_link_token(
            db,
            raw_token=token,
            app=app,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    except AuthError as e:
        raise HTTPException(status_code=400, detail=e.message)

    if not redirect_url:
        redirect_url = f"https://{app.primary_domain}" if app.primary_domain else "/"

    response = RedirectResponse(url=redirect_url, status_code=302)
    response.set_cookie(
        key=settings.session_cookie_name,
        value=access_jwt,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        domain=settings.session_cookie_domain or None,
    )
    return response
