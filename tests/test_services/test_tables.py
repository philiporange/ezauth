import pytest
import pytest_asyncio

from ezauth.api import tables as tables_api
from ezauth.services import tables as tables_svc
from ezauth.services.auth import AuthError


@pytest_asyncio.fixture
async def table(db, app):
    return await tables_svc.create_table(
        db,
        app_id=app.id,
        name="items",
        columns=[
            {"name": "title", "type": "text"},
            {"name": "score", "type": "int"},
        ],
    )


async def _insert(db, redis, app, table, **data):
    return await tables_svc.insert_row(
        db, redis, app_id=app.id, table_id=table.id, data=data,
    )


class TestCursorPagination:
    @pytest.mark.asyncio
    async def test_default_sort_paginates_every_row_once(self, db, redis, app, table):
        for i in range(5):
            await _insert(db, redis, app, table, title=f"t{i}", score=i)

        seen = []
        cursor = None
        for _ in range(5):
            rows, cursor = await tables_svc.query_rows(
                db, app_id=app.id, table_id=table.id, limit=2, cursor=cursor,
            )
            seen.extend(r.id for r in rows)
            if cursor is None:
                break

        assert cursor is None
        assert len(seen) == 5
        assert len(set(seen)) == 5

    @pytest.mark.asyncio
    async def test_int_column_sort_paginates_in_order(self, db, redis, app, table):
        for i in (5, 1, 4, 2, 3):
            await _insert(db, redis, app, table, title=f"t{i}", score=i)

        scores = []
        cursor = None
        while True:
            rows, cursor = await tables_svc.query_rows(
                db,
                app_id=app.id,
                table_id=table.id,
                sort_field="score",
                limit=2,
                cursor=cursor,
            )
            scores.extend(r.data["score"] for r in rows)
            if cursor is None:
                break

        assert scores == [1, 2, 3, 4, 5]

    @pytest.mark.asyncio
    async def test_int_column_sort_handles_values_beyond_32_bits(self, db, redis, app, table):
        big = 2**40
        for score in (big + 1, big):
            await _insert(db, redis, app, table, title="big", score=score)

        rows, _ = await tables_svc.query_rows(
            db, app_id=app.id, table_id=table.id, sort_field="score", limit=10,
        )
        assert [r.data["score"] for r in rows] == [big, big + 1]

    @pytest.mark.asyncio
    async def test_descending_sort_paginates_every_row_once(self, db, redis, app, table):
        for i in range(5):
            await _insert(db, redis, app, table, title=f"t{i}", score=i)

        seen = []
        cursor = None
        while True:
            rows, cursor = await tables_svc.query_rows(
                db,
                app_id=app.id,
                table_id=table.id,
                sort_dir="desc",
                limit=2,
                cursor=cursor,
            )
            seen.extend(r.id for r in rows)
            if cursor is None:
                break

        assert len(set(seen)) == 5

    @pytest.mark.asyncio
    async def test_timestamp_column_sort_paginates_in_order(self, db, redis, app, table):
        await tables_svc.add_column(
            db, app_id=app.id, table_id=table.id, name="due", type="timestamptz",
        )
        stamps = [f"2024-01-0{i}T00:00:00+00:00" for i in range(1, 6)]
        for stamp in reversed(stamps):
            await _insert(db, redis, app, table, title="t", due=stamp)

        seen = []
        cursor = None
        while True:
            rows, cursor = await tables_svc.query_rows(
                db,
                app_id=app.id,
                table_id=table.id,
                sort_field="due",
                limit=2,
                cursor=cursor,
            )
            seen.extend(r.data["due"] for r in rows)
            if cursor is None:
                break

        assert seen == stamps

    @pytest.mark.asyncio
    async def test_malformed_cursor_is_a_client_error(self, db, app, table):
        with pytest.raises(AuthError) as exc:
            await tables_svc.query_rows(
                db, app_id=app.id, table_id=table.id, cursor="not-a-cursor",
            )
        assert exc.value.code == "invalid_cursor"
        assert tables_api._http_error(exc.value).status_code == 400


