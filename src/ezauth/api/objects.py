import uuid
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response

from ezauth.config import settings
from ezauth.dependencies import AppAuthDep, DbSession, RedisDep
from ezauth.schemas.objects import (
    BucketListResponse,
    BucketResponse,
    CreateBucketRequest,
    ObjectListResponse,
    ObjectResponse,
    ObjectStorageResponse,
)
from ezauth.services import objects as objects_svc
from ezauth.services.auth import AuthError

router = APIRouter()


def _get_s3(request: Request):
    return getattr(request.app.state, "s3", None)


def _require_admin(auth: AppAuthDep) -> None:
    if not auth.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")


# -- Buckets --

@router.post("/buckets", response_model=BucketResponse, status_code=201)
async def create_bucket(
    body: CreateBucketRequest,
    db: DbSession,
    auth: AppAuthDep,
):
    _require_admin(auth)
    try:
        bucket = await objects_svc.create_bucket(db, app_id=auth.app.id, name=body.name)
        return bucket
    except AuthError as e:
        if e.code == "bucket_exists":
            raise HTTPException(status_code=409, detail=e.message)
        raise HTTPException(status_code=400, detail=e.message)


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
        raise HTTPException(status_code=404, detail=e.message)


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
        raise HTTPException(status_code=404, detail=e.message)


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
    if auth.is_admin:
        if user_id is None:
            raise HTTPException(status_code=400, detail="user_id query param required for admin uploads")
        target_user_id = user_id
    else:
        target_user_id = auth.user_id

    content_type = request.headers.get("content-type", "application/octet-stream")
    data = await request.body()

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
        if e.code == "object_too_large":
            raise HTTPException(status_code=413, detail=e.message)
        if e.code == "storage_limit_exceeded":
            raise HTTPException(status_code=413, detail=e.message)
        if e.code == "not_found":
            raise HTTPException(status_code=404, detail=e.message)
        raise HTTPException(status_code=400, detail=e.message)


@router.get("/buckets/{bucket_id}/objects/{key:path}")
async def get_object(
    bucket_id: uuid.UUID,
    key: str,
    request: Request,
    db: DbSession,
    auth: AppAuthDep,
    user_id: uuid.UUID | None = Query(None),
):
    if auth.is_admin:
        if user_id is None:
            raise HTTPException(status_code=400, detail="user_id query param required for admin access")
        target_user_id = user_id
    else:
        target_user_id = auth.user_id

    s3 = _get_s3(request)
    try:
        obj, data = await objects_svc.get_object_data(
            db, s3,
            app_id=auth.app.id,
            bucket_id=bucket_id,
            user_id=target_user_id,
            key=key,
        )
        filename = key.rsplit("/", 1)[-1] if "/" in key else key
        return Response(
            content=data,
            media_type=obj.content_type,
            headers={"Content-Disposition": f'inline; filename="{quote(filename)}"'},
        )
    except AuthError as e:
        raise HTTPException(status_code=404, detail=e.message)


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
    if auth.is_admin:
        if user_id is None:
            raise HTTPException(status_code=400, detail="user_id query param required for admin access")
        target_user_id = user_id
    else:
        target_user_id = auth.user_id

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
        raise HTTPException(status_code=404, detail=e.message)


@router.get("/buckets/{bucket_id}/objects", response_model=ObjectListResponse)
async def list_objects(
    bucket_id: uuid.UUID,
    db: DbSession,
    auth: AppAuthDep,
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = Query(None),
    user_id: uuid.UUID | None = Query(None),
):
    # Users only see their own objects; admins see all or can filter by user_id
    if auth.is_admin:
        target_user_id = user_id  # None = all objects
    else:
        target_user_id = auth.user_id

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
        raise HTTPException(status_code=400, detail=e.message)
