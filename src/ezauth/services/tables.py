"""Per-application custom tables: schema CRUD, row validation and typed queries.

A table and its columns are metadata rows; the row payload lives in a single
JSONB column. Every write is coerced to the declared column type, and queries
are compiled into typed JSONB expressions so that filtering and sorting behave
like real columns — integers compare as numerics, timestamps as timestamptz.
Filter values coming from clients are coerced to the resolved column type
before they are bound, and filter trees are capped in depth and clause count.

Listing uses keyset pagination: the cursor carries the sort value and the row
id, and the value is decoded back into the sort column's Python type before it
is bound to the comparison. Renaming or dropping a column rewrites the JSONB
payload of every affected row so stored data always matches the declared
schema. Storage accounting locks the owning application row before comparing
projected usage against the limit, so concurrent writes cannot both pass the
same check.
"""

import base64
import json
import uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import and_, cast, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.types import Boolean, DateTime, Float, Numeric

from ezauth.models.application import Application
from ezauth.models.custom_column import CustomColumn
from ezauth.models.custom_row import CustomRow
from ezauth.models.custom_table import CustomTable
from ezauth.services.auth import AuthError

# -- Constants --

MAX_ROWS_PER_TABLE = 10_000
DEFAULT_STORAGE_LIMIT = 104_857_600  # 100 MB
MAX_FILTER_DEPTH = 8
MAX_FILTER_CLAUSES = 64


# -- Table CRUD --

async def create_table(
    db: AsyncSession,
    *,
    app_id: uuid.UUID,
    name: str,
    columns: list[dict] | None = None,
) -> CustomTable:
    existing = await db.execute(
        select(CustomTable).where(
            CustomTable.app_id == app_id,
            CustomTable.name == name,
        )
    )
    if existing.scalars().first():
        raise AuthError(f"Table '{name}' already exists", code="table_exists")

    table = CustomTable(app_id=app_id, name=name)
    db.add(table)
    await db.flush()

    if columns:
        for i, col_def in enumerate(columns):
            col = CustomColumn(
                app_id=app_id,
                table_id=table.id,
                name=col_def["name"],
                type=col_def["type"],
                required=col_def.get("required", False),
                default_value=col_def.get("default_value"),
                position=col_def.get("position", i),
            )
            db.add(col)
        await db.flush()

    # Reload with columns for response
    result = await db.execute(
        select(CustomTable)
        .options(selectinload(CustomTable.columns))
        .where(CustomTable.id == table.id)
    )
    return result.scalars().first()


async def list_tables(
    db: AsyncSession,
    *,
    app_id: uuid.UUID,
) -> tuple[list[CustomTable], int]:
    count_q = select(func.count()).select_from(CustomTable).where(
        CustomTable.app_id == app_id
    )
    total = (await db.execute(count_q)).scalar() or 0

    q = (
        select(CustomTable)
        .where(CustomTable.app_id == app_id)
        .order_by(CustomTable.created_at.asc())
    )
    result = await db.execute(q)
    tables = list(result.scalars().all())
    return tables, total


async def get_table(
    db: AsyncSession,
    *,
    app_id: uuid.UUID,
    table_id: uuid.UUID,
) -> CustomTable:
    result = await db.execute(
        select(CustomTable)
        .options(selectinload(CustomTable.columns))
        .where(CustomTable.id == table_id, CustomTable.app_id == app_id)
    )
    table = result.scalars().first()
    if table is None:
        raise AuthError("Table not found", code="not_found")
    return table


async def delete_table(
    db: AsyncSession,
    *,
    app_id: uuid.UUID,
    table_id: uuid.UUID,
) -> None:
    result = await db.execute(
        select(CustomTable).where(
            CustomTable.id == table_id,
            CustomTable.app_id == app_id,
        )
    )
    table = result.scalars().first()
    if table is None:
        raise AuthError("Table not found", code="not_found")
    await db.delete(table)
    await db.flush()


# -- Column CRUD --

