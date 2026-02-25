import uuid

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select

from ezauth.dependencies import DbSession, SecretKeyApp
from ezauth.models.user import User
from ezauth.schemas.user import UserCreate, UserListResponse, UserResponse
from ezauth.services.passwords import hash_password

router = APIRouter()


@router.get("/users", response_model=UserListResponse)
async def list_users(
    db: DbSession,
    app: SecretKeyApp,
    limit: int = 50,
    offset: int = 0,
    email: str | None = None,
):
    query = select(User).where(User.app_id == app.id)
    if email:
        query = query.where(User.email_lower == email.lower())
    query = query.order_by(User.created_at.desc()).limit(limit).offset(offset)

    count_query = select(func.count()).select_from(User).where(User.app_id == app.id)
    if email:
        count_query = count_query.where(User.email_lower == email.lower())

    result = await db.execute(query)
    users = result.scalars().all()
    total_result = await db.execute(count_query)
    total = total_result.scalar()

    return UserListResponse(
        users=[UserResponse.from_user(u) for u in users],
        total=total or 0,
    )


@router.post("/users", response_model=UserResponse, status_code=201)
async def create_user(
    body: UserCreate,
    db: DbSession,
    app: SecretKeyApp,
):
    # Check existing
    existing = await db.execute(
        select(User).where(User.app_id == app.id, User.email_lower == body.email.lower())
    )
    if existing.scalars().first():
        raise HTTPException(status_code=409, detail="User already exists")

    user = User(
        app_id=app.id,
        email=body.email,
        password_hash=hash_password(body.password) if body.password else None,
    )
    db.add(user)
    await db.flush()
    return UserResponse.from_user(user)


@router.get("/users/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: uuid.UUID,
    db: DbSession,
    app: SecretKeyApp,
):
    result = await db.execute(
        select(User).where(User.id == user_id, User.app_id == app.id)
    )
    user = result.scalars().first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return UserResponse.from_user(user)
