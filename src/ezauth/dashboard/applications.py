"""Dashboard application management: list, create, settings editing, delete.

All queries are scoped to the logged-in owner via dashboard.scope. The settings
form covers primary domain, email branding, owner email, password auth toggle
and verification method (code vs link).
"""

import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ezauth.dashboard.auth import DashboardAuth, require_dashboard_auth, templates
from ezauth.dashboard.scope import (
    get_owned_app,
    get_owned_tenant,
    scope_applications,
    scope_tenants,
)
from ezauth.dependencies import get_db
from ezauth.models.application import Application, Environment
from ezauth.models.tenant import Tenant
from ezauth.models.user import User
from ezauth.services.keys import generate_jwk_pair, generate_publishable_key, generate_secret_key

router = APIRouter()


@router.get("", response_class=HTMLResponse)
async def list_applications(
    request: Request,
    tenant_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    auth: DashboardAuth = Depends(require_dashboard_auth),
):
    query = scope_applications(
        select(Application).order_by(Application.created_at.desc()), auth
    )
    if tenant_id:
        query = query.where(Application.tenant_id == tenant_id)
    result = await db.execute(query)
    apps = result.scalars().all()
    return templates.TemplateResponse(
        "applications/list.html",
        {"request": request, "apps": apps, "tenant_id": tenant_id, "auth": auth},
    )


@router.get("/new", response_class=HTMLResponse)
async def new_application(
    request: Request,
    tenant_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    auth: DashboardAuth = Depends(require_dashboard_auth),
):
    result = await db.execute(scope_tenants(select(Tenant).order_by(Tenant.name), auth))
    tenants = result.scalars().all()
    return templates.TemplateResponse(
        "applications/new.html",
        {"request": request, "tenants": tenants, "tenant_id": tenant_id, "auth": auth},
    )


@router.post("")
async def create_application(
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: DashboardAuth = Depends(require_dashboard_auth),
):
    form = await request.form()
    name = form.get("name", "").strip()
    tenant_id = form.get("tenant_id", "")
    env = form.get("environment", "dev")

    try:
        tenant_uuid = uuid.UUID(tenant_id)
        environment = Environment(env)
    except ValueError:
        return RedirectResponse(url="/dashboard/applications", status_code=302)
    if not name:
        return RedirectResponse(url="/dashboard/applications/new", status_code=302)

    tenant = await get_owned_tenant(db, auth, tenant_uuid)
    if not tenant:
        return HTMLResponse("Not found", status_code=404)

    pk = generate_publishable_key(env)
    sk = generate_secret_key(env)
    private_pem, kid, _jwk_pub = generate_jwk_pair()

    app = Application(
        tenant_id=tenant.id,
        name=name,
        environment=environment,
        publishable_key=pk,
        secret_key=sk,
        primary_domain=form.get("primary_domain", "").strip() or None,
        email_from_name=form.get("email_from_name", "").strip() or None,
        email_from_address=form.get("email_from_address", "").strip() or None,
        owner_email=(form.get("owner_email", "").strip() or auth.email).lower(),
        jwk_private_pem=private_pem,
        jwk_kid=kid,
    )
    db.add(app)
    await db.flush()
    return RedirectResponse(url=f"/dashboard/applications/{app.id}", status_code=302)


@router.get("/{app_id}", response_class=HTMLResponse)
async def view_application(
    app_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: DashboardAuth = Depends(require_dashboard_auth),
):
    app = await get_owned_app(db, auth, app_id)
    if not app:
        return HTMLResponse("Not found", status_code=404)

    user_count_result = await db.execute(
        select(func.count()).select_from(User).where(User.app_id == app.id)
    )
    user_count = user_count_result.scalar() or 0

    return templates.TemplateResponse(
        "applications/detail.html",
        {"request": request, "app": app, "user_count": user_count, "auth": auth},
    )


@router.post("/{app_id}")
async def update_application(
    app_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: DashboardAuth = Depends(require_dashboard_auth),
):
    app = await get_owned_app(db, auth, app_id)
    if not app:
        return HTMLResponse("Not found", status_code=404)

    form = await request.form()
    name = form.get("name", "").strip()
    if name:
        app.name = name
    app.primary_domain = form.get("primary_domain", "").strip() or None
    app.email_from_name = form.get("email_from_name", "").strip() or None
    app.email_from_address = form.get("email_from_address", "").strip() or None
    owner_email = form.get("owner_email", "").strip().lower()
    if owner_email:
        app.owner_email = owner_email
    app.passwords_enabled = form.get("passwords_enabled") == "on"
    verification_method = form.get("verification_method", "")
    if verification_method in ("code", "link"):
        app.verification_method = verification_method
    await db.flush()
    return RedirectResponse(url=f"/dashboard/applications/{app_id}", status_code=302)


@router.post("/{app_id}/delete")
async def delete_application(
    app_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: DashboardAuth = Depends(require_dashboard_auth),
):
    app = await get_owned_app(db, auth, app_id)
    if not app:
        return HTMLResponse("Not found", status_code=404)
    await db.delete(app)
    await db.flush()
    return RedirectResponse(url="/dashboard/applications", status_code=302)
