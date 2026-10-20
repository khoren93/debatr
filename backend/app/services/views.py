"""Public view counter with a per-IP cool-down so reloads don't inflate numbers."""

import logging

from fastapi import Request
from redis.exceptions import RedisError
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import get_async_redis
from app.models.models import Debate, User

logger = logging.getLogger(__name__)

VIEW_COOLDOWN_SECONDS = 6 * 3600

#: Sent by the page renderer (frontend/src/api/server.server.ts). Its loads are not views: the
#: page counts itself after hydration (`POST /api/debates/{id}/view`), so crawlers without
#: JavaScript and pages served from the renderer's micro-cache neither add views nor hide them.
RENDER_HEADER = "x-debatr-render"


def counts_as_view(request: Request) -> bool:
    """Whether this request for a debate is someone looking at it (not the page renderer)."""
    return request.headers.get(RENDER_HEADER) != "server"


async def count_view(
    db: AsyncSession, debate: Debate, viewer: User | None, request: Request
) -> None:
    if not debate.is_public or (viewer is not None and viewer.id == debate.user_id):
        return
    client = request.client.host if request.client else "unknown"
    key = f"views:{debate.id}:{client}"
    try:
        fresh = await get_async_redis().set(key, "1", nx=True, ex=VIEW_COOLDOWN_SECONDS)
    except RedisError:
        logger.debug("View counter unavailable for %s", debate.id)
        return
    if not fresh:
        return
    await db.execute(update(Debate).where(Debate.id == debate.id).values(views=Debate.views + 1))
    await db.commit()
    debate.views = (debate.views or 0) + 1
