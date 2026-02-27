from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class CreateBucketRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, pattern=r"^[a-zA-Z_][a-zA-Z0-9_\-]*$")
    max_size_bytes: int | None = Field(None, gt=0)
    max_size_bytes_per_user: int | None = Field(None, gt=0)


class UpdateBucketRequest(BaseModel):
    max_size_bytes: int | None = None
    max_size_bytes_per_user: int | None = None


class BucketResponse(BaseModel):
    id: uuid.UUID
    name: str
    max_size_bytes: int | None = None
    max_size_bytes_per_user: int | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class BucketListResponse(BaseModel):
    buckets: list[BucketResponse]
    total: int


class ObjectResponse(BaseModel):
    id: uuid.UUID
    key: str
    content_type: str
    size_bytes: int
    user_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ObjectListResponse(BaseModel):
    objects: list[ObjectResponse]
    next_cursor: str | None = None


class ObjectStorageResponse(BaseModel):
    used_bytes: int
    limit_bytes: int
    used_percent: float
