import uuid
from datetime import datetime

from pydantic import BaseModel


class ApplicationCreate(BaseModel):
    name: str
    environment: str = "dev"
    primary_domain: str | None = None
    allowed_origins: list[str] | None = None
    email_from_name: str | None = None
    email_from_address: str | None = None


class ApplicationUpdate(BaseModel):
    name: str | None = None
    primary_domain: str | None = None
    allowed_origins: list[str] | None = None
    email_from_name: str | None = None
    email_from_address: str | None = None


class ApplicationResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    environment: str
    publishable_key: str
    primary_domain: str | None
    allowed_origins: list[str] | None
    email_from_name: str | None
    email_from_address: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ApplicationWithSecrets(ApplicationResponse):
    secret_key: str
