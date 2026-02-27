import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ezauth.dashboard.auth import require_dashboard_auth
from ezauth.dependencies import get_db
from ezauth.models.bucket import Bucket
from ezauth.models.storage_object import StorageObject

router = APIRouter()
templates = Jinja2Templates(directory="src/ezauth/dashboard/templates")


def _parse_size(value: str | None) -> int | None:
    """Parse a size string into bytes, or return None if empty."""
    if not value or not value.strip():
        return None
    return int(value.strip())


@router.get("", response_class=HTMLResponse)
async def list_buckets(
    request: Request,
    app_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_dashboard_auth),
):
    query = select(Bucket).order_by(Bucket.created_at.desc())
    if app_id:
        query = query.where(Bucket.app_id == app_id)
    result = await db.execute(query)
    buckets = list(result.scalars().all())

    # Get usage per bucket
    bucket_usage = {}
    for b in buckets:
        usage_result = await db.execute(
            select(func.coalesce(func.sum(StorageObject.size_bytes), 0)).where(
                StorageObject.bucket_id == b.id
            )
        )
        bucket_usage[b.id] = usage_result.scalar() or 0

    return templates.TemplateResponse(
        "buckets/list.html",
        {"request": request, "buckets": buckets, "app_id": app_id, "bucket_usage": bucket_usage},
    )


@router.post("")
async def create_bucket(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_dashboard_auth),
):
    form = await request.form()
    app_id = form.get("app_id", "")
    name = form.get("name", "").strip()
    max_size_bytes = _parse_size(form.get("max_size_bytes"))
    max_size_bytes_per_user = _parse_size(form.get("max_size_bytes_per_user"))

    bucket = Bucket(
        app_id=uuid.UUID(app_id),
        name=name,
        max_size_bytes=max_size_bytes,
        max_size_bytes_per_user=max_size_bytes_per_user,
    )
    db.add(bucket)
    await db.flush()
    return RedirectResponse(url=f"/dashboard/buckets?app_id={app_id}", status_code=302)


@router.get("/{bucket_id}", response_class=HTMLResponse)
async def view_bucket(
    bucket_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_dashboard_auth),
):
    result = await db.execute(select(Bucket).where(Bucket.id == bucket_id))
    bucket = result.scalars().first()
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
        {"request": request, "bucket": bucket, "usage": usage, "obj_count": obj_count},
    )


@router.post("/{bucket_id}")
async def update_bucket(
    bucket_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_dashboard_auth),
):
    result = await db.execute(select(Bucket).where(Bucket.id == bucket_id))
    bucket = result.scalars().first()
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
    _=Depends(require_dashboard_auth),
):
    result = await db.execute(select(Bucket).where(Bucket.id == bucket_id))
    bucket = result.scalars().first()
    if not bucket:
        return HTMLResponse("Not found", status_code=404)
    app_id = bucket.app_id
    await db.delete(bucket)
    await db.flush()
    return RedirectResponse(url=f"/dashboard/buckets?app_id={app_id}", status_code=302)
