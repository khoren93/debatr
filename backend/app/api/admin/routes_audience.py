"""The console's Audience page (`/api/admin/audience*`, permission `audience`: admins only, the
answers carry IP addresses): the period's numbers, the visits live now, the visits list, one
visit, and an account's visits (`/users/{id}/visits`).

The period's numbers leave out console staff and bots / AI agents unless asked for (`staff`,
`bots`), are cached in Redis for CACHE_SECONDS per period, time zone and those switches
(`refresh=true` skips it), and run in a read-only transaction like the overview.
"""

import contextlib
import logging
import uuid
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.access import AdminContext, read_only_db, require_admin
from app.core.redis import get_async_redis
from app.models.models import User, utcnow
from app.schemas.admin import (
    AudienceOut,
    GeoDatabase,
    LiveOut,
    OverviewPeriod,
    UserVisits,
    VisitCard,
    VisitList,
    VisitListQuery,
)
from app.services.admin import audience, stats
from app.services.audience import geo

logger = logging.getLogger(__name__)
router = APIRouter()
read_audience = require_admin("audience")

CACHE_SECONDS = 60


def _timezone(name: str) -> str:
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return "UTC"
    return name


def _uuid(raw: str) -> uuid.UUID:
    try:
        return uuid.UUID(raw)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="No such visit") from exc


@router.get("/audience", response_model=AudienceOut)
async def audience_overview(
    period: OverviewPeriod = "7d",
    tz: str = Query("UTC", max_length=64),
    staff: bool = False,
    bots: bool = False,
    refresh: bool = False,
    _ctx: AdminContext = Depends(read_audience),
    db: AsyncSession = Depends(read_only_db),
) -> AudienceOut:
    timezone = _timezone(tz)
    key = f"admin:audience:{period}:{timezone}:{int(staff)}:{int(bots)}"
    redis = get_async_redis()
    if not refresh:
        try:
            cached = await redis.get(key)
            if cached:
                return AudienceOut.model_validate_json(cached)
        except (RedisError, ValueError):
            logger.warning("Audience cache unreadable, building it again")
    now = utcnow()
    since = await audience.first_visit(db)
    window = stats.window_for(period, now, since)
    out = AudienceOut.model_validate(
        {
            "period": period,
            "start": window.start,
            "end": window.end,
            "previous_start": window.previous_start,
            "bucket": window.bucket,
            "generated_at": now,
            "timezone": timezone,
            "data_since": since,
            "geo": GeoDatabase.model_validate(geo.info()),
            **(
                await audience.build(
                    db, window, now, who=audience.Who(staff=staff, bots=bots), timezone=timezone
                )
            ),
        }
    )
    with contextlib.suppress(RedisError):
        await redis.set(key, out.model_dump_json(), ex=CACHE_SECONDS)
    return out


@router.get("/audience/live", response_model=LiveOut)
async def audience_live(
    _ctx: AdminContext = Depends(read_audience),
    db: AsyncSession = Depends(read_only_db),
) -> LiveOut:
    now = utcnow()
    return LiveOut(visits=await audience.live(db, now), generated_at=now)


@router.get("/audience/visits", response_model=VisitList)
async def audience_visits(
    query: Annotated[VisitListQuery, Query()],
    _ctx: AdminContext = Depends(read_audience),
    db: AsyncSession = Depends(read_only_db),
) -> VisitList:
    now = utcnow()
    window = stats.window_for(query.period, now, await audience.first_visit(db))
    return await audience.list_visits(db, query, window)


@router.get("/audience/visits/{visit_id}", response_model=VisitCard)
async def audience_visit(
    visit_id: str,
    _ctx: AdminContext = Depends(read_audience),
    db: AsyncSession = Depends(read_only_db),
) -> VisitCard:
    card = await audience.visit_card(db, _uuid(visit_id))
    if card is None:
        raise HTTPException(status_code=404, detail="No such visit")
    return card


@router.get("/users/{user_id}/visits", response_model=UserVisits)
async def user_visits(
    user_id: str,
    _ctx: AdminContext = Depends(read_audience),
    db: AsyncSession = Depends(read_only_db),
) -> UserVisits:
    try:
        account = await db.get(User, uuid.UUID(user_id))
    except ValueError:
        account = None
    if account is None:
        raise HTTPException(status_code=404, detail="No such account")
    return UserVisits.model_validate(await audience.user_visits(db, account.id))
