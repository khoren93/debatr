"""Trending topics in the admin console (`/api/admin/trending*`): batches with their feed
statistics, dropped topics and blocked headlines; hide or show a topic on the site; build a new
batch now. Reading and hiding need `moderation`, building (a paid model call) needs `system`.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.admin.access import AdminContext, read_only_db, require_admin
from app.core.db import get_db
from app.models.models import TrendingTopic
from app.schemas.admin import ActionOut, TrendingBatchCard, TrendingBatchPage
from app.services.admin import audit
from app.services.admin import debates as admin_debates
from app.services.queue_manager import enqueue_trending_refresh

router = APIRouter()


def _uuid(raw: str, what: str) -> uuid.UUID:
    try:
        return uuid.UUID(raw)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"No such {what}") from None


@router.get("/trending/batches", response_model=TrendingBatchPage)
async def batches(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _ctx: AdminContext = Depends(require_admin("moderation")),
    db: AsyncSession = Depends(read_only_db),
) -> TrendingBatchPage:
    total, rows = await admin_debates.trending_batches(db, limit=limit, offset=offset)
    return TrendingBatchPage.model_validate({"total": total, "rows": rows})


@router.get("/trending/batches/{batch_id}", response_model=TrendingBatchCard)
async def batch(
    batch_id: str,
    _ctx: AdminContext = Depends(require_admin("moderation")),
    db: AsyncSession = Depends(read_only_db),
) -> TrendingBatchCard:
    card = await admin_debates.trending_batch(db, _uuid(batch_id, "batch"))
    if card is None:
        raise HTTPException(status_code=404, detail="No such batch")
    return TrendingBatchCard.model_validate(card)


async def _set_hidden(
    db: AsyncSession, ctx: AdminContext, request: Request, topic_id: str, hidden: bool
) -> ActionOut:
    topic = await db.get(TrendingTopic, _uuid(topic_id, "topic"))
    if topic is None:
        raise HTTPException(status_code=404, detail="No such topic")
    if topic.is_hidden == hidden:
        raise HTTPException(status_code=409, detail="Already hidden" if hidden else "Not hidden")
    topic.is_hidden = hidden
    await audit.record(
        db,
        "trending.hidden" if hidden else "trending.shown",
        request=request,
        actor=ctx.user,
        target_type="trending_topic",
        target_id=topic.id,
        before={"question": topic.question, "batch": str(topic.batch_id)},
    )
    return ActionOut(
        status="hidden" if hidden else "shown",
        message="Hidden from the site" if hidden else "Shown on the site again",
    )


@router.post("/trending/topics/{topic_id}/hide", response_model=ActionOut)
async def hide(
    topic_id: str,
    request: Request,
    ctx: AdminContext = Depends(require_admin("moderation")),
    db: AsyncSession = Depends(get_db),
) -> ActionOut:
    return await _set_hidden(db, ctx, request, topic_id, True)


@router.post("/trending/topics/{topic_id}/show", response_model=ActionOut)
async def show(
    topic_id: str,
    request: Request,
    ctx: AdminContext = Depends(require_admin("moderation")),
    db: AsyncSession = Depends(get_db),
) -> ActionOut:
    return await _set_hidden(db, ctx, request, topic_id, False)


@router.post("/trending/build", response_model=ActionOut)
async def build_now(
    request: Request,
    ctx: AdminContext = Depends(require_admin("system")),
    db: AsyncSession = Depends(get_db),
) -> ActionOut:
    """Fetch the news and build a new batch now (about a minute; the newest batch is shown)."""
    try:
        await run_in_threadpool(enqueue_trending_refresh, True)
    except RedisError:
        raise HTTPException(status_code=503, detail="The job queue is unavailable") from None
    await audit.record(
        db, "trending.build_requested", request=request, actor=ctx.user, target_type="trending"
    )
    return ActionOut(status="queued", message="Building a new batch; it takes about a minute")
