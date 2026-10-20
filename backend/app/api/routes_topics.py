"""Topics for the wizard's first step: trending ones from today's news (built by
services/trending.py, a list per show format that writes topics its own way) and AI ideas from
the user's own words (services/topic_ideas.py)."""

import logging
from collections import Counter
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.auth import require_user
from app.core.config import settings
from app.core.db import get_db
from app.core.ratelimit import enforce_limit
from app.core.redis import get_async_redis, trending_queued_key
from app.models.models import TrendingBatch, TrendingTopic, User, utcnow
from app.schemas.schemas import (
    TOPIC_MAX_LENGTH,
    TopicIdeasIn,
    TopicIdeasOut,
    TrendingCategory,
    TrendingSource,
    TrendingTopicOut,
    TrendingTopicsOut,
)
from app.services import topic_ideas
from app.services.formats import DEFAULT_FORMAT, topic_list_of
from app.services.openrouter_client import OpenRouterError
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


def _topic_out(topic: TrendingTopic, rank: int) -> TrendingTopicOut:
    return TrendingTopicOut(
        id=str(topic.id),
        format=topic.format,
        rank=rank,
        label=topic.label,
        question=topic.question,
        brief=topic.brief,
        category=topic.category,
        heat=topic.heat,
        outlets=topic.outlets,
        sources=[TrendingSource.model_validate(s) for s in topic.sources_json or []],
    )


@router.get("/trending", response_model=TrendingTopicsOut)
async def trending_topics(
    format: str = Query(DEFAULT_FORMAT, max_length=32),
    db: AsyncSession = Depends(get_db),
) -> TrendingTopicsOut:
    """Topics of the format's list in the newest batch that has one (a list that failed to
    build leaves its format the previous one), hottest first: hidden ones left out, and
    questions too long for a debate topic (batches built before the limit had them)."""
    list_id = topic_list_of(format)
    await _refresh_if_stale(await db.scalar(select(func.max(TrendingBatch.created_at))))
    has_list = exists().where(
        TrendingTopic.batch_id == TrendingBatch.id, TrendingTopic.format == list_id
    )
    batch = (
        await db.execute(
            select(TrendingBatch).where(has_list).order_by(TrendingBatch.created_at.desc()).limit(1)
        )
    ).scalar_one_or_none()
    topics: list[TrendingTopic] = []
    if batch is not None:
        topics = list(
            (
                await db.execute(
                    select(TrendingTopic)
                    .where(
                        TrendingTopic.batch_id == batch.id,
                        TrendingTopic.format == list_id,
                        TrendingTopic.is_hidden.is_(False),
                    )
                    .order_by(TrendingTopic.rank)
                )
            )
            .scalars()
            .all()
        )
        topics = [t for t in topics if len(t.question) <= TOPIC_MAX_LENGTH]
    counts = Counter(t.category for t in topics)
    return TrendingTopicsOut(
        format=list_id,
        updated_at=batch.created_at if batch else None,
        topics=[_topic_out(t, rank) for rank, t in enumerate(topics, start=1)],
        categories=[TrendingCategory(id=c, count=counts[c]) for c in TOPIC_CATEGORIES],
    )


@router.post("/ideas", response_model=TopicIdeasOut)
async def ideas(
    body: TopicIdeasIn, request: Request, user: User = Depends(require_user)
) -> TopicIdeasOut:
    """Topics for the chosen format written from the user's own words (the wizard's AI button).
    Free for the user; `TOPIC_IDEAS_PER_HOUR` per account."""
    if not settings.OPENROUTER_API_KEY or not settings.TOPIC_IDEAS_MODEL:
        raise HTTPException(status_code=503, detail="AI topic ideas are off on this server")
    await enforce_limit(
        request,
        bucket="topic-ideas",
        limit=settings.TOPIC_IDEAS_PER_HOUR,
        window_seconds=3600,
        what="AI topic ideas",
        key=str(user.id),
    )
    try:
        found = await run_in_threadpool(
            topic_ideas.suggest, body.text, body.format, body.language, str(user.id)
        )
    except (OpenRouterError, ValueError) as exc:
        logger.warning("Topic ideas failed: %s", exc)
        raise HTTPException(
            status_code=502, detail="The AI could not write topics just now. Try again."
        ) from None
    return TopicIdeasOut(format=body.format, ideas=found)
