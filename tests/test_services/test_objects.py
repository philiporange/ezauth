from unittest.mock import MagicMock

import pytest
import pytest_asyncio

from ezauth.api import objects as objects_api
from ezauth.config import settings
from ezauth.models.storage_object import StorageObject
from ezauth.services import objects as objects_svc
from ezauth.services.auth import AuthError


@pytest.fixture
def s3(monkeypatch):
    monkeypatch.setattr(settings, "s3_bucket_name", "test-bucket")
    return MagicMock()


@pytest_asyncio.fixture
async def bucket(db, app):
    return await objects_svc.create_bucket(db, app_id=app.id, name="files")


class TestObjectKeyValidation:
    @pytest.mark.parametrize(
        "key",
        [
            "",
            "/leading",
            "a//b",
            "trailing/",
            "../escape",
            "a/../b",
            "./here",
            "bad\x00key",
            "line\nbreak",
            "x" * (objects_svc.MAX_OBJECT_KEY_LENGTH + 1),
        ],
    )
    def test_rejected_keys(self, key):
        with pytest.raises(AuthError) as exc:
            objects_svc._validate_object_key(key)
        assert exc.value.code == "invalid_key"
        assert objects_api._http_error(exc.value).status_code == 400

    @pytest.mark.parametrize("key", ["file.txt", "dir/file.txt", "a/b/c-1_2.png", "..dots"])
    def test_accepted_keys(self, key):
        assert objects_svc._validate_object_key(key) == key

    def test_over_long_content_type_is_rejected(self):
        with pytest.raises(AuthError) as exc:
            objects_svc._validate_content_type(
                "x" * (objects_svc.MAX_CONTENT_TYPE_LENGTH + 1)
            )
        assert exc.value.code == "invalid_content_type"

    def test_missing_content_type_falls_back(self):
        assert objects_svc._validate_content_type("") == objects_svc.DEFAULT_CONTENT_TYPE


class TestStorageUnavailable:
    @pytest.mark.asyncio
    async def test_put_without_an_s3_client_is_refused(self, db, redis, app, bucket, user):
        with pytest.raises(AuthError) as exc:
            await objects_svc.put_object(
                db, redis, None,
                app_id=app.id,
                bucket_id=bucket.id,
                user_id=user.id,
                key="a.txt",
                content_type="text/plain",
                data=b"hello",
            )
        assert exc.value.code == "storage_unavailable"
        assert objects_api._http_error(exc.value).status_code == 503

    @pytest.mark.asyncio
    async def test_read_without_an_s3_client_is_refused(self, db, app, bucket, user):
        with pytest.raises(AuthError) as exc:
            await objects_svc.open_object(
                db, None,
                app_id=app.id,
                bucket_id=bucket.id,
                user_id=user.id,
                key="a.txt",
            )
        assert exc.value.code == "storage_unavailable"


class TestBucketSizeLimit:
    @pytest.mark.asyncio
    async def test_upload_that_exactly_fills_the_bucket_is_allowed(
        self, db, redis, s3, app, user
    ):
        bucket = await objects_svc.create_bucket(
            db, app_id=app.id, name="capped", max_size_bytes=10,
        )
        obj = await objects_svc.put_object(
            db, redis, s3,
            app_id=app.id,
            bucket_id=bucket.id,
            user_id=user.id,
            key="a.bin",
            content_type="application/octet-stream",
            data=b"0123456789",
        )
        assert obj.size_bytes == 10

    @pytest.mark.asyncio
    async def test_upload_one_byte_over_the_bucket_limit_is_refused(
        self, db, redis, s3, app, user
    ):
        bucket = await objects_svc.create_bucket(
            db, app_id=app.id, name="capped", max_size_bytes=10,
        )
        with pytest.raises(AuthError) as exc:
            await objects_svc.put_object(
                db, redis, s3,
                app_id=app.id,
                bucket_id=bucket.id,
                user_id=user.id,
                key="a.bin",
                content_type="application/octet-stream",
                data=b"0123456789x",
            )
        assert exc.value.code == "storage_limit_exceeded"
        assert objects_api._http_error(exc.value).status_code == 413

    @pytest.mark.asyncio
    async def test_a_nearly_full_bucket_refuses_the_next_object(self, db, redis, s3, app, user):
        bucket = await objects_svc.create_bucket(
            db, app_id=app.id, name="capped", max_size_bytes=10,
        )
        await objects_svc.put_object(
            db, redis, s3,
            app_id=app.id,
            bucket_id=bucket.id,
            user_id=user.id,
            key="a.bin",
            content_type="application/octet-stream",
            data=b"012345678",
        )
        with pytest.raises(AuthError) as exc:
            await objects_svc.put_object(
                db, redis, s3,
                app_id=app.id,
                bucket_id=bucket.id,
                user_id=user.id,
                key="b.bin",
                content_type="application/octet-stream",
                data=b"xx",
            )
        assert exc.value.code == "storage_limit_exceeded"

    @pytest.mark.asyncio
    async def test_overwrite_counts_only_the_size_difference(self, db, redis, s3, app, user):
        bucket = await objects_svc.create_bucket(
            db, app_id=app.id, name="capped", max_size_bytes=10,
        )
        for payload in (b"012345678", b"987654321"):
            obj = await objects_svc.put_object(
                db, redis, s3,
                app_id=app.id,
                bucket_id=bucket.id,
                user_id=user.id,
                key="a.bin",
                content_type="application/octet-stream",
                data=payload,
            )
        assert obj.size_bytes == 9

        total = await objects_svc._bucket_usage(db, bucket_id=bucket.id)
        assert total == 9


class TestObjectListing:
    @pytest.mark.asyncio
    async def test_pagination_returns_every_object_once_in_key_order(
        self, db, app, bucket, user
    ):
        keys = [f"file-{i}.txt" for i in range(5)]
        for key in keys:
            db.add(
                StorageObject(
                    app_id=app.id,
                    bucket_id=bucket.id,
                    user_id=user.id,
                    key=key,
                    content_type="text/plain",
                    size_bytes=1,
                )
            )
        await db.flush()

        seen = []
        cursor = None
        while True:
            objects, cursor = await objects_svc.list_objects(
                db, app_id=app.id, bucket_id=bucket.id, limit=2, cursor=cursor,
            )
            seen.extend(o.key for o in objects)
            if cursor is None:
                break

        assert seen == sorted(keys)

    @pytest.mark.asyncio
    async def test_malformed_cursor_is_a_client_error(self, db, app, bucket):
        with pytest.raises(AuthError) as exc:
            await objects_svc.list_objects(
                db, app_id=app.id, bucket_id=bucket.id, cursor="}}not-base64{{",
            )
        assert exc.value.code == "invalid_cursor"
        assert objects_api._http_error(exc.value).status_code == 400
