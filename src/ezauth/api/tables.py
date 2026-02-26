import uuid

from fastapi import APIRouter, HTTPException

from ezauth.config import settings
from ezauth.dependencies import AppAuthDep, DbSession, RedisDep
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


def _require_admin(auth: AppAuthDep) -> None:
    if not auth.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")


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
        if e.code == "table_exists":
            raise HTTPException(status_code=409, detail=e.message)
        raise HTTPException(status_code=400, detail=e.message)


@router.get("/tables", response_model=TableListResponse)
async def list_tables(
    db: DbSession,
    auth: AppAuthDep,
):
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
    try:
        table = await tables_svc.get_table(db, app_id=auth.app.id, table_id=table_id)
        return table
    except AuthError as e:
        raise HTTPException(status_code=404, detail=e.message)


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
        raise HTTPException(status_code=404, detail=e.message)


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
        if e.code in ("column_exists", "table_exists"):
            raise HTTPException(status_code=409, detail=e.message)
        if e.code == "not_found":
            raise HTTPException(status_code=404, detail=e.message)
        raise HTTPException(status_code=400, detail=e.message)


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
        kwargs: dict = {}
        if body.name is not None:
            kwargs["name"] = body.name
        if body.required is not None:
            kwargs["required"] = body.required
        if body.default_value is not None:
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
        if e.code == "column_exists":
            raise HTTPException(status_code=409, detail=e.message)
        if e.code == "not_found":
            raise HTTPException(status_code=404, detail=e.message)
        raise HTTPException(status_code=400, detail=e.message)


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
        raise HTTPException(status_code=404, detail=e.message)


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
    if auth.is_admin:
        row_user_id = body.user_id
    else:
        row_user_id = auth.user_id
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
        if e.code in ("storage_limit_exceeded", "row_limit_exceeded"):
            raise HTTPException(status_code=413, detail=e.message)
        if e.code == "validation_error":
            raise HTTPException(status_code=422, detail=e.message)
        if e.code == "not_found":
            raise HTTPException(status_code=404, detail=e.message)
        raise HTTPException(status_code=400, detail=e.message)


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
            filter_spec = body.filter.model_dump(by_alias=True, exclude_none=True)

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
        if e.code in ("invalid_filter", "invalid_sort", "invalid_cursor"):
            raise HTTPException(status_code=400, detail=e.message)
        if e.code == "not_found":
            raise HTTPException(status_code=404, detail=e.message)
        raise HTTPException(status_code=400, detail=e.message)


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
        raise HTTPException(status_code=404, detail=e.message)


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
        if e.code == "storage_limit_exceeded":
            raise HTTPException(status_code=413, detail=e.message)
        if e.code == "validation_error":
            raise HTTPException(status_code=422, detail=e.message)
        if e.code == "not_found":
            raise HTTPException(status_code=404, detail=e.message)
        raise HTTPException(status_code=400, detail=e.message)


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
        raise HTTPException(status_code=404, detail=e.message)
