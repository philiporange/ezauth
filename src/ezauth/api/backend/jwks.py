"""Public JWKS endpoint.

Relying parties fetch the verification keys for an application here, resolved
either from an `app_id` query parameter or from the custom domain the request
arrived on. Every non-retired key is published, not just the active one, so a
key rotation does not invalidate tokens that were signed moments earlier.
"""

import uuid

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from ezauth.dependencies import DbSession
from ezauth.models.application import Application
from ezauth.models.domain import Domain
from ezauth.services.sessions import build_jwks

router = APIRouter()


@router.get("/.well-known/jwks.json")
async def get_jwks(
    request: Request,
    db: DbSession,
):
    """Public JWKS endpoint. Resolves app from Host header or query param."""
    # Try app_id query param first
    app_id = request.query_params.get("app_id")
    if app_id:
        try:
            app_uuid = uuid.UUID(app_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="app_id must be a UUID")
        result = await db.execute(select(Application).where(Application.id == app_uuid))
        app = result.scalars().first()
        if app:
            return await build_jwks(db, app)

    # Fall back to Host-based lookup
    host = request.headers.get("host", "").split(":")[0]
    if host:
        domain_result = await db.execute(
            select(Domain).where(Domain.domain == host, Domain.verified.is_(True))
        )
        domain = domain_result.scalars().first()
        if domain:
            app_result = await db.execute(
                select(Application).where(Application.id == domain.app_id)
            )
            app = app_result.scalars().first()
            if app:
                return await build_jwks(db, app)

    raise HTTPException(status_code=404, detail="Application not found for JWKS")
