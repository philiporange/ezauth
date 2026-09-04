"""HTTP routes for buckets and object storage.

Buckets are administered with the application secret key; objects are read and
written by end users, who are always scoped to their own user id. An admin
caller must name the target user explicitly, and that user is checked to belong
to the calling application before anything touches storage.

Uploads are size-capped twice: the declared ``Content-Length`` is rejected
before a byte is read, and the request stream is abandoned as soon as it
exceeds the cap, so an oversized body is never buffered. Downloads stream back
from S3 chunk by chunk and are always served as an attachment with
``X-Content-Type-Options: nosniff``, so a user-supplied content type cannot
render in this origin. Service errors carry a code that maps to a status here:
unconfigured storage answers 503 and a backend failure 502, rather than
reporting a success the store never saw.
"""

import re
import uuid
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from ezauth.config import settings
from ezauth.dependencies import AppAuthDep, DbSession, RedisDep
from ezauth.models.user import User
from ezauth.schemas.objects import (
    BucketListResponse,
    BucketResponse,
    CreateBucketRequest,
    ObjectListResponse,
    ObjectResponse,
    ObjectStorageResponse,
    UpdateBucketRequest,
)
from ezauth.services import objects as objects_svc
from ezauth.services.auth import AuthError

router = APIRouter()

_STATUS_BY_CODE = {
    "bucket_exists": 409,
    "invalid_content_type": 400,
    "invalid_cursor": 400,
    "invalid_key": 400,
    "invalid_limit": 400,
    "not_found": 404,
    "object_too_large": 413,
    "storage_error": 502,
    "storage_limit_exceeded": 413,
    "storage_unavailable": 503,
}

_UNSAFE_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9._-]+")


def _http_error(exc: AuthError) -> HTTPException:
    return HTTPException(status_code=_STATUS_BY_CODE.get(exc.code, 400), detail=exc.message)


def _get_s3(request: Request):
    return getattr(request.app.state, "s3", None)


def _require_admin(auth: AppAuthDep) -> None:
    if not auth.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")


async def _resolve_target_user(
    db: DbSession,
    auth: AppAuthDep,
    user_id: uuid.UUID | None,
    *,
    required: bool = True,
) -> uuid.UUID | None:
    """Return the user whose objects the caller may touch, validating admin input."""
    if not auth.is_admin:
        return auth.user_id

    if user_id is None:
        if required:
            raise HTTPException(
                status_code=400, detail="user_id query param required for admin access",
            )
        return None

    result = await db.execute(
        select(User.id).where(User.id == user_id, User.app_id == auth.app.id)
    )
    if result.scalar() is None:
        raise HTTPException(
            status_code=400, detail="user_id does not belong to this application",
        )
    return user_id


async def _read_capped_body(request: Request, max_bytes: int) -> bytes:
    """Read the request body, refusing anything over ``max_bytes`` without buffering it."""
    too_large = HTTPException(
        status_code=413, detail=f"Object too large (max {max_bytes} bytes)",
    )

    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            length = int(declared)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid Content-Length header")
        if length > max_bytes:
            raise too_large

    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > max_bytes:
            raise too_large
        chunks.append(chunk)
    return b"".join(chunks)


# -- Buckets --

@router.post("/buckets", response_model=BucketResponse, status_code=201)
async def create_bucket(
    body: CreateBucketRequest,
    db: DbSession,
    auth: AppAuthDep,
):
    _require_admin(auth)
    try:
        bucket = await objects_svc.create_bucket(
            db,
            app_id=auth.app.id,
            name=body.name,
            max_size_bytes=body.max_size_bytes,
            max_size_bytes_per_user=body.max_size_bytes_per_user,
        )
        return bucket
    except AuthError as e:
        raise _http_error(e)


@router.get("/buckets", response_model=BucketListResponse)
async def list_buckets(
    db: DbSession,
    auth: AppAuthDep,
):
    buckets, total = await objects_svc.list_buckets(db, app_id=auth.app.id)
    return BucketListResponse(
        buckets=[BucketResponse.model_validate(b) for b in buckets],
        total=total,
    )


@router.get("/buckets/storage", response_model=ObjectStorageResponse)
async def get_object_storage(
    db: DbSession,
    auth: AppAuthDep,
    redis: RedisDep,
):
    _require_admin(auth)
    used = await objects_svc.get_object_storage_usage(db, redis, app_id=auth.app.id)
    limit = settings.object_storage_limit_bytes
    return ObjectStorageResponse(
        used_bytes=used,
        limit_bytes=limit,
        used_percent=round((used / limit) * 100, 2) if limit > 0 else 0,
    )


@router.get("/buckets/{bucket_id}", response_model=BucketResponse)
async def get_bucket(
    bucket_id: uuid.UUID,
    db: DbSession,
    auth: AppAuthDep,
):
    try:
        bucket = await objects_svc.get_bucket(db, app_id=auth.app.id, bucket_id=bucket_id)
        return bucket
    except AuthError as e:
        raise _http_error(e)


