import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ezauth.dashboard.auth import require_dashboard_auth
from ezauth.dependencies import get_db
from ezauth.models.application import Application, Environment
from ezauth.models.tenant import Tenant
from ezauth.services.keys import generate_jwk_pair, generate_publishable_key, generate_secret_key

router = APIRouter()
templates = Jinja2Templates(directory="src/ezauth/dashboard/templates")


@router.get("", response_class=HTMLResponse)
async def list_applications(
    request: Request,
    tenant_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_dashboard_auth),
):
    query = select(Application).order_by(Application.created_at.desc())
    if tenant_id:
        query = query.where(Application.tenant_id == tenant_id)
    result = await db.execute(query)
    apps = result.scalars().all()
    return templates.TemplateResponse(
        "applications/list.html", {"request": request, "apps": apps, "tenant_id": tenant_id}
    )


@router.get("/new", response_class=HTMLResponse)
async def new_application(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_dashboard_auth),
):
    result = await db.execute(select(Tenant).order_by(Tenant.name))
    tenants = result.scalars().all()
    return templates.TemplateResponse(
        "applications/new.html", {"request": request, "tenants": tenants}
    )


@router.post("")
async def create_application(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_dashboard_auth),
):
    form = await request.form()
    name = form.get("name", "")
    tenant_id = form.get("tenant_id", "")
    env = form.get("environment", "dev")
    primary_domain = form.get("primary_domain", "") or None
    email_from_name = form.get("email_from_name", "") or None
    email_from_address = form.get("email_from_address", "") or None
    owner_email = form.get("owner_email", "") or None

    pk = generate_publishable_key(env)
    sk = generate_secret_key(env)
    private_pem, kid, _jwk_pub = generate_jwk_pair()

    app = Application(
        tenant_id=uuid.UUID(tenant_id),
        name=name,
        environment=Environment(env),
        publishable_key=pk,
        secret_key=sk,
        primary_domain=primary_domain,
        email_from_name=email_from_name,
        email_from_address=email_from_address,
        owner_email=owner_email,
        jwk_private_pem=private_pem,
        jwk_kid=kid,
    )
    db.add(app)
    await db.flush()
    return RedirectResponse(url="/dashboard/applications", status_code=302)


@router.get("/{app_id}", response_class=HTMLResponse)
async def view_application(
    app_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_dashboard_auth),
):
    result = await db.execute(select(Application).where(Application.id == app_id))
    app = result.scalars().first()
    if not app:
        return HTMLResponse("Not found", status_code=404)
    return templates.TemplateResponse(
        "applications/detail.html", {"request": request, "app": app}
    )