async def add_column(
    db: AsyncSession,
    *,
    app_id: uuid.UUID,
    table_id: uuid.UUID,
    name: str,
    type: str,
    required: bool = False,
    default_value: Any | None = None,
    position: int | None = None,
) -> CustomColumn:
    await _get_table_or_raise(db, app_id=app_id, table_id=table_id)

    existing = await db.execute(
        select(CustomColumn).where(
            CustomColumn.table_id == table_id,
            CustomColumn.name == name,
        )
    )
    if existing.scalars().first():
        raise AuthError(f"Column '{name}' already exists in this table", code="column_exists")

    if position is None:
        max_pos_result = await db.execute(
            select(func.max(CustomColumn.position)).where(
                CustomColumn.table_id == table_id
            )
        )
        max_pos = max_pos_result.scalar()
        position = (max_pos or 0) + 1

    col = CustomColumn(
        app_id=app_id,
        table_id=table_id,
        name=name,
        type=type,
        required=required,
        default_value=default_value,
        position=position,
    )
    db.add(col)
    await db.flush()
    return col


async def update_column(
    db: AsyncSession,
    *,
    app_id: uuid.UUID,
    table_id: uuid.UUID,
    column_id: uuid.UUID,
    name: str | None = None,
    required: bool | None = None,
    default_value: Any = ...,  # sentinel: ... means "not provided"
    position: int | None = None,
) -> CustomColumn:
    await _get_table_or_raise(db, app_id=app_id, table_id=table_id)

    result = await db.execute(
        select(CustomColumn).where(
            CustomColumn.id == column_id,
            CustomColumn.table_id == table_id,
        )
    )
    col = result.scalars().first()
    if col is None:
        raise AuthError("Column not found", code="not_found")

    renamed_from = None
    if name is not None and name != col.name:
        dup = await db.execute(
            select(CustomColumn).where(
                CustomColumn.table_id == table_id,
                CustomColumn.name == name,
                CustomColumn.id != column_id,
            )
        )
        if dup.scalars().first():
            raise AuthError(f"Column '{name}' already exists", code="column_exists")
        renamed_from = col.name
        col.name = name

    if required is not None:
        col.required = required
    if default_value is not ...:
        col.default_value = default_value
    if position is not None:
        col.position = position

    await db.flush()

    if renamed_from is not None:
        await _rename_row_key(
            db, app_id=app_id, table_id=table_id, old_name=renamed_from, new_name=col.name
        )

    await db.refresh(col)
    return col


async def delete_column(
    db: AsyncSession,
    *,
    app_id: uuid.UUID,
    table_id: uuid.UUID,
    column_id: uuid.UUID,
) -> None:
    await _get_table_or_raise(db, app_id=app_id, table_id=table_id)

    result = await db.execute(
        select(CustomColumn).where(
            CustomColumn.id == column_id,
            CustomColumn.table_id == table_id,
        )
    )
    col = result.scalars().first()
    if col is None:
        raise AuthError("Column not found", code="not_found")
    dropped_name = col.name
    await db.delete(col)
    await db.flush()
    await _drop_row_key(db, app_id=app_id, table_id=table_id, name=dropped_name)


async def _rename_row_key(
    db: AsyncSession,
    *,
    app_id: uuid.UUID,
    table_id: uuid.UUID,
    old_name: str,
    new_name: str,
) -> None:
    """Move every row's value from ``old_name`` to ``new_name`` inside the JSONB payload."""
    await db.execute(
        text(
            "UPDATE custom_rows "
            "SET data = (data - CAST(:old AS text)) "
            "    || jsonb_build_object(CAST(:new AS text), data -> CAST(:old AS text)) "
            "WHERE app_id = :app_id AND table_id = :table_id "
            "  AND data ? CAST(:old AS text)"
        ),
        {"old": old_name, "new": new_name, "app_id": app_id, "table_id": table_id},
    )
    _expire_cached_rows(db)


async def _drop_row_key(
    db: AsyncSession,
    *,
    app_id: uuid.UUID,
    table_id: uuid.UUID,
    name: str,
) -> None:
    """Strip a key from every row's JSONB payload in a table."""
    await db.execute(
        text(
            "UPDATE custom_rows SET data = data - CAST(:name AS text) "
            "WHERE app_id = :app_id AND table_id = :table_id "
            "  AND data ? CAST(:name AS text)"
        ),
        {"name": name, "app_id": app_id, "table_id": table_id},
    )
    _expire_cached_rows(db)


def _expire_cached_rows(db: AsyncSession) -> None:
    """Drop identity-map copies of rows whose JSONB payload was rewritten in bulk."""
    for obj in list(db.sync_session.identity_map.values()):
        if isinstance(obj, CustomRow):
            db.expire(obj)


# -- Row CRUD --

