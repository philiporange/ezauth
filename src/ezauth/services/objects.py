import asyncio
import base64
import json
import uuid

import boto3
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ezauth.config import settings
from ezauth.models.bucket import Bucket
from ezauth.models.storage_object import StorageObject
from ezauth.services.auth import AuthError


def create_s3_client():
    if not settings.s3_endpoint_url:
        return None
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key_id,
        aws_secret_access_key=settings.s3_secret_access_key,
        region_name=settings.s3_region,
    )


def _s3_key(app_id: uuid.UUID, bucket_id: uuid.UUID, user_id: uuid.UUID, key: str) -> str:
    return f"{app_id}/{bucket_id}/{user_id}/{key}"


# -- Bucket CRUD --

async def create_bucket(
    db: AsyncSession,
    *,
    app_id: uuid.UUID,
    name: str,
) -> Bucket:
    existing = await db.execute(
        select(Bucket).where(Bucket.app_id == app_id, Bucket.name == name)
    )
    if existing.scalars().first():
        raise AuthError(f"Bucket '{name}' already exists", code="bucket_exists")

    bucket = Bucket(app_id=app_id, name=name)
    db.add(bucket)
    await db.flush()
    return bucket


async def list_buckets(
    db: AsyncSession,
    *,
    app_id: uuid.UUID,
) -> tuple[list[Bucket], int]:
    count_q = select(func.count()).select_from(Bucket).where(Bucket.app_id == app_id)
    total = (await db.execute(count_q)).scalar() or 0

    q = select(Bucket).where(Bucket.app_id == app_id).order_by(Bucket.created_at.asc())
    result = await db.execute(q)
    buckets = list(result.scalars().all())
    return buckets, total


async def get_bucket(
    db: AsyncSession,
    *,
    app_id: uuid.UUID,
    bucket_id: uuid.UUID,
) -> Bucket:
    result = await db.execute(
        select(Bucket).where(Bucket.id == bucket_id, Bucket.app_id == app_id)
    )
    bucket = result.scalars().first()
    if bucket is None:
        raise AuthError("Bucket not found", code="not_found")
    return bucket


async def delete_bucket(
    db: AsyncSession,
    s3_client,
    *,
    app_id: uuid.UUID,
    bucket_id: uuid.UUID,
) -> None:
    bucket = await get_bucket(db, app_id=app_id, bucket_id=bucket_id)

    # Delete all S3 objects under this bucket prefix
    if s3_client:
        prefix = f"{app_id}/{bucket_id}/"
        await _delete_s3_prefix(s3_client, prefix)

    await db.delete(bucket)
    await db.flush()


async def _delete_s3_prefix(s3_client, prefix: str) -> None:
    s3_bucket = settings.s3_bucket_name

    def _do():
        paginator = s3_client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=s3_bucket, Prefix=prefix):
            objects = page.get("Contents", [])
            if objects:
                delete_keys = [{"Key": obj["Key"]} for obj in objects]
                s3_client.delete_objects(
                    Bucket=s3_bucket,
                    Delete={"Objects": delete_keys},
                )

    await asyncio.to_thread(_do)


# -- Object CRUD --

async def put_object(
    db: AsyncSession,
    redis,
    s3_client,
    *,
    app_id: uuid.UUID,
    bucket_id: uuid.UUID,
    user_id: uuid.UUID,
    key: str,
    content_type: str,
    data: bytes,
) -> StorageObject:
    size = len(data)

    if size > settings.object_storage_max_object_bytes:
        raise AuthError(
            f"Object too large ({size} bytes, max {settings.object_storage_max_object_bytes})",
            code="object_too_large",
        )

    # Check app-level storage limit
    await _check_object_storage(db, redis, app_id=app_id)

    # Ensure bucket exists
    await get_bucket(db, app_id=app_id, bucket_id=bucket_id)

    # Upload to S3
    s3_object_key = _s3_key(app_id, bucket_id, user_id, key)
    if s3_client:
        await asyncio.to_thread(
            s3_client.put_object,
            Bucket=settings.s3_bucket_name,
            Key=s3_object_key,
            Body=data,
            ContentType=content_type,
        )

    # Upsert DB record
    result = await db.execute(
        select(StorageObject).where(
            StorageObject.bucket_id == bucket_id,
            StorageObject.user_id == user_id,
            StorageObject.key == key,
        )
    )
    obj = result.scalars().first()
    if obj:
        obj.content_type = content_type
        obj.size_bytes = size
    else:
        obj = StorageObject(
            app_id=app_id,
            bucket_id=bucket_id,
            user_id=user_id,
            key=key,
            content_type=content_type,
            size_bytes=size,
        )
        db.add(obj)

    await db.flush()
    await db.refresh(obj)
    await _invalidate_object_storage_cache(redis, app_id=app_id)
    return obj


