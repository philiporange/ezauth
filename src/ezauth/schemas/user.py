import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr


class UserCreate(BaseModel):
    email: EmailStr
    password: str | None = None


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str | None = None
    email_verified: bool
    is_bot: bool = False
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @classmethod
    def from_user(cls, user) -> "UserResponse":
        return cls(
            id=user.id,
            email=user.email,
            email_verified=user.email_verified_at is not None,
            is_bot=user.is_bot,
            created_at=user.created_at,
            updated_at=user.updated_at,
        )


class UserListResponse(BaseModel):
    users: list[UserResponse]
    total: int