async def insert_row(
    db: AsyncSession,
    redis,
    *,
    app_id: uuid.UUID,
    table_id: uuid.UUID,
    data: dict[str, Any],
    user_id: uuid.UUID | None = None,
    storage_limit: int = DEFAULT_STORAGE_LIMIT,
) -> CustomRow:
    await _get_table_or_raise(db, app_id=app_id, table_id=table_id)
    columns = await _load_columns(db, table_id=table_id)

    count_result = await db.execute(
        select(func.count()).select_from(CustomRow).where(
            CustomRow.table_id == table_id,
            CustomRow.app_id == app_id,
        )
    )
    row_count = count_result.scalar() or 0
    if row_count >= MAX_ROWS_PER_TABLE:
        raise AuthError(
            f"Table row limit reached ({MAX_ROWS_PER_TABLE})",
            code="row_limit_exceeded",
        )

    validated_data = _validate_row_data(data, columns)

    await _reserve_storage(
        db, app_id=app_id, limit=storage_limit, additional=_payload_size(validated_data),
    )

    row = CustomRow(app_id=app_id, table_id=table_id, data=validated_data, user_id=user_id)
    db.add(row)
    await db.flush()

    await _invalidate_storage_cache(redis, app_id=app_id)
    return row


async def get_row(
    db: AsyncSession,
    *,
    app_id: uuid.UUID,
    table_id: uuid.UUID,
    row_id: uuid.UUID,
    user_id: uuid.UUID | None = None,
) -> CustomRow:
    q = select(CustomRow).where(
        CustomRow.id == row_id,
        CustomRow.table_id == table_id,
        CustomRow.app_id == app_id,
    )
    if user_id is not None:
        q = q.where(CustomRow.user_id == user_id)
    result = await db.execute(q)
    row = result.scalars().first()
    if row is None:
        raise AuthError("Row not found", code="not_found")
    return row


async def update_row(
    db: AsyncSession,
    redis,
    *,
    app_id: uuid.UUID,
    table_id: uuid.UUID,
    row_id: uuid.UUID,
    data: dict[str, Any],
    user_id: uuid.UUID | None = None,
    storage_limit: int = DEFAULT_STORAGE_LIMIT,
) -> CustomRow:
    columns = await _load_columns(db, table_id=table_id)
    row = await get_row(db, app_id=app_id, table_id=table_id, row_id=row_id, user_id=user_id)

    validated_partial = _validate_row_data_partial(data, columns)

    merged = {**row.data, **validated_partial}

    _validate_required_fields(merged, columns)

    await _reserve_storage(
        db,
        app_id=app_id,
        limit=storage_limit,
        additional=_payload_size(merged) - _payload_size(row.data),
    )

    row.data = merged
    await db.flush()
    await db.refresh(row)
    await _invalidate_storage_cache(redis, app_id=app_id)
    return row


async def delete_row(
    db: AsyncSession,
    redis,
    *,
    app_id: uuid.UUID,
    table_id: uuid.UUID,
    row_id: uuid.UUID,
    user_id: uuid.UUID | None = None,
) -> None:
    row = await get_row(db, app_id=app_id, table_id=table_id, row_id=row_id, user_id=user_id)
    await db.delete(row)
    await db.flush()
    await _invalidate_storage_cache(redis, app_id=app_id)


async def query_rows(
    db: AsyncSession,
    *,
    app_id: uuid.UUID,
    table_id: uuid.UUID,
    user_id: uuid.UUID | None = None,
    filter_spec: dict | None = None,
    sort_field: str | None = None,
    sort_dir: str = "asc",
    limit: int = 50,
    cursor: str | None = None,
) -> tuple[list[CustomRow], str | None]:
    columns = await _load_columns(db, table_id=table_id)
    col_map = {c.name: c for c in columns}

    q = select(CustomRow).where(
        CustomRow.app_id == app_id,
        CustomRow.table_id == table_id,
    )
    if user_id is not None:
        q = q.where(CustomRow.user_id == user_id)

    if filter_spec is not None:
        filter_clause = _compile_filter(filter_spec, col_map)
        q = q.where(filter_clause)

    sort_expr, sort_type = _resolve_sort(sort_field, col_map)
    if sort_dir == "desc":
        q = q.order_by(sort_expr.desc(), CustomRow.id.desc())
    else:
        q = q.order_by(sort_expr.asc(), CustomRow.id.asc())

    if cursor:
        cursor_data = _decode_cursor(cursor)
        cursor_id = cursor_data["id"]
        cursor_val = _coerce_bound_value(
            "cursor", cursor_data["v"], sort_type, code="invalid_cursor",
        )
        q = q.where(_keyset_predicate(sort_expr, sort_dir, cursor_val, cursor_id))

    q = q.limit(limit + 1)

    result = await db.execute(q)
    rows = list(result.scalars().all())

    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        last_row = rows[-1]

        if sort_field and sort_field in col_map:
            cursor_value = last_row.data.get(sort_field)
        elif sort_field in ("created_at", "updated_at"):
            cursor_value = getattr(last_row, sort_field).isoformat()
        else:
            cursor_value = last_row.created_at.isoformat()

        next_cursor = _encode_cursor(cursor_value, last_row.id)

    return rows, next_cursor


