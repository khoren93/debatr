"""Fair share of the workers: how many runs one user may have going at a time.

A few workers serve everyone, so one user starting ten debates (or audio builds) would make
everybody else wait. The API refuses a run beyond MAX_ACTIVE_DEBATES_PER_USER /
MAX_ACTIVE_MEDIA_PER_USER with a 429 that says what to do. The user's row is locked until the
caller commits, so two requests at once cannot both take the last slot. Refusals of the last day
are kept in Redis (REFUSALS_KEY) for the admin console's System page.
"""

import contextlib
import time
import uuid

from fastapi import HTTPException, status
from redis.exceptions import RedisError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.core.config import settings
from app.core.redis import get_async_redis
from app.models.models import Debate, User

ACTIVE = ("queued", "running")
# Sorted set of refusals: member "<kind>:<user id>:<nonce>", score = unix time; one day kept.
REFUSALS_KEY = "fairshare:refusals"
REFUSALS_SECONDS = 24 * 3600
REFUSALS_KEPT = 1000


async def note_refusal(kind: str, user_id: uuid.UUID) -> None:
    """Remember a refused run (never fails the request)."""
    now = time.time()
    with contextlib.suppress(RedisError, OSError):
        redis = get_async_redis()
        await redis.zadd(REFUSALS_KEY, {f"{kind}:{user_id}:{uuid.uuid4().hex[:8]}": now})
        await redis.zremrangebyscore(REFUSALS_KEY, 0, now - REFUSALS_SECONDS)
        await redis.zremrangebyrank(REFUSALS_KEY, 0, -(REFUSALS_KEPT + 1))


async def _active(db: AsyncSession, user_id: uuid.UUID, column: InstrumentedAttribute[str]) -> int:
    await db.execute(select(User.id).where(User.id == user_id).with_for_update())
    count = await db.scalar(
        select(func.count(Debate.id)).where(Debate.user_id == user_id, column.in_(ACTIVE))
    )
    return int(count or 0)


async def require_debate_slot(db: AsyncSession, user_id: uuid.UUID) -> None:
    limit = settings.MAX_ACTIVE_DEBATES_PER_USER
    if limit <= 0:
        return
    active = await _active(db, user_id, Debate.status)
    if active >= limit:
        await note_refusal("debate", user_id)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"You already have {active} debates running: start this one when one of "
            "them finishes (or stop one)",
        )


async def require_media_slot(db: AsyncSession, user_id: uuid.UUID) -> None:
    limit = settings.MAX_ACTIVE_MEDIA_PER_USER
    if limit <= 0:
        return
    active = await _active(db, user_id, Debate.media_status)
    if active >= limit:
        await note_refusal("media", user_id)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"You already have {active} audio builds in progress: start this one when "
            "one of them is ready",
        )
