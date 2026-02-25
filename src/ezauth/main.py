import pathlib
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

from ezauth.db.engine import engine
from ezauth.db.redis import close_redis, init_redis

_DOCS_DIR = pathlib.Path(__file__).parent / "docs"


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting EZAuth")
    await init_redis()
    logger.info("Redis connected")
    yield
    await close_redis()
    await engine.dispose()
    logger.info("EZAuth shut down")


def create_app() -> FastAPI:
    app = FastAPI(title="EZAuth", version="0.1.0", lifespan=lifespan, docs_url=None)

    # CORS: In production, allowed_origins should be set per-application.
    # Using allow_origins=[] with allow_origin_regex to reflect the Origin
    # header while still supporting credentials.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[],
        allow_origin_regex=r"https?://.*",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from ezauth.api.middleware import RequestIDMiddleware

    app.add_middleware(RequestIDMiddleware)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/docs", include_in_schema=False)
    async def docs():
        return FileResponse(_DOCS_DIR / "index.html")

    from ezauth.api.router import api_router

    app.include_router(api_router)

    from ezauth.dashboard.router import dashboard_router

    app.include_router(dashboard_router)

    from ezauth.hosted.router import hosted_router

    app.include_router(hosted_router)

    app.mount(
        "/dashboard/static",
        StaticFiles(directory="src/ezauth/dashboard/static"),
        name="dashboard-static",
    )

    app.mount(
        "/auth/static",
        StaticFiles(directory="src/ezauth/hosted/static"),
        name="hosted-static",
    )

    return app


app = create_app()
