"""Application factory, lifespan and the service-level endpoints.

`create_app` wires the middleware stack (per-application CORS policy on the
outside, request correlation and logging inside it), the API, dashboard and
hosted routers, and the static mounts, whose directories are resolved from this
file so the service runs from any working directory.

The lifespan connects Redis, builds the S3 client and starts the background
cleanup task, then tears all three down again. `/health` probes Postgres and
Redis and answers 503 when either is unreachable, so a load balancer stops
sending traffic to an instance that cannot serve it; `/live` stays cheap for
liveness checks that must not depend on a backing service. Unhandled errors are
turned into a JSON body carrying the request id instead of a stack trace.
"""

import asyncio
import contextlib
import pathlib
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger
from sqlalchemy import select

from ezauth.config import settings
from ezauth.crypto import constant_time_compare
from ezauth.db.engine import async_session_factory, database_healthy, engine
from ezauth.db.redis import close_redis, init_redis, redis_healthy

_PACKAGE_DIR = pathlib.Path(__file__).parent
_DOCS_DIR = _PACKAGE_DIR / "docs"

_LOG_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
)

INTERNAL_SECRET_HEADER = "X-Internal-Secret"
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


def _format_log(record) -> str:
    """Append the request id to every line logged while handling a request."""
    suffix = " | request_id={extra[request_id]}" if "request_id" in record["extra"] else ""
    return _LOG_FORMAT + suffix + "\n{exception}"


logger.remove()
logger.add(sys.stderr, format=_format_log)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting ezAuth")
    await init_redis()
    logger.info("Redis connected")

    from ezauth.services.cleanup import cleanup_loop
    from ezauth.services.objects import create_s3_client

    app.state.s3 = create_s3_client()
    if app.state.s3:
        logger.info("S3 client initialized")

    app.state.cleanup_task = asyncio.create_task(cleanup_loop())

    yield

    app.state.cleanup_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await app.state.cleanup_task
    await close_redis()
    await engine.dispose()
    logger.info("ezAuth shut down")


def _internal_caller_allowed(request: Request) -> bool:
    """Internal endpoints answer only to loopback or a caller holding the shared secret."""
    secret = settings.internal_api_secret
    provided = request.headers.get(INTERNAL_SECRET_HEADER, "")
    if secret and provided and constant_time_compare(provided, secret):
        return True
    client_host = request.client.host if request.client else ""
    return client_host in _LOOPBACK_HOSTS


def create_app() -> FastAPI:
    app = FastAPI(title="ezAuth", version="0.1.0", lifespan=lifespan, docs_url=None)

    from ezauth.api.middleware import CORSPolicyMiddleware, RequestIDMiddleware

    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(CORSPolicyMiddleware)

    @app.exception_handler(Exception)
    async def unhandled_exception(request: Request, exc: Exception):
        request_id = getattr(request.state, "request_id", None)
        logger.exception("Unhandled error on {path}", path=request.url.path)
        return JSONResponse(
            {"error": "internal_error", "request_id": request_id},
            status_code=500,
            headers={"X-Request-ID": request_id} if request_id else None,
        )

    @app.get("/health")
    async def health():
        checks = {"database": await database_healthy(), "redis": await redis_healthy()}
        healthy = all(checks.values())
        return JSONResponse(
            {"status": "ok" if healthy else "unavailable", "checks": checks},
            status_code=200 if healthy else 503,
        )

    @app.get("/live")
    async def live():
        return {"status": "ok"}

    @app.get("/docs", include_in_schema=False)
    async def docs():
        return FileResponse(_DOCS_DIR / "index.html")

    @app.get("/internal/domain-check", include_in_schema=False)
    async def domain_check(request: Request, domain: str = Query(...)):
        """Called by Caddy on-demand TLS to verify a domain should get a cert."""
        from ezauth.models.domain import Domain

        if not _internal_caller_allowed(request):
            return JSONResponse({"error": "forbidden"}, status_code=403)

        async with async_session_factory() as db:
            result = await db.execute(
                select(Domain).where(Domain.domain == domain, Domain.verified.is_(True))
            )
            if result.scalars().first():
                return JSONResponse({"ok": True})
        return JSONResponse({"error": "unknown domain"}, status_code=404)

    from ezauth.api.router import api_router

    app.include_router(api_router)

    from ezauth.dashboard.router import dashboard_router

    app.include_router(dashboard_router)

    from ezauth.hosted.router import hosted_router

    app.include_router(hosted_router)

    app.mount(
        "/dashboard/static",
        StaticFiles(directory=_PACKAGE_DIR / "dashboard" / "static"),
        name="dashboard-static",
    )

    app.mount(
        "/auth/static",
        StaticFiles(directory=_PACKAGE_DIR / "hosted" / "static"),
        name="hosted-static",
    )

    return app


app = create_app()
