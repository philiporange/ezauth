from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ezauth.dependencies import DbSession
from ezauth.models.application import Application
from ezauth.models.domain import Domain
from ezauth.services.sessions import build_jwks
from fastapi import Request

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
        result = await db.execute(select(Application).where(Application.id == app_id))
        app = result.scalars().first()
        if app:
            return build_jwks(app)

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
                return build_jwks(app)

    raise HTTPException(status_code=404, detail="Application not found for JWKS")
