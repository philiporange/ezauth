"""Double-submit CSRF tokens for server-rendered form pages.

The hosted auth pages accept credentials from unauthenticated browsers, so
`SameSite=Lax` alone is not enough: a cross-site form post can still reach them
and log a victim into an attacker's account, which then captures whatever the
victim does next. Each rendered page carries a random token in both a cookie
and a hidden form field, and a submission is accepted only when the two match.
An attacker's page can cause a request to be sent but cannot read the cookie to
populate the field, so the pair cannot be forged.

The token is per-browser rather than per-form, is refreshed whenever a page is
rendered without one, and is compared in constant time.
"""

import secrets

from fastapi import Request, Response

from ezauth.config import settings

CSRF_COOKIE_NAME = "__csrf"
CSRF_FIELD_NAME = "csrf_token"
CSRF_COOKIE_MAX_AGE = 43200


def current_token(request: Request) -> str | None:
    return request.cookies.get(CSRF_COOKIE_NAME)


def issue_token(request: Request) -> str:
    """Reuse the browser's token, or mint one if it has none."""
    return current_token(request) or secrets.token_urlsafe(32)


def attach_token(response: Response, token: str, path: str = "/") -> Response:
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        max_age=CSRF_COOKIE_MAX_AGE,
        path=path,
    )
    return response


def verify(request: Request, submitted: str | None) -> bool:
    cookie_token = current_token(request)
    if not cookie_token or not submitted:
        return False
    return secrets.compare_digest(cookie_token, submitted)
