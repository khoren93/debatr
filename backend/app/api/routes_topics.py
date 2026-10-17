"""Trending debate topics from today's news (built by services/trending.py)."""

import logging
from collections import Counter
from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.core.db import get_db
from app.core.redis import get_async_redis, trending_queued_key
from app.models.models import TrendingBatch, TrendingTopic, utcnow
from app.schemas.schemas import (
    TrendingCategory,
    TrendingSource,
    TrendingTopicOut,
    TrendingTopicsOut,
)
from app.services.queue_manager import enqueue_trending_refresh
from app.services.trending import TOPIC_CATEGORIES, is_due

router = APIRouter()
logger = logging.getLogger(__name__)

QUEUED_TTL = 600  # a stale read enqueues a refresh at most once per 10 minutes


async def _refresh_if_stale(latest: datetime | None) -> None:
    """Without the scheduler process (native dev) the first stale read starts the refresh;
    visitors keep the current batch until the new one is saved."""
    if not settings.OPENROUTER_API_KEY or not is_due(
        latest, utcnow(), settings.TRENDING_REFRESH_HOURS
    ):
        return
    try:
        if await get_async_redis().set(trending_queued_key(), "1", nx=True, ex=QUEUED_TTL):
            await run_in_threadpool(enqueue_trending_refresh)
    except Exception:  # Redis trouble must not break the topic list
        logger.warning("Could not enqueue the trending refresh", exc_info=True)


def _topic_out(topic: TrendingTopic) -> TrendingTopicOut:
    return TrendingTopicOut(
        id=str(topic.id),
        rank=topic.rank,
        label=topic.label,
        question=topic.question,
        brief=topic.brief,
        category=topic.category,
        heat=topic.heat,
        outlets=topic.outlets,
        sources=[TrendingSource.model_validate(s) for s in topic.sources_json or []],
    )


@router.get("/trending", response_model=TrendingTopicsOut)
async def trending_topics(db: AsyncSession = Depends(get_db)) -> TrendingTopicsOut:
    """Topics of the newest batch, hottest first (hidden ones left out)."""
    batch = (
        await db.execute(select(TrendingBatch).order_by(TrendingBatch.created_at.desc()).limit(1))
    ).scalar_one_or_none()
    await _refresh_if_stale(batch.created_at if batch else None)
    topics: list[TrendingTopic] = []
    if batch is not None:
        topics = list(
            (
                await db.execute(
                    select(TrendingTopic)
                    .where(TrendingTopic.batch_id == batch.id, TrendingTopic.is_hidden.is_(False))
                    .order_by(TrendingTopic.rank)
                )
            )
            .scalars()
            .all()
        )
    counts = Counter(t.category for t in topics)
    return TrendingTopicsOut(
        updated_at=batch.created_at if batch else None,
        topics=[_topic_out(t) for t in topics],
        categories=[TrendingCategory(id=c, count=counts[c]) for c in TOPIC_CATEGORIES],
    )