def _keyset_predicate(sort_expr, sort_dir: str, cursor_val: Any, cursor_id: uuid.UUID):
    """Build the "strictly after the cursor row" predicate for the given sort order.

    Postgres orders NULLs last for ascending and first for descending sorts, so a
    NULL cursor value bounds the remaining rows differently in each direction.
    """
    if sort_dir == "desc":
        if cursor_val is None:
            return or_(
                sort_expr.isnot(None),
                and_(sort_expr.is_(None), CustomRow.id < cursor_id),
            )
        return or_(
            sort_expr < cursor_val,
            and_(sort_expr == cursor_val, CustomRow.id < cursor_id),
        )

    if cursor_val is None:
        return and_(sort_expr.is_(None), CustomRow.id > cursor_id)
    return or_(
        sort_expr > cursor_val,
        and_(sort_expr == cursor_val, CustomRow.id > cursor_id),
        sort_expr.is_(None),
    )


# -- Storage --

async def get_storage_usage(
    db: AsyncSession,
    redis,
    *,
    app_id: uuid.UUID,
) -> int:
    cache_key = f"custom_tables:storage:{app_id}"

    cached = await redis.get(cache_key)
    if cached is not None:
        return int(cached)

    size = await _compute_storage_usage(db, app_id=app_id)
    await redis.set(cache_key, str(size), ex=60)
    return size


async def _compute_storage_usage(db: AsyncSession, *, app_id: uuid.UUID) -> int:
    result = await db.execute(
        text(
            "SELECT COALESCE(SUM(pg_column_size(data)), 0) "
            "FROM custom_rows WHERE app_id = :app_id"
        ),
        {"app_id": app_id},
    )
    return result.scalar() or 0


# -- Internal helpers --

async def _get_table_or_raise(
    db: AsyncSession,
    *,
    app_id: uuid.UUID,
    table_id: uuid.UUID,
) -> CustomTable:
    result = await db.execute(
        select(CustomTable).where(
            CustomTable.id == table_id,
            CustomTable.app_id == app_id,
        )
    )
    table = result.scalars().first()
    if table is None:
        raise AuthError("Table not found", code="not_found")
    return table


async def _load_columns(
    db: AsyncSession,
    *,
    table_id: uuid.UUID,
) -> list[CustomColumn]:
    result = await db.execute(
        select(CustomColumn)
        .where(CustomColumn.table_id == table_id)
        .order_by(CustomColumn.position)
    )
    return list(result.scalars().all())


def _payload_size(data: dict[str, Any]) -> int:
    """Estimate the stored size of a row payload in bytes."""
    return len(json.dumps(data, separators=(",", ":"), default=str).encode())


async def _reserve_storage(
    db: AsyncSession,
    *,
    app_id: uuid.UUID,
    limit: int,
    additional: int,
) -> None:
    """Take the per-application write lock and admit ``additional`` bytes, or raise.

    The application row is locked first so that concurrent writers queue up
    rather than all reading the same usage figure and all passing the check.
    """
    if additional <= 0:
        return

    await db.execute(
        select(Application.id).where(Application.id == app_id).with_for_update()
    )
    used = await _compute_storage_usage(db, app_id=app_id)
    if used + additional > limit:
        raise AuthError(
            f"Storage limit exceeded ({used + additional} / {limit} bytes)",
            code="storage_limit_exceeded",
        )


async def _invalidate_storage_cache(redis, *, app_id: uuid.UUID) -> None:
    cache_key = f"custom_tables:storage:{app_id}"
    await redis.delete(cache_key)


