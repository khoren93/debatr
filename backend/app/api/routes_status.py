"""`GET /api/status`: what the site shows from the admin console's levers (sign-ups closed,
maintenance mode with its message). Public and cheap: the levers are cached per process."""

from fastapi import APIRouter

from app.schemas.schemas import SiteStatusOut
from app.services import runtime_settings

router = APIRouter()


@router.get("/status", response_model=SiteStatusOut)
async def site_status() -> SiteStatusOut:
    levers = await runtime_settings.current()
    return SiteStatusOut(
        registration_open=levers.registration_open,
        maintenance=levers.maintenance,
        maintenance_message=levers.notice() if levers.maintenance else None,
    )
