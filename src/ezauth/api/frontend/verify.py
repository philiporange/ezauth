"""Magic-link and email-verification landing endpoint.

Following the link with GET does not consume it. Mail security products and
link previewers fetch every URL in a message, and a GET that signed the user in
would let those fetches burn the token before the recipient ever clicked, so
the GET renders a confirmation page and the token is consumed by the POST that
the recipient's own click submits.

The redirect target stored on the attempt is re-validated against the
application's domains before the browser is sent there, so a target that was
allowed when the link was issued but has since been removed cannot be used.
"""

import pathlib

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from ezauth.cookies import set_session_cookies
from ezauth.dependencies import AppDep, DbSession
from ezauth.redirects import safe_redirect_url
from ezauth.services.auth import AuthError, consume_email_link_token

router = APIRouter()

_TEMPLATE_DIR = pathlib.Path(__file__).parent.parent.parent / "hosted" / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATE_DIR))


@router.get("/email/verify")
async def verify_email_page(
    token: str,
    request: Request,
    app: AppDep,
):
    """Show a confirmation page; the link is consumed by the POST it submits."""
    return templates.TemplateResponse(
        request,
        "confirm_link.html",
        {"app_name": app.name, "token": token},
    )


@router.post("/email/verify")
async def verify_email(
    request: Request,
    db: DbSession,
    app: AppDep,
    token: str = "",
):
    """Consume a verification or magic-link token and open a session."""
    if not token:
        form = await request.form()
        token = form.get("token", "")
    if not token:
        raise HTTPException(status_code=400, detail="Missing token")

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

    final_url = await safe_redirect_url(db, app, redirect_url)

    return set_session_cookies(
        RedirectResponse(url=final_url, status_code=302),
        access_jwt=access_jwt,
        refresh_token=raw_refresh,
        app=app,
    )
