from fastapi import APIRouter

from ezauth.hosted import auth_pages

hosted_router = APIRouter(prefix="/auth", tags=["hosted-auth"])
hosted_router.include_router(auth_pages.router)
