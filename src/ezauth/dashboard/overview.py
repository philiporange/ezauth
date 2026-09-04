"""Dashboard overview page: scoped counts of tenants, apps, users and storage."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ezauth.dashboard.auth import DashboardAuth, require_dashboard_auth, templates
from ezauth.dashboard.scope import owned_app_ids, scope_applications, scope_tenants
from ezauth.dependencies import get_db
from ezauth.models.application import Application
from ezauth.models.storage_object import StorageObject
from ezauth.models.tenant import Tenant
from ezauth.models.user import User

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def overview(
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: DashboardAuth = Depends(require_dashboard_auth),
):
    tenant_count = (
        await db.execute(
            scope_tenants(select(func.count()).select_from(Tenant), auth)
        )
    ).scalar() or 0

    app_query = scope_applications(
        select(Application).order_by(Application.created_at.desc()), auth
    )
    apps = (await db.execute(app_query)).scalars().all()

    user_query = select(func.count()).select_from(User)
    storage_query = select(func.coalesce(func.sum(StorageObject.size_bytes), 0))
    if not auth.is_super:
        user_query = user_query.where(User.app_id.in_(owned_app_ids(auth)))
        storage_query = storage_query.where(StorageObject.app_id.in_(owned_app_ids(auth)))
    user_count = (await db.execute(user_query)).scalar() or 0
    storage_bytes = (await db.execute(storage_query)).scalar() or 0

    return templates.TemplateResponse(
        "overview.html",
        {
            "request": request,
            "tenant_count": tenant_count,
            "apps": apps,
            "user_count": user_count,
            "storage_bytes": storage_bytes,
            "auth": auth,
        },
    )
