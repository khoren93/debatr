"""`POST /api/presence`: the site's presence beacon (services/audience). Always 204, whatever
happened to the beacon: a page has nothing to do with the answer."""

from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.config import settings
from app.core.db import get_db
from app.core.ratelimit import enforce_limit
from app.models.models import User, utcnow
from app.services import runtime_settings
from app.services.audience.collect import Context, parse_beacon, record
from app.services.views import host_of, is_bot

router = APIRouter()

RATE_WINDOW_SECONDS = 600


@router.post("/presence", status_code=204, include_in_schema=False)
async def presence(
    request: Request,
    viewer: User | None = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    done = Response(status_code=204)
    user_agent = request.headers.get("user-agent")
    if is_bot(user_agent) or not (await runtime_settings.current()).analytics_enabled:
        return done
    await enforce_limit(
        request,
        bucket="presence",
        limit=settings.PRESENCE_RATE_LIMIT,
        window_seconds=RATE_WINDOW_SECONDS,
        what="requests",
    )
    beacon = parse_beacon(await request.body())
    if beacon is None:
        return done
    context = Context(
        ip=request.client.host if request.client else None,
        user_agent=user_agent,
        user=viewer,
        now=utcnow(),
        site_host=host_of(urlsplit(settings.SITE_URL).netloc) or "",
        site_aliases=settings.site_aliases,
    )
    await record(db, beacon, context)
    return done
