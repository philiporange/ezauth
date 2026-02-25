import uuid
from datetime import datetime

from pydantic import BaseModel


class DomainCreate(BaseModel):
    domain: str
    type: str = "primary"


class DomainResponse(BaseModel):
    id: uuid.UUID
    app_id: uuid.UUID
    domain: str
    type: str
    verified: bool
    verified_at: datetime | None
    cname_target: str | None
    created_at: datetime

    model_config = {"from_attributes": True}
