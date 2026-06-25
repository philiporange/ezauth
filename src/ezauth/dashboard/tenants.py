"""Dashboard tenant management: list, create, rename, delete.

All queries are scoped to the logged-in owner via dashboard.scope; tenants
created here are stamped with the creator's email as owner_email.
"""

import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ezauth.dashboard.auth import DashboardAuth, require_dashboard_auth
from ezauth.dashboard.scope import get_owned_tenant, scope_applications, scope_tenants
from ezauth.dependencies import get_db
from ezauth.models.application import Application
from ezauth.models.tenant import Tenant
from ezauth.models.user import User

router = APIRouter()
templates = Jinja2Templates(directory="src/ezauth/dashboard/templates")


@router.get("", response_class=HTMLResponse)
async def list_tenants(
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: DashboardAuth = Depends(require_dashboard_auth),
):
    query = scope_tenants(select(Tenant).order_by(Tenant.created_at.desc()), auth)
    result = await db.execute(query)
    tenants = result.scalars().all()

    app_counts = {}
    if tenants:
        counts = await db.execute(
            select(Application.tenant_id, func.count())
            .where(Application.tenant_id.in_([t.id for t in tenants]))
            .group_by(Application.tenant_id)
        )
        app_counts = dict(counts.all())

    return templates.TemplateResponse(
        "tenants/list.html",
        {"request": request, "tenants": tenants, "app_counts": app_counts, "auth": auth},
    )


@router.post("")
async def create_tenant(
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: DashboardAuth = Depends(require_dashboard_auth),
):
    form = await request.form()
    name = form.get("name", "").strip()
    if not name:
        return RedirectResponse(url="/dashboard/tenants", status_code=302)
    tenant = Tenant(name=name, owner_email=auth.email)
    db.add(tenant)
    await db.flush()
    return RedirectResponse(url=f"/dashboard/tenants/{tenant.id}", status_code=302)


@router.get("/{tenant_id}", response_class=HTMLResponse)
async def view_tenant(
    tenant_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: DashboardAuth = Depends(require_dashboard_auth),
):
    tenant = await get_owned_tenant(db, auth, tenant_id)
    if not tenant:
        return HTMLResponse("Not found", status_code=404)

    apps_query = scope_applications(
        select(Application)
        .where(Application.tenant_id == tenant.id)
        .order_by(Application.created_at.desc()),
        auth,
    )
    apps_result = await db.execute(apps_query)
    apps = apps_result.scalars().all()

    user_counts = {}
    if apps:
        counts = await db.execute(
            select(User.app_id, func.count())
            .where(User.app_id.in_([a.id for a in apps]))
            .group_by(User.app_id)
        )
        user_counts = dict(counts.all())

    return templates.TemplateResponse(
        "tenants/detail.html",
        {
            "request": request,
            "tenant": tenant,
            "apps": apps,
            "user_counts": user_counts,
            "auth": auth,
        },
    )


@router.post("/{tenant_id}")
async def update_tenant(
    tenant_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: DashboardAuth = Depends(require_dashboard_auth),
):
    tenant = await get_owned_tenant(db, auth, tenant_id)
    if not tenant:
        return HTMLResponse("Not found", status_code=404)
    form = await request.form()
    name = form.get("name", "").strip()
    if name:
        tenant.name = name
    await db.flush()
    return RedirectResponse(url=f"/dashboard/tenants/{tenant_id}", status_code=302)


@router.post("/{tenant_id}/delete")
async def delete_tenant(
    tenant_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: DashboardAuth = Depends(require_dashboard_auth),
):
    tenant = await get_owned_tenant(db, auth, tenant_id)
    if not tenant:
        return HTMLResponse("Not found", status_code=404)
    await db.delete(tenant)
    await db.flush()
    return RedirectResponse(url="/dashboard/tenants", status_code=302)
