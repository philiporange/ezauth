"""Request and response models for the custom tables API.

Beyond field shapes these carry the limits the query DSL must respect: a filter
group holds exactly one of ``and``/``or``, and a whole filter tree is walked
iteratively on validation to cap its nesting depth and total condition count
before any of it reaches the query compiler.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

MAX_FILTER_DEPTH = 8
MAX_FILTER_CLAUSES = 64

# -- Column type enum --

class ColumnType(str, Enum):
    text = "text"
    int = "int"
    float = "float"
    bool = "bool"
    timestamptz = "timestamptz"
    json = "json"


# -- Table schemas --

class CreateTableRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, pattern=r"^[a-zA-Z_][a-zA-Z0-9_]*$")
    columns: list[CreateColumnInline] | None = None


class TableResponse(BaseModel):
    id: uuid.UUID
    name: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TableDetailResponse(BaseModel):
    id: uuid.UUID
    name: str
    columns: list[ColumnResponse]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TableListResponse(BaseModel):
    tables: list[TableResponse]
    total: int


# -- Column schemas --

class CreateColumnInline(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, pattern=r"^[a-zA-Z_][a-zA-Z0-9_]*$")
    type: ColumnType
    required: bool = False
    default_value: Any | None = None
    position: int | None = None


class CreateColumnRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, pattern=r"^[a-zA-Z_][a-zA-Z0-9_]*$")
    type: ColumnType
    required: bool = False
    default_value: Any | None = None
    position: int | None = None


class UpdateColumnRequest(BaseModel):
    name: str | None = Field(
        None, min_length=1, max_length=255, pattern=r"^[a-zA-Z_][a-zA-Z0-9_]*$"
    )
    required: bool | None = None
    default_value: Any | None = None
    position: int | None = None


class ColumnResponse(BaseModel):
    id: uuid.UUID
    name: str
    type: str
    required: bool
    default_value: Any | None
    position: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# -- Row schemas --

class CreateRowRequest(BaseModel):
    data: dict[str, Any]
    user_id: uuid.UUID | None = None


class UpdateRowRequest(BaseModel):
    data: dict[str, Any]


class RowResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID | None = None
    data: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# -- Filter / Query DSL --

class FilterCondition(BaseModel):
    field: str
    op: str = Field(..., pattern=r"^(eq|neq|gt|gte|lt|lte)$")
    value: Any


class FilterGroup(BaseModel):
    and_: list[FilterCondition | FilterGroup] | None = Field(None, alias="and")
    or_: list[FilterCondition | FilterGroup] | None = Field(None, alias="or")

    model_config = {"populate_by_name": True}

    @field_validator("and_", "or_")
    @classmethod
    def check_not_empty(cls, v):
        if v is not None and len(v) == 0:
            raise ValueError("Filter group must not be empty")
        return v

    @model_validator(mode="after")
    def check_exactly_one_group(self) -> FilterGroup:
        if (self.and_ is None) == (self.or_ is None):
            raise ValueError("Filter group must set exactly one of 'and' or 'or'")
        return self


def _check_filter_size(node: FilterCondition | FilterGroup) -> None:
    """Walk a filter tree iteratively, rejecting excessive nesting or clause counts."""
    clauses = 0
    pending: list[tuple[Any, int]] = [(node, 0)]
    while pending:
        current, depth = pending.pop()
        if depth > MAX_FILTER_DEPTH:
            raise ValueError(f"Filter nesting exceeds the maximum depth of {MAX_FILTER_DEPTH}")
        if isinstance(current, FilterGroup):
            for child in (current.and_ or []) + (current.or_ or []):
                pending.append((child, depth + 1))
        else:
            clauses += 1
            if clauses > MAX_FILTER_CLAUSES:
                raise ValueError(
                    f"Filter exceeds the maximum of {MAX_FILTER_CLAUSES} conditions"
                )


class SortSpec(BaseModel):
    field: str
    dir: str = Field("asc", pattern=r"^(asc|desc)$")


class QueryRowsRequest(BaseModel):
    filter: FilterCondition | FilterGroup | None = None
    sort: SortSpec | None = None
    limit: int = Field(50, ge=1, le=200)
    cursor: str | None = None

    @model_validator(mode="after")
    def check_filter_size(self) -> QueryRowsRequest:
        if self.filter is not None:
            _check_filter_size(self.filter)
        return self


class RowListResponse(BaseModel):
    rows: list[RowResponse]
    next_cursor: str | None = None


# -- Storage --

class StorageResponse(BaseModel):
    used_bytes: int
    limit_bytes: int
    used_percent: float
