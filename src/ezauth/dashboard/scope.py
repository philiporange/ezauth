"""Ownership scoping helpers for the dashboard.

Two levels of access exist. Reading is granted through either route into a
tenant: the tenant's own `owner_email`, or ownership of one application inside
it, so an application owner can see the tenant their app lives in. Renaming or
deleting a tenant destroys every application under it, so it is granted only by
`Tenant.owner_email`. Applications are scoped to their own `owner_email` or to
the owner of their tenant. Superadmins (settings.dashboard_admin_emails) bypass
all filters.
"""

import uuid

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ezauth.dashboard.auth import DashboardAuth
from ezauth.models.application import Application
from ezauth.models.tenant import Tenant


def owned_app_ids(auth: DashboardAuth) -> Select:
    """Subquery of application IDs the auth identity may administer."""
    return (
        select(Application.id)
        .join(Tenant, Application.tenant_id == Tenant.id)
        .where(
            or_(
                func.lower(Application.owner_email) == auth.email,
                func.lower(Tenant.owner_email) == auth.email,
            )
        )
    )


def scope_tenants(query: Select, auth: DashboardAuth) -> Select:
    """Restrict a tenant query to what this identity may read."""
    if auth.is_super:
        return query
    return query.where(
        or_(
            func.lower(Tenant.owner_email) == auth.email,
            Tenant.id.in_(
                select(Application.tenant_id).where(
                    func.lower(Application.owner_email) == auth.email
                )
            ),
        )
    )


def scope_administered_tenants(query: Select, auth: DashboardAuth) -> Select:
    """Restrict a tenant query to tenants this identity may modify or delete."""
    if auth.is_super:
        return query
    return query.where(func.lower(Tenant.owner_email) == auth.email)


def scope_applications(query: Select, auth: DashboardAuth) -> Select:
    if auth.is_super:
        return query
    return query.where(Application.id.in_(owned_app_ids(auth)))


async def get_owned_tenant(
    db: AsyncSession, auth: DashboardAuth, tenant_id: uuid.UUID
) -> Tenant | None:
    query = scope_tenants(select(Tenant).where(Tenant.id == tenant_id), auth)
    result = await db.execute(query)
    return result.scalars().first()


async def get_administered_tenant(
    db: AsyncSession, auth: DashboardAuth, tenant_id: uuid.UUID
) -> Tenant | None:
    """The tenant, only if this identity owns it outright."""
    query = scope_administered_tenants(select(Tenant).where(Tenant.id == tenant_id), auth)
    result = await db.execute(query)
    return result.scalars().first()


async def get_owned_app(
    db: AsyncSession, auth: DashboardAuth, app_id: uuid.UUID
) -> Application | None:
    query = scope_applications(select(Application).where(Application.id == app_id), auth)
    result = await db.execute(query)
    return result.scalars().first()
