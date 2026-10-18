"""On which days accounts are active (DAU / WAU / MAU, retention) and when they were last seen.

`note_activity` runs for every authenticated API request (core.auth.get_current_user: cookie or
API token) but writes only when the user's UTC day changed or ACTIVITY_TOUCH passed since
`users.last_seen_at`, so a busy client costs one small write per ten minutes. It writes in a
session of its own and never fails the request.
"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm.attributes import set_committed_value

from app.core.db import AsyncSessionLocal
from app.models.models import User, UserActivityDay, utcnow

logger = logging.getLogger(__name__)

ACTIVITY_TOUCH = timedelta(minutes=10)


def activity_due(last_seen: datetime | None, now: datetime) -> tuple[bool, bool]:
    """(write `last_seen_at`, add a row for today)."""
    if last_seen is None:
        return True, True
    new_day = last_seen.astimezone(UTC).date() != now.astimezone(UTC).date()
    return new_day or now - last_seen >= ACTIVITY_TOUCH, new_day


async def note_activity(user: User, now: datetime | None = None) -> None:
    moment = now or utcnow()
    touch, new_day = activity_due(user.last_seen_at, moment)
    if not touch:
        return
    try:
        async with AsyncSessionLocal() as db:
            if new_day:
                await db.execute(
                    insert(UserActivityDay)
                    .values(user_id=user.id, day=moment.astimezone(UTC).date())
                    .on_conflict_do_nothing()
                )
            await db.execute(update(User).where(User.id == user.id).values(last_seen_at=moment))
            await db.commit()
    except Exception:
        logger.warning("Could not record the activity of %s", user.id, exc_info=True)
        return
    # The request's own copy of the user learns the value without becoming dirty.
    set_committed_value(user, "last_seen_at", moment)
