"""The admin console API (`/api/admin/*`, see app.admin.access and app.admin.gate)."""

from fastapi import APIRouter, Depends

from app.admin.access import enforce_admin_api_limit
from app.api.admin import (
    routes_audience,
    routes_audit,
    routes_auth,
    routes_debates,
    routes_finance,
    routes_overview,
    routes_passkeys,
    routes_settings,
    routes_system,
    routes_trending,
    routes_users,
)

router = APIRouter(dependencies=[Depends(enforce_admin_api_limit)])
router.include_router(routes_auth.router, prefix="/auth", tags=["admin"])
router.include_router(routes_passkeys.router, prefix="/auth", tags=["admin"])
router.include_router(routes_overview.router, tags=["admin"])
router.include_router(routes_users.router, tags=["admin"])
router.include_router(routes_debates.router, tags=["admin"])
router.include_router(routes_trending.router, tags=["admin"])
router.include_router(routes_system.router, tags=["admin"])
router.include_router(routes_finance.router, tags=["admin"])
router.include_router(routes_audit.router, tags=["admin"])
router.include_router(routes_audience.router, tags=["admin"])
router.include_router(routes_settings.router, tags=["admin"])
