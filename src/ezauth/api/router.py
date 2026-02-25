from fastapi import APIRouter

from ezauth.api.frontend import (
    bots,
    challenges,
    signups,
    signins,
    verify,
    verify_code,
    sessions as fe_sessions,
    sso,
)
from ezauth.api.backend import users, sessions as be_sessions, jwks

api_router = APIRouter()

# Frontend routes (browser-facing, publishable_key auth)
api_router.include_router(challenges.router, prefix="/v1", tags=["frontend-auth"])
api_router.include_router(signups.router, prefix="/v1", tags=["frontend-auth"])
api_router.include_router(signins.router, prefix="/v1", tags=["frontend-auth"])
api_router.include_router(verify.router, prefix="/v1", tags=["frontend-auth"])
api_router.include_router(verify_code.router, prefix="/v1", tags=["frontend-auth"])
api_router.include_router(fe_sessions.router, prefix="/v1", tags=["frontend-sessions"])
api_router.include_router(sso.router, prefix="/v1", tags=["frontend-sso"])
api_router.include_router(bots.router, prefix="/v1", tags=["frontend-bots"])

# Backend routes (server-facing, secret_key auth)
api_router.include_router(users.router, prefix="/v1", tags=["backend-users"])
api_router.include_router(be_sessions.router, prefix="/v1", tags=["backend-sessions"])
api_router.include_router(jwks.router, tags=["backend-jwks"])
