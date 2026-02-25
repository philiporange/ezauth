import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ezauth.dashboard.auth import require_dashboard_auth
from ezauth.dependencies import get_db
from ezauth.models.domain import Domain, DomainType
from ezauth.services.domains import verify_cname

router = APIRouter()
templates = Jinja2Templates(directory="src/ezauth/dashboard/templates")


@router.get("", response_class=HTMLResponse)
async def list_domains(
    request: Request,
    app_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_dashboard_auth),
):
    query = select(Domain).order_by(Domain.created_at.desc())
    if app_id:
        query = query.where(Domain.app_id == app_id)
    result = await db.execute(query)
    domains = result.scalars().all()
    return templates.TemplateResponse(
        "domains/list.html", {"request": request, "domains": domains, "app_id": app_id}
    )


@router.post("")
async def create_domain(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_dashboard_auth),
):
    form = await request.form()
    domain_name = form.get("domain", "")
    app_id = form.get("app_id", "")
    domain_type = form.get("type", "primary")

    cname_target = "auth.ezauth.org"

    domain = Domain(
        app_id=uuid.UUID(app_id),
        domain=domain_name,
        type=DomainType(domain_type),
        cname_target=cname_target,
    )
    db.add(domain)
    await db.flush()
    return RedirectResponse(url=f"/dashboard/domains?app_id={app_id}", status_code=302)


@router.post("/{domain_id}/verify")
async def verify_domain(
    domain_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_dashboard_auth),
):
    result = await db.execute(select(Domain).where(Domain.id == domain_id))
    domain = result.scalars().first()
    if not domain:
        return HTMLResponse("Not found", status_code=404)

    verified = await verify_cname(domain.domain, domain.cname_target)
    if verified:
        domain.verified = True
        domain.verified_at = datetime.now(timezone.utc)
        await db.flush()
        return HTMLResponse('<span class="badge bg-success">Verified</span>')

    return HTMLResponse('<span class="badge bg-warning">CNAME not found</span>')
