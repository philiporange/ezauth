"""Password management for signed-in users.

Setting a password requires an active session, which the user reaches either by
signing in or by proving control of their address through the reset flow. When
the account already has a password the current one must be supplied too, so a
stolen session cannot silently lock the owner out by replacing it.

A successful change revokes the user's other sessions, so whoever changed the
password keeps working and every other device is signed out.
"""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from ezauth.dependencies import AppDep, DbSession, SessionDep
from ezauth.models.user import User
from ezauth.services import passwords as password_service
from ezauth.services.auth import AuthError, set_password

router = APIRouter()


class SetPasswordRequest(BaseModel):
    password: str = Field(min_length=8, max_length=1024)
    current_password: str | None = None


@router.post("/passwords")
async def set_user_password(
    body: SetPasswordRequest,
    request: Request,
    db: DbSession,
    app: AppDep,
    session: SessionDep,
):
    """Set or change the signed-in user's password."""
    result = await db.execute(
        select(User).where(User.id == session.user_id, User.app_id == app.id)
    )
    user = result.scalars().first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    if user.password_hash is not None:
        if not body.current_password:
            raise HTTPException(status_code=400, detail="Current password is required")
        if not password_service.verify_password(body.current_password, user.password_hash):
            raise HTTPException(status_code=401, detail="Current password is incorrect")

    try:
        await set_password(
            db,
            app=app,
            user=user,
            new_password=body.password,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    except AuthError as e:
        raise HTTPException(status_code=400, detail=e.message)

    return {"status": "password_set"}