class TestFilterValidation:
    @pytest.mark.asyncio
    async def test_non_numeric_value_on_int_column_is_rejected(self, db, redis, app, table):
        await _insert(db, redis, app, table, title="a", score=1)

        with pytest.raises(AuthError) as exc:
            await tables_svc.query_rows(
                db,
                app_id=app.id,
                table_id=table.id,
                filter_spec={"field": "score", "op": "eq", "value": "abc"},
            )
        assert exc.value.code == "invalid_filter"
        assert tables_api._http_error(exc.value).status_code == 400

    @pytest.mark.asyncio
    async def test_non_timestamp_value_on_timestamp_column_is_rejected(self, db, app, table):
        with pytest.raises(AuthError) as exc:
            await tables_svc.query_rows(
                db,
                app_id=app.id,
                table_id=table.id,
                filter_spec={"field": "created_at", "op": "gt", "value": "yesterday"},
            )
        assert exc.value.code == "invalid_filter"

    @pytest.mark.asyncio
    async def test_null_value_compiles_to_a_null_check(self, db, redis, app, table):
        await _insert(db, redis, app, table, title="a")
        await _insert(db, redis, app, table, title="b", score=7)

        rows, _ = await tables_svc.query_rows(
            db,
            app_id=app.id,
            table_id=table.id,
            filter_spec={"field": "score", "op": "eq", "value": None},
        )
        assert [r.data["title"] for r in rows] == ["a"]

    @pytest.mark.asyncio
    async def test_nesting_beyond_the_cap_is_rejected(self, db, app, table):
        spec = {"field": "title", "op": "eq", "value": "x"}
        for _ in range(tables_svc.MAX_FILTER_DEPTH + 2):
            spec = {"and": [spec]}

        with pytest.raises(AuthError) as exc:
            await tables_svc.query_rows(
                db, app_id=app.id, table_id=table.id, filter_spec=spec,
            )
        assert exc.value.code == "invalid_filter"


class TestStorageLimit:
    @pytest.mark.asyncio
    async def test_write_that_exactly_fills_the_limit_is_allowed(self, db, redis, app, table):
        payload = {"title": "x"}
        size = tables_svc._payload_size(payload)

        row = await tables_svc.insert_row(
            db, redis, app_id=app.id, table_id=table.id, data=payload, storage_limit=size,
        )
        assert row.id is not None

    @pytest.mark.asyncio
    async def test_write_one_byte_over_the_limit_is_refused(self, db, redis, app, table):
        payload = {"title": "x"}
        size = tables_svc._payload_size(payload)

        with pytest.raises(AuthError) as exc:
            await tables_svc.insert_row(
                db,
                redis,
                app_id=app.id,
                table_id=table.id,
                data=payload,
                storage_limit=size - 1,
            )
        assert exc.value.code == "storage_limit_exceeded"
        assert tables_api._http_error(exc.value).status_code == 413


class TestColumnDataMigration:
    @pytest.mark.asyncio
    async def test_rename_moves_the_stored_key(self, db, redis, app, table):
        await _insert(db, redis, app, table, title="a", score=1)
        column = next(c for c in table.columns if c.name == "title")

        await tables_svc.update_column(
            db, app_id=app.id, table_id=table.id, column_id=column.id, name="label",
        )

        rows, _ = await tables_svc.query_rows(db, app_id=app.id, table_id=table.id)
        assert rows[0].data == {"label": "a", "score": 1}

    @pytest.mark.asyncio
    async def test_delete_strips_the_stored_key(self, db, redis, app, table):
        await _insert(db, redis, app, table, title="a", score=1)
        column = next(c for c in table.columns if c.name == "score")

        await tables_svc.delete_column(
            db, app_id=app.id, table_id=table.id, column_id=column.id,
        )

        rows, _ = await tables_svc.query_rows(db, app_id=app.id, table_id=table.id)
        assert rows[0].data == {"title": "a"}
