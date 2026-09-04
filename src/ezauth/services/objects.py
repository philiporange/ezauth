"""Per-application object storage: buckets, object metadata and S3 payloads.

Buckets and object metadata live in Postgres; the payloads live in a single S3
bucket under an ``app/bucket/user/key`` prefix. Every entry point requires a
configured S3 client and refuses the request outright when there is none, so a
misconfigured deployment cannot silently accept uploads it never stores.

Writes are ordered database-first: the metadata row is upserted on the
``(bucket, user, key)`` unique constraint and flushed, then the payload is sent
to S3, so a failed upload rolls back with the request transaction and leaves no
orphaned row. Deletes run in the same order for the same reason. Quota checks
take a row lock on the bucket before comparing projected usage — current usage
plus the delta this write introduces — against the app, bucket and per-user
limits, so concurrent uploads queue instead of all admitting themselves against
the same stale figure. Listing is keyset paginated on ``(key, id)``, matching
the sort order exactly so no object is skipped or repeated.
"""

import asyncio
import base64
import json
import re
import uuid
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from sqlalchemy import func, select, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ezauth.config import settings
from ezauth.models.bucket import Bucket
from ezauth.models.storage_object import StorageObject
from ezauth.services.auth import AuthError

# -- Constants --

MAX_OBJECT_KEY_LENGTH = 1024
MAX_CONTENT_TYPE_LENGTH = 255
DEFAULT_CONTENT_TYPE = "application/octet-stream"
DOWNLOAD_CHUNK_BYTES = 64 * 1024

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_NOT_FOUND_S3_CODES = {"NoSuchKey", "NoSuchBucket", "404"}


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


def _require_s3(s3_client) -> None:
    if s3_client is None:
        raise AuthError("Object storage is not configured", code="storage_unavailable")
    if not settings.s3_bucket_name:
        raise AuthError("Object storage is not configured", code="storage_unavailable")


def _storage_failure(exc: Exception) -> AuthError:
    """Translate a botocore failure into a service error the API can map to a status."""
    if isinstance(exc, ClientError):
        code = str(exc.response.get("Error", {}).get("Code", ""))
        if code in _NOT_FOUND_S3_CODES:
            return AuthError("Object not found", code="not_found")
    return AuthError("Object storage request failed", code="storage_error")


def _validate_object_key(key: str) -> str:
    """Reject keys that would escape their prefix, exceed the column, or hide characters."""
    if not key:
        raise AuthError("Object key must not be empty", code="invalid_key")
    if len(key) > MAX_OBJECT_KEY_LENGTH:
        raise AuthError(
            f"Object key must be at most {MAX_OBJECT_KEY_LENGTH} characters",
            code="invalid_key",
        )
    if _CONTROL_CHARS.search(key):
        raise AuthError("Object key must not contain control characters", code="invalid_key")
    if key.startswith("/"):
        raise AuthError("Object key must not start with '/'", code="invalid_key")
    for segment in key.split("/"):
        if segment == "":
            raise AuthError(
                "Object key must not contain empty path segments", code="invalid_key",
            )
        if segment in (".", ".."):
            raise AuthError(
                "Object key must not contain relative path segments", code="invalid_key",
            )
    return key


def _validate_content_type(content_type: str | None) -> str:
    value = (content_type or "").strip() or DEFAULT_CONTENT_TYPE
    if len(value) > MAX_CONTENT_TYPE_LENGTH:
        raise AuthError(
            f"Content type must be at most {MAX_CONTENT_TYPE_LENGTH} characters",
            code="invalid_content_type",
        )
    if _CONTROL_CHARS.search(value):
        raise AuthError(
            "Content type must not contain control characters", code="invalid_content_type",
        )
    return value


# -- Bucket CRUD --

async def create_bucket(
    db: AsyncSession,
    *,
    app_id: uuid.UUID,
    name: str,
    max_size_bytes: int | None = None,
    max_size_bytes_per_user: int | None = None,
) -> Bucket:
    existing = await db.execute(
        select(Bucket).where(Bucket.app_id == app_id, Bucket.name == name)
    )
    if existing.scalars().first():
        raise AuthError(f"Bucket '{name}' already exists", code="bucket_exists")

    _validate_bucket_limit("max_size_bytes", max_size_bytes)
    _validate_bucket_limit("max_size_bytes_per_user", max_size_bytes_per_user)

    bucket = Bucket(
        app_id=app_id,
        name=name,
        max_size_bytes=max_size_bytes,
        max_size_bytes_per_user=max_size_bytes_per_user,
    )
    db.add(bucket)
    await db.flush()
    return bucket


def _validate_bucket_limit(field: str, value: int | None) -> None:
    if value is not None and value <= 0:
        raise AuthError(f"{field} must be greater than zero", code="invalid_limit")


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


