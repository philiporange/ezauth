"""HTTP routes for custom per-application tables.

Table and column definitions are administered with the application secret key
or an admin JWT; end users may only read and write row data, and every such
request is scoped to the caller's own user id. Because there is no per-table
permission column, end users cannot enumerate or inspect table definitions at
all — listing and detail are admin-only — and rows they create or read always
carry their own user id. An admin naming a target user has that user checked
against the calling application first.

Service errors carry a code that is mapped to a status here, so malformed
filters, unparseable cursors and values that do not fit their column type come
back as 4xx rather than surfacing as a 500 from the database driver.
"""

import uuid

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from ezauth.config import settings
from ezauth.dependencies import AppAuthDep, DbSession, RedisDep
from ezauth.models.user import User
from ezauth.schemas.tables import (
    ColumnResponse,
    CreateColumnRequest,
    CreateRowRequest,
    CreateTableRequest,
    QueryRowsRequest,
    RowListResponse,
    RowResponse,
    StorageResponse,
    TableDetailResponse,
    TableListResponse,
    TableResponse,
    UpdateColumnRequest,
    UpdateRowRequest,
)
from ezauth.services import tables as tables_svc
from ezauth.services.auth import AuthError

router = APIRouter()

_STATUS_BY_CODE = {
    "column_exists": 409,
    "invalid_cursor": 400,
    "invalid_filter": 400,
    "invalid_sort": 400,
    "not_found": 404,
    "row_limit_exceeded": 413,
    "storage_limit_exceeded": 413,
    "table_exists": 409,
    "validation_error": 422,
}


def _http_error(exc: AuthError) -> HTTPException:
    return HTTPException(status_code=_STATUS_BY_CODE.get(exc.code, 400), detail=exc.message)


def _require_admin(auth: AppAuthDep) -> None:
    if not auth.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")


async def _resolve_row_user(
    db: DbSession,
    auth: AppAuthDep,
    user_id: uuid.UUID | None,
) -> uuid.UUID | None:
    """Return the user id rows are scoped to, validating an admin-supplied id."""
    if not auth.is_admin:
        return auth.user_id
    if user_id is None:
        return None

    result = await db.execute(
        select(User.id).where(User.id == user_id, User.app_id == auth.app.id)
    )
    if result.scalar() is None:
        raise HTTPException(
            status_code=400, detail="user_id does not belong to this application",
        )
    return user_id


# -- Tables --

@router.post("/tables", response_model=TableDetailResponse, status_code=201)
async def create_table(
    body: CreateTableRequest,
    db: DbSession,
    auth: AppAuthDep,
):
    _require_admin(auth)
    try:
        columns = None
        if body.columns:
            columns = [
                {
                    "name": c.name,
                    "type": c.type.value,
                    "required": c.required,
                    "default_value": c.default_value,
                    "position": c.position,
                }
                for c in body.columns
            ]
        table = await tables_svc.create_table(
            db, app_id=auth.app.id, name=body.name, columns=columns,
        )
        return table
    except AuthError as e:
        raise _http_error(e)


@router.get("/tables", response_model=TableListResponse)
async def list_tables(
    db: DbSession,
    auth: AppAuthDep,
):
    _require_admin(auth)
    tables, total = await tables_svc.list_tables(db, app_id=auth.app.id)
    return TableListResponse(
        tables=[TableResponse.model_validate(t) for t in tables],
        total=total,
    )


@router.get("/tables/storage", response_model=StorageResponse)
async def get_storage(
    db: DbSession,
    auth: AppAuthDep,
    redis: RedisDep,
):
    _require_admin(auth)
    used = await tables_svc.get_storage_usage(db, redis, app_id=auth.app.id)
    limit = settings.custom_tables_storage_limit_bytes
    return StorageResponse(
        used_bytes=used,
        limit_bytes=limit,
        used_percent=round((used / limit) * 100, 2) if limit > 0 else 0,
    )


@router.get("/tables/{table_id}", response_model=TableDetailResponse)
async def get_table(
    table_id: uuid.UUID,
    db: DbSession,
    auth: AppAuthDep,
):
    _require_admin(auth)
    try:
        table = await tables_svc.get_table(db, app_id=auth.app.id, table_id=table_id)
        return table
    except AuthError as e:
        raise _http_error(e)


@router.delete("/tables/{table_id}", status_code=204)
async def delete_table(
    table_id: uuid.UUID,
    db: DbSession,
    auth: AppAuthDep,
):
    _require_admin(auth)
    try:
        await tables_svc.delete_table(db, app_id=auth.app.id, table_id=table_id)
    except AuthError as e:
        raise _http_error(e)


# -- Columns --

@router.post("/tables/{table_id}/columns", response_model=ColumnResponse, status_code=201)
async def add_column(
    table_id: uuid.UUID,
    body: CreateColumnRequest,
    db: DbSession,
    auth: AppAuthDep,
):
    _require_admin(auth)
    try:
        col = await tables_svc.add_column(
            db,
            app_id=auth.app.id,
            table_id=table_id,
            name=body.name,
            type=body.type.value,
            required=body.required,
            default_value=body.default_value,
            position=body.position,
        )
        return col
    except AuthError as e:
        raise _http_error(e)


