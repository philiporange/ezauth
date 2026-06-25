"""Dashboard custom-domain management: list, add, CNAME verify (HTMX), delete.

All queries are scoped to applications the logged-in owner controls. The verify
endpoint swaps the full table row so the result keeps every column intact.
"""

import html
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ezauth.dashboard.auth import DashboardAuth, require_dashboard_auth
from ezauth.dashboard.scope import get_owned_app, owned_app_ids
from ezauth.dependencies import get_db
from ezauth.models.domain import Domain, DomainType
from ezauth.services.domains import verify_cname

router = APIRouter()
templates = Jinja2Templates(directory="src/ezauth/dashboard/templates")

CNAME_TARGET = "api.ezauth.org"


async def _get_owned_domain(
    db: AsyncSession, auth: DashboardAuth, domain_id: uuid.UUID
) -> Domain | None:
    query = select(Domain).where(Domain.id == domain_id)
    if not auth.is_super:
        query = query.where(Domain.app_id.in_(owned_app_ids(auth)))
    result = await db.execute(query)
    return result.scalars().first()


@router.get("", response_class=HTMLResponse)
async def list_domains(
    request: Request,
    app_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    auth: DashboardAuth = Depends(require_dashboard_auth),
):
    query = select(Domain).order_by(Domain.created_at.desc())
    if not auth.is_super:
        query = query.where(Domain.app_id.in_(owned_app_ids(auth)))
    if app_id:
        query = query.where(Domain.app_id == app_id)
    result = await db.execute(query)
    domains = result.scalars().all()
    return templates.TemplateResponse(
        "domains/list.html",
        {
            "request": request,
            "domains": domains,
            "app_id": app_id,
            "cname_target": CNAME_TARGET,
            "auth": auth,
        },
    )


@router.post("")
async def create_domain(
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: DashboardAuth = Depends(require_dashboard_auth),
):
    form = await request.form()
    domain_name = form.get("domain", "").strip().lower()
    app_id = form.get("app_id", "")
    domain_type = form.get("type", "primary")

    try:
        app_uuid = uuid.UUID(app_id)
        parsed_type = DomainType(domain_type)
    except ValueError:
        return RedirectResponse(url="/dashboard/domains", status_code=302)
    if not domain_name:
        return RedirectResponse(url=f"/dashboard/domains?app_id={app_id}", status_code=302)

    app = await get_owned_app(db, auth, app_uuid)
    if not app:
        return HTMLResponse("Not found", status_code=404)

    domain = Domain(
        app_id=app.id,
        domain=domain_name,
        type=parsed_type,
        cname_target=CNAME_TARGET,
    )
    db.add(domain)
    await db.flush()
    return RedirectResponse(url=f"/dashboard/domains?app_id={app_id}", status_code=302)


@router.post("/{domain_id}/verify")
async def verify_domain(
    domain_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: DashboardAuth = Depends(require_dashboard_auth),
):
    domain = await _get_owned_domain(db, auth, domain_id)
    if not domain:
        return HTMLResponse("Not found", status_code=404)

    verified = await verify_cname(domain.domain, domain.cname_target)
    domain_td = (
        f'<td><span class="mono">{html.escape(domain.domain)}</span> '
        f'<span class="badge">{domain.type.value}</span></td>'
    )
    if verified:
        domain.verified = True
        domain.verified_at = datetime.now(timezone.utc)
        await db.flush()
        return HTMLResponse(
            domain_td
            + '<td><span class="badge badge-success">Verified</span></td>'
            f'<td class="mono">{domain.cname_target}</td>'
            "<td></td>"
        )

    return HTMLResponse(
        domain_td
        + '<td><span class="badge badge-warning">Failed</span>'
        '<p class="hint" style="margin-top:6px">No matching DNS record found. '
        f"Make sure your CNAME points to <strong>{domain.cname_target}</strong> "
        "and DNS has propagated.</p></td>"
        f'<td class="mono">{domain.cname_target}</td>'
        f'<td class="row-actions"><button hx-post="/dashboard/domains/{domain.id}/verify" '
        f'hx-target="closest tr" hx-swap="innerHTML" class="btn btn-sm">Retry</button>'
        f'<button hx-post="/dashboard/domains/{domain.id}/delete" '
        f'hx-target="closest tr" hx-swap="outerHTML" '
        f'hx-confirm="Remove this domain?" class="btn-danger btn-sm">Remove</button></td>'
    )


@router.post("/{domain_id}/delete")
async def delete_domain(
    domain_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: DashboardAuth = Depends(require_dashboard_auth),
):
    domain = await _get_owned_domain(db, auth, domain_id)
    if not domain:
        return HTMLResponse("Not found", status_code=404)
    await db.delete(domain)
    await db.flush()
    return HTMLResponse("")