async def get_object_data(
    db: AsyncSession,
    s3_client,
    *,
    app_id: uuid.UUID,
    bucket_id: uuid.UUID,
    user_id: uuid.UUID,
    key: str,
) -> tuple[StorageObject, bytes]:
    result = await db.execute(
        select(StorageObject).where(
            StorageObject.bucket_id == bucket_id,
            StorageObject.user_id == user_id,
            StorageObject.key == key,
            StorageObject.app_id == app_id,
        )
    )
    obj = result.scalars().first()
    if obj is None:
        raise AuthError("Object not found", code="not_found")

    s3_object_key = _s3_key(app_id, bucket_id, user_id, key)
    if s3_client:
        response = await asyncio.to_thread(
            s3_client.get_object,
            Bucket=settings.s3_bucket_name,
            Key=s3_object_key,
        )
        data = await asyncio.to_thread(response["Body"].read)
    else:
        data = b""

    return obj, data


async def delete_object(
    db: AsyncSession,
    redis,
    s3_client,
    *,
    app_id: uuid.UUID,
    bucket_id: uuid.UUID,
    user_id: uuid.UUID,
    key: str,
) -> None:
    result = await db.execute(
        select(StorageObject).where(
            StorageObject.bucket_id == bucket_id,
            StorageObject.user_id == user_id,
            StorageObject.key == key,
            StorageObject.app_id == app_id,
        )
    )
    obj = result.scalars().first()
    if obj is None:
        raise AuthError("Object not found", code="not_found")

    s3_object_key = _s3_key(app_id, bucket_id, user_id, key)
    if s3_client:
        await asyncio.to_thread(
            s3_client.delete_object,
            Bucket=settings.s3_bucket_name,
            Key=s3_object_key,
        )

    await db.delete(obj)
    await db.flush()
    await _invalidate_object_storage_cache(redis, app_id=app_id)


async def list_objects(
    db: AsyncSession,
    *,
    app_id: uuid.UUID,
    bucket_id: uuid.UUID,
    user_id: uuid.UUID | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> tuple[list[StorageObject], str | None]:
    q = select(StorageObject).where(
        StorageObject.bucket_id == bucket_id,
        StorageObject.app_id == app_id,
    )
    if user_id is not None:
        q = q.where(StorageObject.user_id == user_id)

    q = q.order_by(StorageObject.key.asc(), StorageObject.id.asc())

    if cursor:
        cursor_data = _decode_cursor(cursor)
        cursor_id = uuid.UUID(cursor_data["id"])
        q = q.where(StorageObject.id > cursor_id)

    q = q.limit(limit + 1)
    result = await db.execute(q)
    objects = list(result.scalars().all())

    next_cursor = None
    if len(objects) > limit:
        objects = objects[:limit]
        last = objects[-1]
        next_cursor = _encode_cursor(str(last.id))

    return objects, next_cursor


# -- Storage tracking --

async def get_object_storage_usage(
    db: AsyncSession,
    redis,
    *,
    app_id: uuid.UUID,
) -> int:
    cache_key = f"object_storage:{app_id}"
    cached = await redis.get(cache_key)
    if cached is not None:
        return int(cached)

    result = await db.execute(
        select(func.coalesce(func.sum(StorageObject.size_bytes), 0)).where(
            StorageObject.app_id == app_id
        )
    )
    size = result.scalar() or 0
    await redis.set(cache_key, str(size), ex=60)
    return size


async def _check_object_storage(
    db: AsyncSession,
    redis,
    *,
    app_id: uuid.UUID,
) -> None:
    used = await get_object_storage_usage(db, redis, app_id=app_id)
    limit = settings.object_storage_limit_bytes
    if used >= limit:
        raise AuthError(
            f"Object storage limit exceeded ({used} / {limit} bytes)",
            code="storage_limit_exceeded",
        )


async def _invalidate_object_storage_cache(redis, *, app_id: uuid.UUID) -> None:
    cache_key = f"object_storage:{app_id}"
    await redis.delete(cache_key)


def _encode_cursor(value: str) -> str:
    payload = json.dumps({"id": value})
    return base64.urlsafe_b64encode(payload.encode()).decode()


def _decode_cursor(cursor: str) -> dict:
    try:
        payload = base64.urlsafe_b64decode(cursor.encode()).decode()
        data = json.loads(payload)
        if "id" not in data:
            raise ValueError
        return data
    except Exception:
        raise AuthError("Invalid cursor", code="invalid_cursor")