def _validate_row_data(
    data: dict[str, Any],
    columns: list[CustomColumn],
) -> dict[str, Any]:
    col_map = {c.name: c for c in columns}
    validated = {}

    for col in columns:
        if col.name not in data:
            if col.default_value is not None:
                validated[col.name] = col.default_value
            elif col.required:
                raise AuthError(
                    f"Missing required field: {col.name}",
                    code="validation_error",
                )

    for key, value in data.items():
        if key not in col_map:
            raise AuthError(
                f"Unknown column: {key}",
                code="validation_error",
            )
        col = col_map[key]
        validated[key] = _coerce_value(key, value, col.type, col.required)

    return validated


def _validate_row_data_partial(
    data: dict[str, Any],
    columns: list[CustomColumn],
) -> dict[str, Any]:
    col_map = {c.name: c for c in columns}
    validated = {}

    for key, value in data.items():
        if key not in col_map:
            raise AuthError(f"Unknown column: {key}", code="validation_error")
        col = col_map[key]
        validated[key] = _coerce_value(key, value, col.type, col.required)

    return validated


def _validate_required_fields(
    merged_data: dict[str, Any],
    columns: list[CustomColumn],
) -> None:
    for col in columns:
        if col.required and (col.name not in merged_data or merged_data[col.name] is None):
            raise AuthError(
                f"Required field cannot be null: {col.name}",
                code="validation_error",
            )


def _coerce_value(field_name: str, value: Any, col_type: str, required: bool) -> Any:
    if value is None:
        if required:
            raise AuthError(f"Field '{field_name}' is required", code="validation_error")
        return None

    if col_type == "text":
        if not isinstance(value, str):
            raise AuthError(f"Field '{field_name}' must be a string", code="validation_error")
        return value

    if col_type == "int":
        if isinstance(value, bool):
            raise AuthError(f"Field '{field_name}' must be an integer", code="validation_error")
        if not isinstance(value, int):
            raise AuthError(f"Field '{field_name}' must be an integer", code="validation_error")
        return value

    if col_type == "float":
        if isinstance(value, bool):
            raise AuthError(f"Field '{field_name}' must be a number", code="validation_error")
        if not isinstance(value, (int, float)):
            raise AuthError(f"Field '{field_name}' must be a number", code="validation_error")
        return float(value)

    if col_type == "bool":
        if not isinstance(value, bool):
            raise AuthError(f"Field '{field_name}' must be a boolean", code="validation_error")
        return value

    if col_type == "timestamptz":
        if not isinstance(value, str):
            raise AuthError(
                f"Field '{field_name}' must be an ISO 8601 timestamp string",
                code="validation_error",
            )
        try:
            datetime.fromisoformat(value)
        except ValueError:
            raise AuthError(
                f"Field '{field_name}' is not a valid ISO 8601 timestamp",
                code="validation_error",
            )
        return value

    if col_type == "json":
        return value

    raise AuthError(f"Unknown column type: {col_type}", code="validation_error")


def _resolve_sort(sort_field: str | None, col_map: dict[str, CustomColumn]):
    """Return the sort expression and the column type its values must be coerced to."""
    if sort_field is None or sort_field == "created_at":
        return CustomRow.created_at, "timestamptz"
    if sort_field == "updated_at":
        return CustomRow.updated_at, "timestamptz"
    if sort_field in col_map:
        col_type = col_map[sort_field].type
        return _jsonb_extract(sort_field, col_type), col_type
    raise AuthError(f"Unknown sort field: {sort_field}", code="invalid_sort")


def _resolve_field(field_name: str, col_map: dict[str, CustomColumn]):
    """Return the filter expression and column type for a queryable field name."""
    if field_name in ("created_at", "updated_at"):
        return getattr(CustomRow, field_name), "timestamptz"
    if field_name in col_map:
        col_type = col_map[field_name].type
        return _jsonb_extract(field_name, col_type), col_type
    raise AuthError(f"Unknown filter field: {field_name}", code="invalid_filter")


def _jsonb_extract(field_name: str, col_type: str):
    text_expr = CustomRow.data[field_name].astext

    if col_type == "int":
        # Numeric rather than a fixed-width integer: JSON integers are unbounded.
        return cast(text_expr, Numeric)
    elif col_type == "float":
        return cast(text_expr, Float)
    elif col_type == "bool":
        return cast(text_expr, Boolean)
    elif col_type == "timestamptz":
        return cast(text_expr, DateTime(timezone=True))
    else:
        return text_expr


