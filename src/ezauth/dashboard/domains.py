"""Dashboard custom-domain management: list, add, CNAME verify (HTMX), delete.

All queries are scoped to applications the logged-in owner controls. The verify
endpoint swaps the full table row so the result keeps every column intact.

Hostnames are globally unique, so adding one that already exists is handled
rather than left to raise. A hostname that another application has already
verified is refused with an explanation. An unverified claim confers nothing —
verification still requires a CNAME the claimant cannot forge — so it is
transferred to the requesting application instead of blocking it forever, which
stops a squatter from parking a hostname its real owner needs.
"""

import html
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ezauth.dashboard.auth import DashboardAuth, require_dashboard_auth, templates
from ezauth.dashboard.scope import get_owned_app, owned_app_ids
from ezauth.dependencies import get_db
from ezauth.models.domain import Domain, DomainType
from ezauth.services.domains import verify_cname

router = APIRouter()

CNAME_TARGET = "api.ezauth.org"


async def _get_owned_domain(
    db: AsyncSession, auth: DashboardAuth, domain_id: uuid.UUID
) -> Domain | None:
    query = select(Domain).where(Domain.id == domain_id)
    if not auth.is_super:
        query = query.where(Domain.app_id.in_(owned_app_ids(auth)))
    result = await db.execute(query)
    return result.scalars().first()


async def _render_list(
    request: Request,
    db: AsyncSession,
    auth: DashboardAuth,
    app_id: uuid.UUID | None,
    error: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    query = select(Domain).order_by(Domain.created_at.desc())
    if not auth.is_super:
        query = query.where(Domain.app_id.in_(owned_app_ids(auth)))
    if app_id:
        query = query.where(Domain.app_id == app_id)
    result = await db.execute(query)
    return templates.TemplateResponse(
        "domains/list.html",
        {
            "request": request,
            "domains": result.scalars().all(),
            "app_id": app_id,
            "cname_target": CNAME_TARGET,
            "error": error,
            "auth": auth,
        },
        status_code=status_code,
    )


@router.get("", response_class=HTMLResponse)
async def list_domains(
    request: Request,
    app_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    auth: DashboardAuth = Depends(require_dashboard_auth),
):
    return await _render_list(request, db, auth, app_id)


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

    existing = (
        await db.execute(select(Domain).where(Domain.domain == domain_name))
    ).scalars().first()
    if existing is not None:
        if existing.app_id == app.id:
            return RedirectResponse(
                url=f"/dashboard/domains?app_id={app_id}", status_code=302
            )
        if existing.verified:
            return await _render_list(
                request,
                db,
                auth,
                app_uuid,
                error=(
                    f"{domain_name} is already verified by another application. "
                    "Remove it there before adding it here."
                ),
                status_code=409,
            )
        existing.app_id = app.id
        existing.type = parsed_type
        existing.cname_target = CNAME_TARGET
        existing.verified_at = None
        await db.flush()
        return RedirectResponse(url=f"/dashboard/domains?app_id={app_id}", status_code=302)

    db.add(
        Domain(
            app_id=app.id,
            domain=domain_name,
            type=parsed_type,
            cname_target=CNAME_TARGET,
        )
    )
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        return await _render_list(
            request,
            db,
            auth,
            app_uuid,
            error=f"{domain_name} was claimed by another application a moment ago.",
            status_code=409,
        )
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
    target = html.escape(domain.cname_target or "")
    domain_td = (
        f'<td><span class="mono">{html.escape(domain.domain)}</span> '
        f'<span class="badge">{html.escape(domain.type.value)}</span></td>'
    )
    if verified:
        domain.verified = True
        domain.verified_at = datetime.now(timezone.utc)
        await db.flush()
        return HTMLResponse(
            domain_td
            + '<td><span class="badge badge-success">Verified</span></td>'
            f'<td class="mono">{target}</td>'
            "<td></td>"
        )

    return HTMLResponse(
        domain_td
        + '<td><span class="badge badge-warning">Failed</span>'
        '<p class="hint" style="margin-top:6px">No matching DNS record found. '
        f"Make sure your CNAME points to <strong>{target}</strong> "
        "and DNS has propagated.</p></td>"
        f'<td class="mono">{target}</td>'
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