async def _lock_bucket(
    db: AsyncSession,
    *,
    app_id: uuid.UUID,
    bucket_id: uuid.UUID,
) -> Bucket:
    """Load the bucket with a row lock so quota checks serialise against each other."""
    result = await db.execute(
        select(Bucket)
        .where(Bucket.id == bucket_id, Bucket.app_id == app_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    bucket = result.scalars().first()
    if bucket is None:
        raise AuthError("Bucket not found", code="not_found")
    return bucket


async def update_bucket(
    db: AsyncSession,
    *,
    app_id: uuid.UUID,
    bucket_id: uuid.UUID,
    max_size_bytes: int | None = ...,
    max_size_bytes_per_user: int | None = ...,
) -> Bucket:
    bucket = await get_bucket(db, app_id=app_id, bucket_id=bucket_id)
    if max_size_bytes is not ...:
        _validate_bucket_limit("max_size_bytes", max_size_bytes)
        bucket.max_size_bytes = max_size_bytes
    if max_size_bytes_per_user is not ...:
        _validate_bucket_limit("max_size_bytes_per_user", max_size_bytes_per_user)
        bucket.max_size_bytes_per_user = max_size_bytes_per_user
    await db.flush()
    await db.refresh(bucket)
    return bucket


async def delete_bucket(
    db: AsyncSession,
    s3_client,
    *,
    app_id: uuid.UUID,
    bucket_id: uuid.UUID,
) -> None:
    bucket = await get_bucket(db, app_id=app_id, bucket_id=bucket_id)

    stored = await db.execute(
        select(func.count()).select_from(StorageObject).where(
            StorageObject.bucket_id == bucket.id
        )
    )
    if (stored.scalar() or 0) > 0:
        _require_s3(s3_client)
        prefix = f"{app_id}/{bucket_id}/"
        try:
            await _delete_s3_prefix(s3_client, prefix)
        except (BotoCoreError, ClientError) as exc:
            raise _storage_failure(exc)

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
    _require_s3(s3_client)
    key = _validate_object_key(key)
    content_type = _validate_content_type(content_type)

    size = len(data)
    if size > settings.object_storage_max_object_bytes:
        raise AuthError(
            f"Object too large ({size} bytes, max {settings.object_storage_max_object_bytes})",
            code="object_too_large",
        )

    bucket = await _lock_bucket(db, app_id=app_id, bucket_id=bucket_id)

    replaced = await db.execute(
        select(func.coalesce(func.sum(StorageObject.size_bytes), 0)).where(
            StorageObject.bucket_id == bucket_id,
            StorageObject.user_id == user_id,
            StorageObject.key == key,
        )
    )
    delta = size - (replaced.scalar() or 0)

    await _check_app_storage(db, app_id=app_id, additional=delta)
    _check_bucket_limit(
        "Bucket storage limit",
        await _bucket_usage(db, bucket_id=bucket.id),
        bucket.max_size_bytes,
        delta,
    )
    _check_bucket_limit(
        "User storage limit",
        await _bucket_usage(db, bucket_id=bucket.id, user_id=user_id),
        bucket.max_size_bytes_per_user,
        delta,
    )

    stmt = (
        pg_insert(StorageObject)
        .values(
            id=uuid.uuid4(),
            app_id=app_id,
            bucket_id=bucket_id,
            user_id=user_id,
            key=key,
            content_type=content_type,
            size_bytes=size,
        )
        .on_conflict_do_update(
            index_elements=["bucket_id", "user_id", "key"],
            set_={
                "content_type": content_type,
                "size_bytes": size,
                "updated_at": func.now(),
            },
        )
    )
    result = await db.execute(
        select(StorageObject)
        .from_statement(stmt.returning(StorageObject))
        .execution_options(populate_existing=True)
    )
    obj = result.scalars().one()
    await db.flush()

    try:
        await asyncio.to_thread(
            s3_client.put_object,
            Bucket=settings.s3_bucket_name,
            Key=_s3_key(app_id, bucket_id, user_id, key),
            Body=data,
            ContentType=content_type,
        )
    except (BotoCoreError, ClientError) as exc:
        raise _storage_failure(exc)

    await _invalidate_object_storage_cache(redis, app_id=app_id)
    await _invalidate_bucket_storage_cache(redis, bucket_id=bucket_id, user_id=user_id)
    return obj


async def get_object(
    db: AsyncSession,
    *,
    app_id: uuid.UUID,
    bucket_id: uuid.UUID,
    user_id: uuid.UUID,
    key: str,
) -> StorageObject:
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
    return obj


async def open_object(
    db: AsyncSession,
    s3_client,
    *,
    app_id: uuid.UUID,
    bucket_id: uuid.UUID,
    user_id: uuid.UUID,
    key: str,
) -> tuple[StorageObject, Any]:
    """Return the metadata row and an open S3 body to stream the payload from."""
    _require_s3(s3_client)
    key = _validate_object_key(key)
    obj = await get_object(
        db, app_id=app_id, bucket_id=bucket_id, user_id=user_id, key=key,
    )

    try:
        response = await asyncio.to_thread(
            s3_client.get_object,
            Bucket=settings.s3_bucket_name,
            Key=_s3_key(app_id, bucket_id, user_id, key),
        )
    except (BotoCoreError, ClientError) as exc:
        raise _storage_failure(exc)

    return obj, response["Body"]


async def iter_object_body(body, chunk_size: int = DOWNLOAD_CHUNK_BYTES):
    """Yield an S3 body in chunks so a download never lands in memory whole."""
    try:
        while True:
            chunk = await asyncio.to_thread(body.read, chunk_size)
            if not chunk:
                break
            yield chunk
    finally:
        close = getattr(body, "close", None)
        if close is not None:
            await asyncio.to_thread(close)


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
    _require_s3(s3_client)
    key = _validate_object_key(key)
    obj = await get_object(
        db, app_id=app_id, bucket_id=bucket_id, user_id=user_id, key=key,
    )

    await db.delete(obj)
    await db.flush()

    try:
        await asyncio.to_thread(
            s3_client.delete_object,
            Bucket=settings.s3_bucket_name,
            Key=_s3_key(app_id, bucket_id, user_id, key),
        )
    except (BotoCoreError, ClientError) as exc:
        raise _storage_failure(exc)

    await _invalidate_object_storage_cache(redis, app_id=app_id)
    await _invalidate_bucket_storage_cache(redis, bucket_id=bucket_id, user_id=user_id)


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
        cursor_key, cursor_id = _decode_cursor(cursor)
        q = q.where(
            tuple_(StorageObject.key, StorageObject.id) > tuple_(cursor_key, cursor_id)
        )

    q = q.limit(limit + 1)
    result = await db.execute(q)
    objects = list(result.scalars().all())

    next_cursor = None
    if len(objects) > limit:
        objects = objects[:limit]
        last = objects[-1]
        next_cursor = _encode_cursor(last.key, last.id)

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

    size = await _app_usage(db, app_id=app_id)
    await redis.set(cache_key, str(size), ex=60)
    return size


async def _app_usage(db: AsyncSession, *, app_id: uuid.UUID) -> int:
    result = await db.execute(
        select(func.coalesce(func.sum(StorageObject.size_bytes), 0)).where(
            StorageObject.app_id == app_id
        )
    )
    return result.scalar() or 0


async def _bucket_usage(
    db: AsyncSession,
    *,
    bucket_id: uuid.UUID,
    user_id: uuid.UUID | None = None,
) -> int:
    q = select(func.coalesce(func.sum(StorageObject.size_bytes), 0)).where(
        StorageObject.bucket_id == bucket_id
    )
    if user_id is not None:
        q = q.where(StorageObject.user_id == user_id)
    result = await db.execute(q)
    return result.scalar() or 0


async def _check_app_storage(
    db: AsyncSession,
    *,
    app_id: uuid.UUID,
    additional: int,
) -> None:
    limit = settings.object_storage_limit_bytes
    used = await _app_usage(db, app_id=app_id)
    if used + additional > limit:
        raise AuthError(
            f"Object storage limit exceeded ({used + additional} / {limit} bytes)",
            code="storage_limit_exceeded",
        )


def _check_bucket_limit(label: str, used: int, limit: int | None, additional: int) -> None:
    if limit is None:
        return
    if used + additional > limit:
        raise AuthError(
            f"{label} exceeded ({used + additional} / {limit} bytes)",
            code="storage_limit_exceeded",
        )


async def _invalidate_object_storage_cache(redis, *, app_id: uuid.UUID) -> None:
    await redis.delete(f"object_storage:{app_id}")


async def _invalidate_bucket_storage_cache(
    redis,
    *,
    bucket_id: uuid.UUID,
    user_id: uuid.UUID,
) -> None:
    await redis.delete(f"bucket_storage:{bucket_id}")
    await redis.delete(f"bucket_user_storage:{bucket_id}:{user_id}")


def _encode_cursor(key: str, object_id: uuid.UUID) -> str:
    payload = json.dumps({"k": key, "id": str(object_id)})
    return base64.urlsafe_b64encode(payload.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[str, uuid.UUID]:
    try:
        payload = base64.urlsafe_b64decode(cursor.encode()).decode()
        data = json.loads(payload)
        if not isinstance(data, dict) or "k" not in data or "id" not in data:
            raise ValueError
        if not isinstance(data["k"], str):
            raise ValueError
        return data["k"], uuid.UUID(str(data["id"]))
    except Exception:
        raise AuthError("Invalid cursor", code="invalid_cursor")