def _coerce_bound_value(field_name: str, value: Any, col_type: str, *, code: str) -> Any:
    """Convert a client-supplied value into the Python type the column binds as."""
    if value is None:
        return None

    def bad(expected: str):
        return AuthError(
            f"Value for '{field_name}' must be {expected}", code=code,
        )

    if col_type == "int":
        if isinstance(value, bool):
            raise bad("an integer")
        if isinstance(value, int):
            return Decimal(value)
        if isinstance(value, float) and value.is_integer():
            return Decimal(int(value))
        if isinstance(value, str):
            try:
                return Decimal(value.strip())
            except (InvalidOperation, ValueError):
                raise bad("an integer")
        raise bad("an integer")

    if col_type == "float":
        if isinstance(value, bool):
            raise bad("a number")
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value.strip())
            except ValueError:
                raise bad("a number")
        raise bad("a number")

    if col_type == "bool":
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.strip().lower() in ("true", "false"):
            return value.strip().lower() == "true"
        raise bad("a boolean")

    if col_type == "timestamptz":
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                raise bad("an ISO 8601 timestamp")
        raise bad("an ISO 8601 timestamp")

    if col_type == "text":
        if isinstance(value, str):
            return value
        raise bad("a string")

    # JSON columns compare against the textual rendering of the stored value.
    if isinstance(value, str):
        return value
    return json.dumps(value)


def _compile_filter(
    spec: Any,
    col_map: dict[str, CustomColumn],
    *,
    depth: int = 0,
    state: dict | None = None,
):
    if state is None:
        state = {"clauses": 0}
    if depth > MAX_FILTER_DEPTH:
        raise AuthError(
            f"Filter nesting exceeds the maximum depth of {MAX_FILTER_DEPTH}",
            code="invalid_filter",
        )
    if not isinstance(spec, dict):
        raise AuthError("Invalid filter structure", code="invalid_filter")

    for key, combine in (("and", and_), ("or", or_)):
        children = spec.get(key)
        if children is None:
            continue
        if not isinstance(children, list) or not children:
            raise AuthError(f"Filter group '{key}' must be a non-empty list", code="invalid_filter")
        clauses = [
            _compile_filter(child, col_map, depth=depth + 1, state=state)
            for child in children
        ]
        return combine(*clauses)

    if "field" in spec:
        state["clauses"] += 1
        if state["clauses"] > MAX_FILTER_CLAUSES:
            raise AuthError(
                f"Filter exceeds the maximum of {MAX_FILTER_CLAUSES} conditions",
                code="invalid_filter",
            )

        field_name = spec["field"]
        op = spec.get("op")
        if not isinstance(op, str):
            raise AuthError("Filter condition requires an operator", code="invalid_filter")

        col_expr, col_type = _resolve_field(field_name, col_map)
        value = _coerce_bound_value(
            field_name, spec.get("value"), col_type, code="invalid_filter",
        )
        return _apply_op(col_expr, op, value)

    raise AuthError("Invalid filter structure", code="invalid_filter")


def _apply_op(col_expr, op: str, value: Any):
    if value is None:
        if op == "eq":
            return col_expr.is_(None)
        if op == "neq":
            return col_expr.isnot(None)
        raise AuthError(f"Operator '{op}' requires a value", code="invalid_filter")

    if op == "eq":
        return col_expr == value
    elif op == "neq":
        return col_expr != value
    elif op == "gt":
        return col_expr > value
    elif op == "gte":
        return col_expr >= value
    elif op == "lt":
        return col_expr < value
    elif op == "lte":
        return col_expr <= value
    else:
        raise AuthError(f"Unknown operator: {op}", code="invalid_filter")


def _encode_cursor(value: Any, row_id: uuid.UUID) -> str:
    payload = json.dumps({"v": value, "id": str(row_id)})
    return base64.urlsafe_b64encode(payload.encode()).decode()


def _decode_cursor(cursor: str) -> dict:
    try:
        payload = base64.urlsafe_b64decode(cursor.encode()).decode()
        data = json.loads(payload)
        if not isinstance(data, dict) or "v" not in data or "id" not in data:
            raise ValueError
        return {"v": data["v"], "id": uuid.UUID(str(data["id"]))}
    except Exception:
        raise AuthError("Invalid cursor", code="invalid_cursor")
