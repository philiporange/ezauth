import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ezauth.dashboard.auth import require_dashboard_auth
from ezauth.dependencies import get_db
from ezauth.models.user import User

router = APIRouter()
templates = Jinja2Templates(directory="src/ezauth/dashboard/templates")


@router.get("", response_class=HTMLResponse)
async def list_users(
    request: Request,
    app_id: uuid.UUID | None = None,
    search: str | None = None,
    page: int = 1,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_dashboard_auth),
):
    limit = 50
    offset = (page - 1) * limit

    query = select(User).order_by(User.created_at.desc())
    count_query = select(func.count()).select_from(User)

    if app_id:
        query = query.where(User.app_id == app_id)
        count_query = count_query.where(User.app_id == app_id)
    if search:
        query = query.where(User.email_lower.contains(search.lower()))
        count_query = count_query.where(User.email_lower.contains(search.lower()))

    query = query.limit(limit).offset(offset)
    result = await db.execute(query)
    users = result.scalars().all()

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    return templates.TemplateResponse(
        "users/list.html",
        {
            "request": request,
            "users": users,
            "total": total,
            "page": page,
            "app_id": app_id,
            "search": search,
        },
    )
