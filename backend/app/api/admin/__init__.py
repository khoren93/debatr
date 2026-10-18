"""The admin console API (`/api/admin/*`, see app.admin.access and app.admin.gate)."""

from fastapi import APIRouter, Depends

from app.admin.access import enforce_admin_api_limit
from app.api.admin import routes_auth, routes_overview

router = APIRouter(dependencies=[Depends(enforce_admin_api_limit)])
router.include_router(routes_auth.router, prefix="/auth", tags=["admin"])
router.include_router(routes_overview.router, tags=["admin"])
