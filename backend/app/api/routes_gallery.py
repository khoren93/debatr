"""Public gallery of published debates, share links (/d/{slug}) and the model leaderboard."""

from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import ColumnElement, and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only, selectinload

from app.api.serializers import debater_models, detail_out, gallery_item_out
from app.core.auth import get_current_user
from app.core.db import get_db
from app.models.models import Debate, DebateParticipant, DebateVote, User, utcnow
from app.schemas.schemas import (
    GALLERY_CATEGORIES,
    DebateDetail,
    GalleryPeriod,
    GalleryResponse,
    GallerySort,
    LeaderboardEntry,
    LeaderboardOut,
)
from app.services import ranking
from app.services.engagement import engagement_out
from app.services.openrouter_client import openrouter_client
from app.services.views import count_view

router = APIRouter()

PERIODS: dict[str, timedelta] = {
    "week": timedelta(days=7),
    "month": timedelta(days=30),
    "year": timedelta(days=365),
}


def _published_at() -> ColumnElement[Any]:
    return func.coalesce(Debate.published_at, Debate.created_at)


def trending_sql() -> ColumnElement[Any]:
    """SQL twin of `ranking.trending_score`."""
    age_hours = func.extract("epoch", func.now() - _published_at()) / 3600.0
    engagement = (
        Debate.likes_count * ranking.LIKE_WEIGHT
        + Debate.votes_count * ranking.VOTE_WEIGHT
        + func.ln(Debate.views + 1)
        + 1
    )
    return engagement / func.power(
        func.greatest(age_hours, 0) + ranking.TRENDING_OFFSET_HOURS, ranking.TRENDING_GRAVITY
    )


def _public() -> list[ColumnElement[bool]]:
    return [Debate.is_public.is_(True), Debate.slug.is_not(None)]


@router.get("", response_model=GalleryResponse)
async def list_gallery(
    category: str | None = Query(None, max_length=40),
    q: str | None = Query(None, max_length=200),
    model: str | None = Query(None, max_length=200, description="Debates this model argued in"),
    sort: GallerySort = Query("new"),
    period: GalleryPeriod = Query("all", description="Publication window for sort=top"),
    limit: int = Query(24, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> GalleryResponse:
    conditions = _public()
    if category and category.lower() in GALLERY_CATEGORIES:
        conditions.append(Debate.category == category.lower())
    if q and q.strip():
        conditions.append(Debate.title.ilike(f"%{q.strip()}%"))
    if model and model.strip():
        conditions.append(
            Debate.participants.any(
                and_(
                    DebateParticipant.model_id == model.strip(),
                    DebateParticipant.role == "debater",
                )
            )
        )
    if sort == "top" and period in PERIODS:
        conditions.append(_published_at() >= utcnow() - PERIODS[period])

    newest = (Debate.published_at.desc().nulls_last(), Debate.created_at.desc())
    if sort == "trending":
        order: tuple[Any, ...] = (trending_sql().desc(), *newest)
    elif sort == "top":
        order = (
            Debate.likes_count.desc(),
            Debate.votes_count.desc(),
            Debate.views.desc(),
            *newest,
        )
    else:
        order = newest

    total = await db.scalar(select(func.count(Debate.id)).where(*conditions)) or 0
    stmt = (
        select(Debate)
        .options(selectinload(Debate.participants), selectinload(Debate.user))
        .where(*conditions)
        .order_by(*order)
        .limit(limit)
        .offset(offset)
    )
    debates = (await db.execute(stmt)).scalars().all()
    return GalleryResponse(items=[gallery_item_out(d) for d in debates], total=int(total))


@router.get("/leaderboard", response_model=LeaderboardOut)
async def leaderboard(db: AsyncSession = Depends(get_db)) -> LeaderboardOut:
    """Models ranked by audience votes across public debates (only models that argued in at
    least one public, finished debate are listed)."""
    finished = [*_public(), Debate.status == "completed"]
    debates = (
        (
            await db.execute(
                select(Debate)
                .options(
                    load_only(Debate.id, Debate.verdict_json), selectinload(Debate.participants)
                )
                .where(*finished)
            )
        )
        .scalars()
        .all()
    )
    vote_rows = await db.execute(
        select(DebateVote.debate_id, DebateVote.participant_id, func.count())
        .join(Debate, Debate.id == DebateVote.debate_id)
        .where(*finished)
        .group_by(DebateVote.debate_id, DebateVote.participant_id)
    )
    votes: dict[Any, dict[str, int]] = {}
    for debate_id, participant_id, count in vote_rows.all():
        votes.setdefault(debate_id, {})[participant_id] = int(count)

    records = [
        ranking.DebateRecord(
            models=debater_models(d),
            votes=votes.get(d.id, {}),
            judge_winner=(d.verdict_json or {}).get("winner_id"),
        )
        for d in debates
    ]
    catalogue = {m["id"]: m for m in await openrouter_client.get_models()}
    entries = []
    for s in ranking.build_leaderboard(records):
        info = catalogue.get(s.model_id) or {}
        entries.append(
            LeaderboardEntry(
                model_id=s.model_id,
                name=str(info.get("name") or s.model_id),
                is_free=bool(info.get("is_free", s.model_id.endswith(":free"))),
                rating=round(s.rating),
                debates=s.debates,
                votes=s.votes,
                vote_share=s.vote_share,
                audience_wins=s.audience_wins,
                audience_contests=s.audience_contests,
                judge_wins=s.judge_wins,
                judge_contests=s.judge_contests,
            )
        )
    return LeaderboardOut(
        entries=entries,
        total_debates=len(records),
        total_votes=sum(sum(v.values()) for v in votes.values()),
    )


@router.get("/{slug}", response_model=DebateDetail)
async def get_public_debate(
    slug: str,
    request: Request,
    viewer: User | None = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DebateDetail:
    stmt = (
        select(Debate)
        .options(
            selectinload(Debate.turns),
            selectinload(Debate.participants),
            selectinload(Debate.user),
        )
        .where(Debate.slug == slug, Debate.is_public.is_(True))
    )
    debate = (await db.execute(stmt)).scalar_one_or_none()
    if debate is None:
        raise HTTPException(status_code=404, detail="This debate is not public")
    await count_view(db, debate, viewer, request)
    return detail_out(debate, viewer, await engagement_out(db, debate, viewer))
