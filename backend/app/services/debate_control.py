"""Stopping a debate, for its owner (POST /api/debates/{id}/stop) and the admin console."""

import logging

from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import get_async_redis, stop_flag_key
from app.models.models import Debate, utcnow
from app.services.events import publish_event_async

logger = logging.getLogger(__name__)

ACTIVE_STATUSES = ("queued", "running")


def mark_stopped(debate: Debate) -> None:
    debate.status = "stopped"
    debate.ended_at = utcnow()


async def signal_stopped(debate_id: str) -> None:
    """After the commit: the worker checks the Redis flag every few chunks, so the current turn
    ends early, and viewers hear about it."""
    try:
        await get_async_redis().set(stop_flag_key(debate_id), "1", ex=3600)
    except RedisError:
        logger.warning("Could not set stop flag for %s; worker will stop at next turn", debate_id)
    await publish_event_async(
        debate_id, "debate_stopped", {"debate_id": debate_id, "status": "stopped"}
    )


async def stop_debate(db: AsyncSession, debate: Debate) -> None:
    """Mark a queued or running debate stopped and tell the worker."""
    mark_stopped(debate)
    await db.commit()
    await signal_stopped(str(debate.id))
