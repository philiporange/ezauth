"""Redirect-target validation shared by the API routes and the hosted auth pages.

Any URL that reaches a browser redirect or is embedded in an email must be
checked against the application it belongs to, otherwise an attacker can point
a legitimate-looking auth link at a host they control and collect the session
token that lands there. `is_allowed_redirect` accepts only same-site relative
paths, the application's primary domain, and hostnames with a verified `Domain`
row for that application. `safe_redirect_url` wraps it and falls back to the
application's own origin so callers never have to handle a rejection inline.
"""

from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ezauth.config import settings
from ezauth.models.application import Application
from ezauth.models.domain import Domain


def app_base_url(app: Application) -> str:
    """Public origin for an application, used for links in email."""
    if app.primary_domain:
        return f"https://{app.primary_domain}"
    return settings.public_base_url.rstrip("/")


def _is_relative_path(url: str) -> bool:
    """True for same-site paths like /dashboard, excluding //evil.com."""
    return url.startswith("/") and not url.startswith("//")


async def is_allowed_redirect(
    db: AsyncSession | None, app: Application, redirect_url: str | None
) -> bool:
    """Whether redirect_url may be used as a redirect target for this app."""
    if not redirect_url:
        return False

    if _is_relative_path(redirect_url):
        return True

    parsed = urlparse(redirect_url)
    if parsed.scheme not in ("http", "https"):
        return False

    host = parsed.hostname
    if not host:
        return False
    host = host.lower()

    if app.primary_domain and host == app.primary_domain.lower():
        return True

    if db is None:
        return False

    result = await db.execute(
        select(Domain).where(
            Domain.app_id == app.id,
            Domain.domain == host,
            Domain.verified.is_(True),
        )
    )
    return result.scalars().first() is not None


async def safe_redirect_url(
    db: AsyncSession | None, app: Application, redirect_url: str | None
) -> str:
    """Return redirect_url if it is allowed for this app, else the app's origin."""
    if await is_allowed_redirect(db, app, redirect_url):
        return redirect_url
    return app_base_url(app)
