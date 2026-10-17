"""Fair share of the workers: how many runs one user may have going at a time.

A few workers serve everyone, so one user starting ten debates (or audio builds) would make
everybody else wait. The API refuses a run beyond MAX_ACTIVE_DEBATES_PER_USER /
MAX_ACTIVE_MEDIA_PER_USER with a 429 that says what to do. The user's row is locked until the
caller commits, so two requests at once cannot both take the last slot.
"""

import uuid

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.core.config import settings
from app.models.models import Debate, User

ACTIVE = ("queued", "running")


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
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"You already have {active} audio builds in progress: start this one when "
            "one of them is ready",
        )
