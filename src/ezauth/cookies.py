"""Session cookie handling for browser-based flows.

Browser sign-in issues two cookies. The access cookie holds the short-lived JWT
that authenticates ordinary requests. The refresh cookie holds the rotating
refresh token and is scoped to the refresh endpoint's path, so it is not sent
with every request and a cross-site scripting bug on an application page has a
much smaller window to steal it. Without the refresh cookie a browser session
would stop working when the access token expired minutes after sign-in, because
the refresh token was only ever returned in JSON to API callers.

Cookie names carry a discriminator derived from the application id. Two
applications served from the same parent domain would otherwise share one
`__session` cookie and repeatedly overwrite each other, leaving a signed-in
user wedged on 401s because the surviving token names the wrong audience. Both
cookies are cleared with the domain and path they were set with.
"""

import hashlib
from datetime import timedelta

from fastapi import Response

from ezauth.config import settings
from ezauth.models.application import Application


def _suffix(app: Application | None) -> str:
    if app is None or not settings.session_cookie_per_app:
        return ""
    return "_" + hashlib.sha256(str(app.id).encode()).hexdigest()[:8]


def session_cookie_name(app: Application | None = None) -> str:
    return settings.session_cookie_name + _suffix(app)


def refresh_cookie_name(app: Application | None = None) -> str:
    return settings.refresh_cookie_name + _suffix(app)


def set_session_cookies(
    response: Response,
    *,
    access_jwt: str,
    refresh_token: str | None = None,
    app: Application | None = None,
) -> Response:
    """Attach the access cookie, and the refresh cookie when one is issued."""
    response.set_cookie(
        key=session_cookie_name(app),
        value=access_jwt,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        domain=settings.session_cookie_domain or None,
    )
    if refresh_token:
        response.set_cookie(
            key=refresh_cookie_name(app),
            value=refresh_token,
            httponly=True,
            secure=settings.session_cookie_secure,
            samesite="lax",
            domain=settings.session_cookie_domain or None,
            path=settings.refresh_cookie_path,
            max_age=int(
                timedelta(days=settings.jwt_refresh_token_expire_days).total_seconds()
            ),
        )
    return response


def clear_session_cookies(
    response: Response, app: Application | None = None
) -> Response:
    domain = settings.session_cookie_domain or None
    response.delete_cookie(key=session_cookie_name(app), domain=domain)
    response.delete_cookie(
        key=refresh_cookie_name(app),
        domain=domain,
        path=settings.refresh_cookie_path,
    )
    return response