@router.patch("/tables/{table_id}/columns/{column_id}", response_model=ColumnResponse)
async def update_column(
    table_id: uuid.UUID,
    column_id: uuid.UUID,
    body: UpdateColumnRequest,
    db: DbSession,
    auth: AppAuthDep,
):
    _require_admin(auth)
    try:
        provided = body.model_fields_set
        kwargs: dict = {}
        if body.name is not None:
            kwargs["name"] = body.name
        if body.required is not None:
            kwargs["required"] = body.required
        if "default_value" in provided:
            kwargs["default_value"] = body.default_value
        if body.position is not None:
            kwargs["position"] = body.position

        col = await tables_svc.update_column(
            db,
            app_id=auth.app.id,
            table_id=table_id,
            column_id=column_id,
            **kwargs,
        )
        return col
    except AuthError as e:
        raise _http_error(e)


@router.delete("/tables/{table_id}/columns/{column_id}", status_code=204)
async def delete_column(
    table_id: uuid.UUID,
    column_id: uuid.UUID,
    db: DbSession,
    auth: AppAuthDep,
):
    _require_admin(auth)
    try:
        await tables_svc.delete_column(
            db, app_id=auth.app.id, table_id=table_id, column_id=column_id,
        )
    except AuthError as e:
        raise _http_error(e)


# -- Rows --

@router.post("/tables/{table_id}/rows", response_model=RowResponse, status_code=201)
async def insert_row(
    table_id: uuid.UUID,
    body: CreateRowRequest,
    db: DbSession,
    auth: AppAuthDep,
    redis: RedisDep,
):
    limit = settings.custom_tables_storage_limit_bytes
    # Users auto-get their own user_id; admins can optionally specify one
    row_user_id = await _resolve_row_user(db, auth, body.user_id)
    try:
        row = await tables_svc.insert_row(
            db, redis,
            app_id=auth.app.id,
            table_id=table_id,
            data=body.data,
            user_id=row_user_id,
            storage_limit=limit,
        )
        return row
    except AuthError as e:
        raise _http_error(e)


@router.post("/tables/{table_id}/rows/query", response_model=RowListResponse)
async def query_rows(
    table_id: uuid.UUID,
    body: QueryRowsRequest,
    db: DbSession,
    auth: AppAuthDep,
):
    # Users only see their own rows; admins see all
    query_user_id = None if auth.is_admin else auth.user_id
    try:
        filter_spec = None
        if body.filter:
            filter_spec = body.filter.model_dump(by_alias=True)

        rows, next_cursor = await tables_svc.query_rows(
            db,
            app_id=auth.app.id,
            table_id=table_id,
            user_id=query_user_id,
            filter_spec=filter_spec,
            sort_field=body.sort.field if body.sort else None,
            sort_dir=body.sort.dir if body.sort else "asc",
            limit=body.limit,
            cursor=body.cursor,
        )
        return RowListResponse(
            rows=[RowResponse.model_validate(r) for r in rows],
            next_cursor=next_cursor,
        )
    except AuthError as e:
        raise _http_error(e)


@router.get("/tables/{table_id}/rows/{row_id}", response_model=RowResponse)
async def get_row(
    table_id: uuid.UUID,
    row_id: uuid.UUID,
    db: DbSession,
    auth: AppAuthDep,
):
    row_user_id = None if auth.is_admin else auth.user_id
    try:
        row = await tables_svc.get_row(
            db, app_id=auth.app.id, table_id=table_id, row_id=row_id, user_id=row_user_id,
        )
        return row
    except AuthError as e:
        raise _http_error(e)


@router.patch("/tables/{table_id}/rows/{row_id}", response_model=RowResponse)
async def update_row(
    table_id: uuid.UUID,
    row_id: uuid.UUID,
    body: UpdateRowRequest,
    db: DbSession,
    auth: AppAuthDep,
    redis: RedisDep,
):
    limit = settings.custom_tables_storage_limit_bytes
    row_user_id = None if auth.is_admin else auth.user_id
    try:
        row = await tables_svc.update_row(
            db, redis,
            app_id=auth.app.id,
            table_id=table_id,
            row_id=row_id,
            data=body.data,
            user_id=row_user_id,
            storage_limit=limit,
        )
        return row
    except AuthError as e:
        raise _http_error(e)


@router.delete("/tables/{table_id}/rows/{row_id}", status_code=204)
async def delete_row(
    table_id: uuid.UUID,
    row_id: uuid.UUID,
    db: DbSession,
    auth: AppAuthDep,
    redis: RedisDep,
):
    row_user_id = None if auth.is_admin else auth.user_id
    try:
        await tables_svc.delete_row(
            db, redis,
            app_id=auth.app.id,
            table_id=table_id,
            row_id=row_id,
            user_id=row_user_id,
        )
    except AuthError as e:
        raise _http_error(e)
