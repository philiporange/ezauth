"""HTTP middleware: request correlation, request logging and CORS policy.

`RequestIDMiddleware` stamps every request with a UUID, binds it into the
loguru context so that every log line emitted while handling the request
carries it, logs a one-line summary with the status and duration, and returns
the id in `X-Request-ID` so a client can quote it in a bug report.

`CORSPolicyMiddleware` replaces a blanket origin reflector. Dashboard and
internal routes accept only the origins listed in
`settings.dashboard_allowed_origin_list`. Public API routes accept an origin
only when some application claims it, either in its `allowed_origins` array or
as its `primary_domain`; the lookup hits Postgres once and is then cached in
Redis for `_ORIGIN_CACHE_TTL` seconds. Anything else gets no CORS headers at
all, so the browser refuses to expose the response. Preflight requests are
answered here rather than reaching the router, and every response varies on
`Origin` so a shared cache cannot serve one site's response to another.
"""

import time
import uuid

from fastapi import Request, Response
from loguru import logger
from sqlalchemy import func, select
from starlette.middleware.base import BaseHTTPMiddleware

from ezauth.config import settings
from ezauth.db.engine import async_session_factory
from ezauth.db.redis import get_redis
from ezauth.models.application import Application

_ORIGIN_CACHE_PREFIX = "cors:origin:"
_ORIGIN_CACHE_TTL = 60
_PREFLIGHT_MAX_AGE = "600"
_MAX_ORIGIN_LENGTH = 255
_ALLOWED_METHODS = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
_DEFAULT_ALLOWED_HEADERS = "Authorization, Content-Type, X-Publishable-Key, X-CSRF-Token"
_PRIVATE_PATH_PREFIXES = ("/dashboard", "/internal")


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        started = time.perf_counter()
        with logger.contextualize(request_id=request_id):
            response: Response = await call_next(request)
            duration_ms = (time.perf_counter() - started) * 1000
            logger.info(
                "{method} {path} -> {status} in {duration:.1f}ms",
                method=request.method,
                path=request.url.path,
                status=response.status_code,
                duration=duration_ms,
            )
        response.headers["X-Request-ID"] = request_id
        return response


def _vary_on_origin(response: Response) -> None:
    existing = response.headers.get("Vary")
    if not existing:
        response.headers["Vary"] = "Origin"
    elif "origin" not in existing.lower():
        response.headers["Vary"] = f"{existing}, Origin"


async def _application_claims_origin(origin: str) -> bool:
    """Whether any application lists this origin or owns its hostname."""
    host = origin.split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0].lower()
    async with async_session_factory() as db:
        result = await db.execute(
            select(Application.id)
            .where(
                (Application.allowed_origins.any(origin))
                | (func.lower(Application.primary_domain) == host)
            )
            .limit(1)
        )
        return result.first() is not None


async def _origin_allowed_for_api(origin: str) -> bool:
    cache_key = _ORIGIN_CACHE_PREFIX + origin
    redis = None
    try:
        redis = get_redis()
        cached = await redis.get(cache_key)
    except Exception:
        cached = None
    if cached is not None:
        return cached == "1"

    allowed = await _application_claims_origin(origin)
    if redis is not None:
        try:
            await redis.setex(cache_key, _ORIGIN_CACHE_TTL, "1" if allowed else "0")
        except Exception:
            logger.warning("Could not cache the CORS decision for {origin}", origin=origin)
    return allowed


async def origin_allowed(path: str, origin: str) -> bool:
    """Whether this origin may make credentialed requests to this path."""
    if not origin or origin == "null" or len(origin) > _MAX_ORIGIN_LENGTH:
        return False
    if path.startswith(_PRIVATE_PATH_PREFIXES):
        return origin in settings.dashboard_allowed_origin_list
    return await _origin_allowed_for_api(origin)


class CORSPolicyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        origin = request.headers.get("origin", "")
        is_preflight = (
            request.method == "OPTIONS" and "access-control-request-method" in request.headers
        )
        allowed = bool(origin) and await origin_allowed(request.url.path, origin)

        if is_preflight:
            response = Response(status_code=204 if allowed else 403)
        else:
            response = await call_next(request)

        _vary_on_origin(response)
        if not allowed:
            return response

        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Expose-Headers"] = "X-Request-ID"
        if is_preflight:
            requested_headers = request.headers.get("access-control-request-headers")
            response.headers["Access-Control-Allow-Methods"] = _ALLOWED_METHODS
            response.headers["Access-Control-Allow-Headers"] = (
                requested_headers or _DEFAULT_ALLOWED_HEADERS
            )
            response.headers["Access-Control-Max-Age"] = _PREFLIGHT_MAX_AGE
        return response
