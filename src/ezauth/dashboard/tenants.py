import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ezauth.dashboard.auth import require_dashboard_auth
from ezauth.dependencies import get_db
from ezauth.models.tenant import Tenant

router = APIRouter()
templates = Jinja2Templates(directory="src/ezauth/dashboard/templates")


@router.get("", response_class=HTMLResponse)
async def list_tenants(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_dashboard_auth),
):
    result = await db.execute(select(Tenant).order_by(Tenant.created_at.desc()))
    tenants = result.scalars().all()
    return templates.TemplateResponse(
        "tenants/list.html", {"request": request, "tenants": tenants}
    )


@router.get("/new", response_class=HTMLResponse)
async def new_tenant(request: Request, _=Depends(require_dashboard_auth)):
    return templates.TemplateResponse("tenants/new.html", {"request": request})


@router.post("")
async def create_tenant(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_dashboard_auth),
):
    form = await request.form()
    name = form.get("name", "")
    tenant = Tenant(name=name)
    db.add(tenant)
    await db.flush()
    return RedirectResponse(url="/dashboard/tenants", status_code=302)


@router.get("/{tenant_id}", response_class=HTMLResponse)
async def view_tenant(
    tenant_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_dashboard_auth),
):
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalars().first()
    if not tenant:
        return HTMLResponse("Not found", status_code=404)
    return templates.TemplateResponse(
        "tenants/detail.html", {"request": request, "tenant": tenant}
    )
