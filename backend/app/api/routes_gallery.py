"""Public gallery of published debates, share links (/d/{slug}) and the model leaderboard.

With `group=motion` the gallery lists topics: one card per topic (services/motions), whose cover
is the version that earned the topic its place in this sort — the most trending, the newest or
the most liked one among those matching the filters — and topics rank by that version."""

from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import ColumnElement, Float, Select, and_, case, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only, selectinload

from app.api.serializers import debater_models, detail_out, gallery_item_out, topic_context
from app.core.auth import get_current_user
from app.core.db import get_db
from app.models.models import Debate, DebateParticipant, DebateVote, User, utcnow
from app.schemas.schemas import (
    GALLERY_CATEGORIES,
    DebateDetail,
    GalleryGroup,
    GalleryPeriod,
    GalleryResponse,
    GallerySort,
    LeaderboardEntry,
    LeaderboardOut,
)
from app.services import motions, ranking
from app.services.engagement import engagement_out
from app.services.free_router import is_free_router
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


def premium_voices_sql() -> ColumnElement[bool]:
    """SQL twin of `serializers.has_premium_voices`."""
    return and_(
        Debate.media_status == "ready",
        Debate.media_json[("options", "provider")].as_string() == "elevenlabs",
    )


def trending_sql() -> ColumnElement[Any]:
    """SQL twin of `ranking.trending_score`."""
    age_hours = func.extract("epoch", func.now() - _published_at()) / 3600.0
    engagement = (
        Debate.likes_count * ranking.LIKE_WEIGHT
        + Debate.votes_count * ranking.VOTE_WEIGHT
        + func.ln(Debate.views + 1)
        + 1
        + case((premium_voices_sql(), ranking.PREMIUM_VOICES_BONUS), else_=0.0)
    )
    return engagement / func.power(
        func.greatest(age_hours, 0) + ranking.TRENDING_OFFSET_HOURS, ranking.TRENDING_GRAVITY
    )


def _public() -> list[ColumnElement[bool]]:
    return motions.public_clause()


def _sort_keys(sort: GallerySort) -> list[tuple[str, Any]]:
    """(label, expression) of a sort, most important first; higher is better for each."""
    published = _published_at()
    if sort == "trending":
        return [("score", trending_sql()), ("published", published)]
    if sort == "top":
        return [
            ("likes", Debate.likes_count),
            ("votes", Debate.votes_count),
            ("views", Debate.views),
            ("published", published),
        ]
    return [("published", published), ("created", Debate.created_at)]


def _group() -> ColumnElement[Any]:
    """A debate's topic; one without a topic is a group of its own."""
    return func.coalesce(Debate.motion_id, Debate.id)


def covers_query(conditions: list[ColumnElement[bool]], sort: GallerySort) -> Select[Any]:
    """Ids of the topics' covers in gallery order: the best version per topic under these
    filters (row_number over the topic), topics ranked by it; in trending a topic with more
    matching versions gets `ranking.topic_trending_score`'s bonus."""
    group = _group()
    keys = _sort_keys(sort)
    within = [expr.desc().nulls_last() for _, expr in keys]
    ranked = (
        select(
            Debate.id.label("id"),
            func.row_number().over(partition_by=group, order_by=[*within, Debate.id]).label("rn"),
            func.count().over(partition_by=group).label("versions"),
            *[expr.label(label) for label, expr in keys],
        )
        .where(*conditions)
        .subquery()
    )
    order: list[Any] = []
    for i, (label, _expr) in enumerate(keys):
        column = ranked.c[label]
        if i == 0 and sort == "trending":
            versions = cast(ranked.c.versions, Float)
            column = column * (1 + ranking.VERSIONS_BONUS * func.ln(versions))
        order.append(column.desc().nulls_last())
    return select(ranked.c.id).where(ranked.c.rn == 1).order_by(*order, ranked.c.id)


async def _grouped(
    db: AsyncSession,
    conditions: list[ColumnElement[bool]],
    sort: GallerySort,
    limit: int,
    offset: int,
) -> tuple[list[Debate], int]:
    """One debate per topic (the cover) and the number of topics."""
    query = covers_query(conditions, sort).limit(limit).offset(offset)
    covers = (await db.execute(query)).scalars().all()
    total = await db.scalar(select(func.count(func.distinct(_group()))).where(*conditions)) or 0
    if not covers:
        return [], int(total)
    rows = (
        await db.scalars(
            select(Debate)
            .options(selectinload(Debate.participants), selectinload(Debate.user))
            .where(Debate.id.in_(covers))
        )
    ).all()
    by_id = {d.id: d for d in rows}
    return [by_id[i] for i in covers if i in by_id], int(total)


@router.get("", response_model=GalleryResponse)
async def list_gallery(
    category: str | None = Query(None, max_length=40),
    q: str | None = Query(None, max_length=200),
    model: str | None = Query(None, max_length=200, description="Debates this model argued in"),
    premium_voices: bool = Query(False, description="Only debates voiced by ElevenLabs"),
    sort: GallerySort = Query("new"),
    group: GalleryGroup = Query("none", description="motion: one card per topic"),
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
    if premium_voices:
        conditions.append(premium_voices_sql())
    if sort == "top" and period in PERIODS:
        conditions.append(_published_at() >= utcnow() - PERIODS[period])

    if group == "motion":
        debates, total = await _grouped(db, conditions, sort, limit, offset)
        infos = await motions.motion_infos(db, [d.motion_id for d in debates])
        return GalleryResponse(
            items=[
                gallery_item_out(d, infos.get(d.motion_id) if d.motion_id else None)
                for d in debates
            ],
            total=total,
        )

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
    infos = await motions.motion_infos(db, [d.motion_id for d in debates])
    return GalleryResponse(
        items=[
            gallery_item_out(d, infos.get(d.motion_id) if d.motion_id else None) for d in debates
        ],
        total=int(total),
    )


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
                    load_only(Debate.id, Debate.verdict_json, Debate.totals_json),
                    selectinload(Debate.participants),
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

    # Debates from before the Free Router pinned its models keep the router itself: a random
    # free model per turn is no contender, so it is left out (its opponents get no contest).
    records = [
        ranking.DebateRecord(
            models={p: m for p, m in debater_models(d).items() if not is_free_router(m)},
            votes=votes.get(d.id, {}),
            judge_winner=(d.verdict_json or {}).get("winner_id"),
            claims=(d.totals_json or {}).get("claims") or {},
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
                rated=s.rated,
                debates=s.debates,
                votes=s.votes,
                vote_share=s.vote_share,
                audience_wins=s.audience_wins,
                audience_contests=s.audience_contests,
                judge_wins=s.judge_wins,
                judge_contests=s.judge_contests,
                claims_checked=s.claims_checked,
                claims_verified=s.claims_verified,
                claims_disputed=s.claims_disputed,
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
    motion, remix_of = await topic_context(db, debate)
    return detail_out(
        debate,
        viewer,
        await engagement_out(db, debate, viewer),
        motion=motion,
        remix_of=remix_of,
    )
