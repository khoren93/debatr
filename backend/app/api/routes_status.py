"""`GET /api/status`: what the site shows from the admin console's levers (sign-ups closed,
maintenance mode with its message, limits of free debates, AI covers, the presence beacon) and
the contact address (SUPPORT_EMAIL). Public and cheap: the levers are cached per process."""

from fastapi import APIRouter

from app.core.config import settings
from app.schemas.schemas import SiteStatusOut
from app.services import free_limits, runtime_settings
from app.services.credits import cover_charge_usd

router = APIRouter()


@router.get("/status", response_model=SiteStatusOut)
async def site_status() -> SiteStatusOut:
    levers = await runtime_settings.current()
    return SiteStatusOut(
        registration_open=levers.registration_open,
        maintenance=levers.maintenance,
        maintenance_message=levers.notice() if levers.maintenance else None,
        free_debates=free_limits.site_limits(levers),
        ai_covers=levers.ai_covers,
        cover_price_usd=float(cover_charge_usd(settings.COVER_PRICE_USD, levers.credit_markup)),
        analytics=levers.analytics_enabled,
        support_email=settings.SUPPORT_EMAIL or None,
    )
