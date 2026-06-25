"""Dashboard user browser: paginated, searchable list scoped to owned apps."""

import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ezauth.dashboard.auth import DashboardAuth, require_dashboard_auth
from ezauth.dashboard.scope import owned_app_ids
from ezauth.dependencies import get_db
from ezauth.models.user import User

router = APIRouter()
templates = Jinja2Templates(directory="src/ezauth/dashboard/templates")

PAGE_SIZE = 50


@router.get("", response_class=HTMLResponse)
async def list_users(
    request: Request,
    app_id: uuid.UUID | None = None,
    search: str | None = None,
    page: int = 1,
    db: AsyncSession = Depends(get_db),
    auth: DashboardAuth = Depends(require_dashboard_auth),
):
    page = max(page, 1)
    offset = (page - 1) * PAGE_SIZE

    query = select(User).order_by(User.created_at.desc())
    count_query = select(func.count()).select_from(User)

    if not auth.is_super:
        query = query.where(User.app_id.in_(owned_app_ids(auth)))
        count_query = count_query.where(User.app_id.in_(owned_app_ids(auth)))
    if app_id:
        query = query.where(User.app_id == app_id)
        count_query = count_query.where(User.app_id == app_id)
    if search:
        query = query.where(User.email_lower.contains(search.lower()))
        count_query = count_query.where(User.email_lower.contains(search.lower()))

    query = query.limit(PAGE_SIZE).offset(offset)
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
            "page_size": PAGE_SIZE,
            "app_id": app_id,
            "search": search,
            "auth": auth,
        },
    )
