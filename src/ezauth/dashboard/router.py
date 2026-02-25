from fastapi import APIRouter

from ezauth.dashboard import auth, tenants, applications, domains, users, email_templates

dashboard_router = APIRouter(prefix="/dashboard")

dashboard_router.include_router(auth.router, tags=["dashboard-auth"])
dashboard_router.include_router(tenants.router, prefix="/tenants", tags=["dashboard-tenants"])
dashboard_router.include_router(applications.router, prefix="/applications", tags=["dashboard-apps"])
dashboard_router.include_router(domains.router, prefix="/domains", tags=["dashboard-domains"])
dashboard_router.include_router(users.router, prefix="/users", tags=["dashboard-users"])
dashboard_router.include_router(email_templates.router, prefix="/email-templates", tags=["dashboard-email"])