@router.patch("/buckets/{bucket_id}", response_model=BucketResponse)
async def update_bucket(
    bucket_id: uuid.UUID,
    body: UpdateBucketRequest,
    db: DbSession,
    auth: AppAuthDep,
):
    _require_admin(auth)
    try:
        kwargs: dict = {}
        if "max_size_bytes" in body.model_fields_set:
            kwargs["max_size_bytes"] = body.max_size_bytes
        if "max_size_bytes_per_user" in body.model_fields_set:
            kwargs["max_size_bytes_per_user"] = body.max_size_bytes_per_user
        bucket = await objects_svc.update_bucket(
            db, app_id=auth.app.id, bucket_id=bucket_id, **kwargs
        )
        return bucket
    except AuthError as e:
        raise _http_error(e)


@router.delete("/buckets/{bucket_id}", status_code=204)
async def delete_bucket(
    bucket_id: uuid.UUID,
    db: DbSession,
    auth: AppAuthDep,
    request: Request,
):
    _require_admin(auth)
    s3 = _get_s3(request)
    try:
        await objects_svc.delete_bucket(db, s3, app_id=auth.app.id, bucket_id=bucket_id)
    except AuthError as e:
        raise _http_error(e)


# -- Objects --

@router.put("/buckets/{bucket_id}/objects/{key:path}")
async def put_object(
    bucket_id: uuid.UUID,
    key: str,
    request: Request,
    db: DbSession,
    auth: AppAuthDep,
    redis: RedisDep,
    user_id: uuid.UUID | None = Query(None),
):
    target_user_id = await _resolve_target_user(db, auth, user_id)

    content_type = request.headers.get("content-type", objects_svc.DEFAULT_CONTENT_TYPE)
    data = await _read_capped_body(request, settings.object_storage_max_object_bytes)

    s3 = _get_s3(request)
    try:
        obj = await objects_svc.put_object(
            db, redis, s3,
            app_id=auth.app.id,
            bucket_id=bucket_id,
            user_id=target_user_id,
            key=key,
            content_type=content_type,
            data=data,
        )
        return ObjectResponse.model_validate(obj)
    except AuthError as e:
        raise _http_error(e)


@router.get("/buckets/{bucket_id}/objects/{key:path}")
async def get_object(
    bucket_id: uuid.UUID,
    key: str,
    request: Request,
    db: DbSession,
    auth: AppAuthDep,
    user_id: uuid.UUID | None = Query(None),
):
    target_user_id = await _resolve_target_user(db, auth, user_id)

    s3 = _get_s3(request)
    try:
        obj, body = await objects_svc.open_object(
            db, s3,
            app_id=auth.app.id,
            bucket_id=bucket_id,
            user_id=target_user_id,
            key=key,
        )
    except AuthError as e:
        raise _http_error(e)

    return StreamingResponse(
        objects_svc.iter_object_body(body),
        media_type=obj.content_type,
        headers={
            "Content-Disposition": _attachment_disposition(key),
            "X-Content-Type-Options": "nosniff",
        },
    )


def _attachment_disposition(key: str) -> str:
    """Force a download, with an ASCII fallback alongside the UTF-8 filename."""
    filename = key.rsplit("/", 1)[-1] or "download"
    ascii_name = _UNSAFE_FILENAME_CHARS.sub("_", filename).strip("_") or "download"
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"


@router.delete("/buckets/{bucket_id}/objects/{key:path}", status_code=204)
async def delete_object(
    bucket_id: uuid.UUID,
    key: str,
    request: Request,
    db: DbSession,
    auth: AppAuthDep,
    redis: RedisDep,
    user_id: uuid.UUID | None = Query(None),
):
    target_user_id = await _resolve_target_user(db, auth, user_id)

    s3 = _get_s3(request)
    try:
        await objects_svc.delete_object(
            db, redis, s3,
            app_id=auth.app.id,
            bucket_id=bucket_id,
            user_id=target_user_id,
            key=key,
        )
    except AuthError as e:
        raise _http_error(e)


@router.get("/buckets/{bucket_id}/objects", response_model=ObjectListResponse)
async def list_objects(
    bucket_id: uuid.UUID,
    db: DbSession,
    auth: AppAuthDep,
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = Query(None),
    user_id: uuid.UUID | None = Query(None),
):
    # Users only see their own objects; admins see all or can filter by user_id.
    target_user_id = await _resolve_target_user(db, auth, user_id, required=False)

    try:
        objects, next_cursor = await objects_svc.list_objects(
            db,
            app_id=auth.app.id,
            bucket_id=bucket_id,
            user_id=target_user_id,
            limit=limit,
            cursor=cursor,
        )
        return ObjectListResponse(
            objects=[ObjectResponse.model_validate(o) for o in objects],
            next_cursor=next_cursor,
        )
    except AuthError as e:
        raise _http_error(e)
