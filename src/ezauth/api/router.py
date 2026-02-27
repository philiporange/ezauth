from fastapi import APIRouter

from ezauth.api import admin_auth, objects, tables
from ezauth.api.backend import jwks, oauth_config, users
from ezauth.api.backend import sessions as be_sessions
from ezauth.api.frontend import (
    bots,
    challenges,
    signins,
    signups,
    sso,
    verify,
    verify_code,
)
from ezauth.api.frontend import (
    oauth as fe_oauth,
)
from ezauth.api.frontend import (
    sessions as fe_sessions,
)

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
api_router.include_router(fe_oauth.router, prefix="/v1", tags=["frontend-oauth"])

# Admin auth routes (email magic link login)
api_router.include_router(admin_auth.router, prefix="/v1", tags=["admin-auth"])

# Backend routes (server-facing, secret_key auth)
api_router.include_router(users.router, prefix="/v1", tags=["backend-users"])
api_router.include_router(be_sessions.router, prefix="/v1", tags=["backend-sessions"])
api_router.include_router(jwks.router, tags=["backend-jwks"])
api_router.include_router(oauth_config.router, prefix="/v1", tags=["backend-oauth"])

# Unified auth routes (secret key or publishable key + session)
api_router.include_router(tables.router, prefix="/v1", tags=["tables"])
api_router.include_router(objects.router, prefix="/v1", tags=["objects"])
