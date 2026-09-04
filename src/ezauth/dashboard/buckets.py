"""Dashboard storage bucket management: list with usage, create, limits, delete.

All queries are scoped to applications the logged-in owner controls. Deleting a
bucket goes through the object storage service so that the stored payloads are
removed from S3 alongside the metadata rows, rather than being orphaned.
"""

import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ezauth.dashboard.auth import DashboardAuth, require_dashboard_auth, templates
from ezauth.dashboard.scope import get_owned_app, owned_app_ids
from ezauth.dependencies import get_db
from ezauth.models.bucket import Bucket
from ezauth.models.storage_object import StorageObject
from ezauth.services import objects as objects_svc
from ezauth.services.auth import AuthError

router = APIRouter()


def _parse_size(value: str | None) -> int | None:
    """Parse a size limit in bytes, treating anything not positive as unset.

    A zero or negative limit would compare as already exhausted against any
    usage, silently rejecting every upload to the bucket.
    """
    if not value or not value.strip():
        return None
    try:
        parsed = int(value.strip())
    except ValueError:
        return None
    return parsed if parsed > 0 else None


async def _get_owned_bucket(
    db: AsyncSession, auth: DashboardAuth, bucket_id: uuid.UUID
) -> Bucket | None:
    query = select(Bucket).where(Bucket.id == bucket_id)
    if not auth.is_super:
        query = query.where(Bucket.app_id.in_(owned_app_ids(auth)))
    result = await db.execute(query)
    return result.scalars().first()


@router.get("", response_class=HTMLResponse)
async def list_buckets(
    request: Request,
    app_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    auth: DashboardAuth = Depends(require_dashboard_auth),
):
    query = select(Bucket).order_by(Bucket.created_at.desc())
    if not auth.is_super:
        query = query.where(Bucket.app_id.in_(owned_app_ids(auth)))
    if app_id:
        query = query.where(Bucket.app_id == app_id)
    result = await db.execute(query)
    buckets = list(result.scalars().all())

    bucket_usage = {b.id: 0 for b in buckets}
    if buckets:
        usage_result = await db.execute(
            select(StorageObject.bucket_id, func.coalesce(func.sum(StorageObject.size_bytes), 0))
            .where(StorageObject.bucket_id.in_(list(bucket_usage)))
            .group_by(StorageObject.bucket_id)
        )
        bucket_usage.update(dict(usage_result.all()))

    return templates.TemplateResponse(
        "buckets/list.html",
        {
            "request": request,
            "buckets": buckets,
            "app_id": app_id,
            "bucket_usage": bucket_usage,
            "auth": auth,
        },
    )


@router.post("")
async def create_bucket(
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: DashboardAuth = Depends(require_dashboard_auth),
):
    form = await request.form()
    app_id = form.get("app_id", "")
    name = form.get("name", "").strip()

    try:
        app_uuid = uuid.UUID(app_id)
    except ValueError:
        return RedirectResponse(url="/dashboard/buckets", status_code=302)
    if not name:
        return RedirectResponse(url=f"/dashboard/buckets?app_id={app_id}", status_code=302)

    app = await get_owned_app(db, auth, app_uuid)
    if not app:
        return HTMLResponse("Not found", status_code=404)

    bucket = Bucket(
        app_id=app.id,
        name=name,
        max_size_bytes=_parse_size(form.get("max_size_bytes")),
        max_size_bytes_per_user=_parse_size(form.get("max_size_bytes_per_user")),
    )
    db.add(bucket)
    await db.flush()
    return RedirectResponse(url=f"/dashboard/buckets?app_id={app_id}", status_code=302)


@router.get("/{bucket_id}", response_class=HTMLResponse)
async def view_bucket(
    bucket_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: DashboardAuth = Depends(require_dashboard_auth),
):
    bucket = await _get_owned_bucket(db, auth, bucket_id)
    if not bucket:
        return HTMLResponse("Not found", status_code=404)

    usage_result = await db.execute(
        select(func.coalesce(func.sum(StorageObject.size_bytes), 0)).where(
            StorageObject.bucket_id == bucket.id
        )
    )
    usage = usage_result.scalar() or 0

    obj_count_result = await db.execute(
        select(func.count()).select_from(StorageObject).where(
            StorageObject.bucket_id == bucket.id
        )
    )
    obj_count = obj_count_result.scalar() or 0

    return templates.TemplateResponse(
        "buckets/detail.html",
        {
            "request": request,
            "bucket": bucket,
            "usage": usage,
            "obj_count": obj_count,
            "auth": auth,
        },
    )


@router.post("/{bucket_id}")
async def update_bucket(
    bucket_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: DashboardAuth = Depends(require_dashboard_auth),
):
    bucket = await _get_owned_bucket(db, auth, bucket_id)
    if not bucket:
        return HTMLResponse("Not found", status_code=404)

    form = await request.form()
    bucket.max_size_bytes = _parse_size(form.get("max_size_bytes"))
    bucket.max_size_bytes_per_user = _parse_size(form.get("max_size_bytes_per_user"))
    await db.flush()
    return RedirectResponse(url=f"/dashboard/buckets/{bucket_id}", status_code=302)


@router.post("/{bucket_id}/delete")
async def delete_bucket(
    bucket_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: DashboardAuth = Depends(require_dashboard_auth),
):
    bucket = await _get_owned_bucket(db, auth, bucket_id)
    if not bucket:
        return HTMLResponse("Not found", status_code=404)
    app_id = bucket.app_id
    try:
        await objects_svc.delete_bucket(
            db,
            getattr(request.app.state, "s3", None),
            app_id=app_id,
            bucket_id=bucket.id,
        )
    except AuthError as e:
        status = 503 if e.code in ("storage_unavailable", "storage_error") else 404
        return HTMLResponse(e.message, status_code=status)
    return RedirectResponse(url=f"/dashboard/buckets?app_id={app_id}", status_code=302)
