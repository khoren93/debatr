"""Debates in the admin console: the list (search, filters, sorting), the debate card, the
moderation queue and the trending batches.

The list joins per-debate totals computed in SQL (turns, provider cost on the system keys,
credits charged) so filters and sorts work across pages; money columns are left out for roles
without the `money` permission. The card's per-turn summary (`turn_row`) and the trending
batch summary (`batch_row`) are pure.
"""

import uuid
from collections import Counter
from collections.abc import Mapping
from datetime import timedelta
from typing import Any

from redis.asyncio import Redis as AsyncRedis
from redis.exceptions import RedisError
from sqlalchemy import Select, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.core.redis import (
    debate_beat_key,
    media_beat_key,
    provider_key_key,
    recovery_key,
    stop_flag_key,
    tts_key_key,
)
from app.models.models import (
    AdminAuditLog,
    CreditTransaction,
    Debate,
    DebateParticipant,
    ProviderUsage,
    TrendingBatch,
    TrendingTopic,
    Turn,
    User,
)
from app.schemas.admin import DebateFilters, DebateSort
from app.services import motions
from app.services.admin.stats import ledger_category
from app.services.admin.users import audit_out, day_start, ledger_row_out, like_pattern, public_url
from app.services.debate_control import ACTIVE_STATUSES
from app.services.moderation import wants_public
from app.services.resume import resume_point
from app.services.studio import turn_visuals_out

AUDIT_ROWS = 50
DECISIONS = ("moderation.approved", "moderation.rejected")
SECRET_CONFIG_KEYS = frozenset({"user_provider_key", "user_tts_key", "api_key", "key"})


def _usd(value: Any) -> float:
    return round(float(value or 0), 6)


def own_key_column() -> ColumnElement[bool]:
    """`config_json.billing.own_key` is true (the run used the owner's OpenRouter key)."""
    flag = Debate.config_json[("billing", "own_key")].as_string()
    return func.coalesce(flag, "false") == "true"


# --- the list ---------------------------------------------------------------------------------


def search_condition(q: str) -> ColumnElement[bool] | None:
    text = q.strip()
    if not text:
        return None
    try:
        return Debate.id == uuid.UUID(text)
    except ValueError:
        return or_(Debate.title.ilike(like_pattern(text), escape="\\"), Debate.slug == text)


def filter_conditions(filters: DebateFilters) -> list[ColumnElement[bool]]:
    out: list[ColumnElement[bool]] = []
    found = search_condition(filters.q)
    if found is not None:
        out.append(found)
    if filters.status is not None:
        out.append(Debate.status == filters.status)
    if filters.active is not None:
        active = Debate.status.in_(ACTIVE_STATUSES)
        out.append(active if filters.active else ~active)
    if filters.failed is not None:
        failed = Debate.status == "error"
        out.append(failed if filters.failed else ~failed)
    if filters.moderation is not None:
        out.append(Debate.moderation_status == filters.moderation)
    if filters.media is not None:
        out.append(Debate.media_status == filters.media)
    if filters.public is not None:
        out.append(Debate.is_public.is_(filters.public))
    if filters.own_key is not None:
        own = own_key_column()
        out.append(own if filters.own_key else ~own)
    if filters.via_token is not None:
        token = Debate.api_token_id
        out.append(token.is_not(None) if filters.via_token else token.is_(None))
    if filters.model:
        out.append(
            exists().where(
                DebateParticipant.debate_id == Debate.id,
                DebateParticipant.role == "debater",
                DebateParticipant.model_id == filters.model,
            )
        )
    if filters.user_id is not None:
        out.append(Debate.user_id == filters.user_id)
    if filters.created_from is not None:
        out.append(Debate.created_at >= day_start(filters.created_from))
    if filters.created_to is not None:
        out.append(Debate.created_at < day_start(filters.created_to) + timedelta(days=1))
    return out


def debates_query(
    filters: DebateFilters, sort: DebateSort, descending: bool
) -> Select[*tuple[Any, ...]]:
    """Debates with their owner and totals, filtered and sorted (no limit yet)."""
    turns = (
        select(Turn.debate_id.label("debate_id"), func.count().label("turns"))
        .group_by(Turn.debate_id)
        .subquery("turn_counts")
    )
    costs = (
        select(
            ProviderUsage.debate_id.label("debate_id"),
            func.sum(ProviderUsage.cost_usd).label("cost"),
        )
        .where(ProviderUsage.debate_id.is_not(None), ProviderUsage.key_owner == "system")
        .group_by(ProviderUsage.debate_id)
        .subquery("costs")
    )
    charges = (
        select(
            CreditTransaction.debate_id.label("debate_id"),
            func.sum(-CreditTransaction.amount_usd).label("charged"),
        )
        .where(CreditTransaction.debate_id.is_not(None))
        .group_by(CreditTransaction.debate_id)
        .subquery("charges")
    )
    totals: dict[str, Any] = {
        "turns": func.coalesce(turns.c.turns, 0),
        "cost": func.coalesce(costs.c.cost, 0),
        "charged": func.coalesce(charges.c.charged, 0),
    }
    sorts: dict[str, Any] = {
        "created": Debate.created_at,
        "likes": Debate.likes_count,
        "views": Debate.views,
        **totals,
    }
    column = sorts[sort]
    order = column.desc() if descending else column.asc()
    columns: list[Any] = [
        Debate,
        User.email.label("owner_email"),
        User.display_name.label("owner_name"),
        own_key_column().label("own_key"),
        *(value.label(name) for name, value in totals.items()),
    ]
    return (
        select(*columns)
        .outerjoin(User, User.id == Debate.user_id)
        .outerjoin(turns, turns.c.debate_id == Debate.id)
        .outerjoin(costs, costs.c.debate_id == Debate.id)
        .outerjoin(charges, charges.c.debate_id == Debate.id)
        .where(*filter_conditions(filters))
        .order_by(order.nulls_last(), Debate.id)
    )


async def debaters(db: AsyncSession, ids: list[uuid.UUID]) -> dict[uuid.UUID, list[str]]:
    if not ids:
        return {}
    rows = await db.execute(
        select(DebateParticipant.debate_id, DebateParticipant.model_id)
        .where(DebateParticipant.debate_id.in_(ids), DebateParticipant.role == "debater")
        .order_by(DebateParticipant.id)
    )
    out: dict[uuid.UUID, list[str]] = {}
    for debate_id, model in rows.all():
        out.setdefault(debate_id, []).append(str(model))
    return out


def duration_ms(debate: Debate) -> int | None:
    if debate.started_at is None or debate.ended_at is None:
        return None
    return max(0, int((debate.ended_at - debate.started_at).total_seconds() * 1000))


def row_out(
    debate: Debate, extra: Mapping[Any, Any], models: list[str], *, with_money: bool
) -> dict[str, Any]:
    owner = (
        {
            "id": str(debate.user_id),
            "email": extra["owner_email"],
            "display_name": extra["owner_name"],
        }
        if debate.user_id is not None and extra.get("owner_email")
        else None
    )
    return {
        "id": str(debate.id),
        "title": debate.title or "Untitled debate",
        "owner": owner,
        "status": debate.status,
        "models": models,
        "created_at": debate.created_at,
        "started_at": debate.started_at,
        "ended_at": debate.ended_at,
        "duration_ms": duration_ms(debate),
        "turns": int(extra.get("turns") or 0),
        "cost": _usd(extra.get("cost")) if with_money else None,
        "charged": _usd(extra.get("charged")) if with_money else None,
        "own_key": bool(extra.get("own_key")),
        "via_token": debate.api_token_id is not None,
        "is_public": debate.is_public,
        "url": public_url(debate),
        "moderation_status": debate.moderation_status or "none",
        "media_status": debate.media_status or "none",
        "views": debate.views or 0,
        "likes": debate.likes_count or 0,
        "votes": debate.votes_count or 0,
        "error": (debate.error_message or "")[:300] or None,
    }


async def list_debates(
    db: AsyncSession,
    filters: DebateFilters,
    *,
    sort: DebateSort,
    descending: bool,
    limit: int,
    offset: int,
    with_money: bool,
) -> tuple[int, list[dict[str, Any]]]:
    query = debates_query(filters, sort, descending)
    total = await db.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
    rows = (await db.execute(query.limit(limit).offset(offset))).all()
    models = await debaters(db, [row[0].id for row in rows])
    return int(total or 0), [
        row_out(row[0], row._mapping, models.get(row[0].id, []), with_money=with_money)
        for row in rows
    ]


async def debate_row(db: AsyncSession, debate_id: uuid.UUID, *, with_money: bool) -> Any:
    """One debate as a list row (None when it does not exist)."""
    query = debates_query(DebateFilters(), "created", True).where(Debate.id == debate_id)
    row = (await db.execute(query)).first()
    if row is None:
        return None
    models = await debaters(db, [debate_id])
    return row[0], row_out(row[0], row._mapping, models.get(debate_id, []), with_money=with_money)


# --- the card ---------------------------------------------------------------------------------


def clean_config(config: dict[str, Any]) -> dict[str, Any]:
    """The stored config without anything key-like (keys are never stored; belt and braces)."""

    def scrub(value: Any) -> Any:
        if isinstance(value, dict):
            return {k: scrub(v) for k, v in value.items() if str(k) not in SECRET_CONFIG_KEYS}
        if isinstance(value, list):
            return [scrub(v) for v in value]
        return value

    return scrub(config)


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def turn_row(turn: Turn) -> dict[str, Any]:
    usage = turn.usage_json or {}
    visuals = turn_visuals_out(turn)
    checks = Counter(
        str(scene.check.verdict) for scene in (visuals.scenes if visuals else []) if scene.check
    )
    return {
        "seq_index": turn.seq_index,
        "round_id": turn.round_id,
        "turn_type": turn.turn_type,
        "speaker_name": turn.speaker_name,
        "model_used": turn.model_used,
        "text": turn.text or "",
        "error": turn.error,
        "created_at": turn.created_at,
        "tokens_in": int(usage.get("prompt_tokens") or 0),
        "tokens_out": int(usage.get("completion_tokens") or 0),
        "cost": _usd(usage.get("cost")),
        "duration_ms": _int_or_none(usage.get("duration_ms")),
        "ttft_ms": _int_or_none(usage.get("ttft_ms")),
        "error_kind": usage.get("error_kind"),
        "visuals_status": visuals.status if visuals else "none",
        "scenes": len(visuals.scenes) if visuals else 0,
        "checks": dict(checks),
        "disputes": len(visuals.disputes) if visuals else 0,
    }


def media_out(debate: Debate) -> dict[str, Any]:
    state = dict(debate.media_json or {})
    keep = (
        "options",
        "step",
        "message",
        "error",
        "current",
        "total",
        "started_at",
        "finished_at",
        "stats",
        "renders",
        "auto",
        "free",
        "own_tts_key",
    )
    return {"status": debate.media_status or "none", **{k: state.get(k) for k in keep}}


def refundable(charged_net: float) -> float:
    """What a refund may still give back: the debate's net charge, never below zero."""
    return max(0.0, round(charged_net, 6))


def can_resume(debate: Debate, own_key: bool) -> bool:
    """An admin resumes on the system key only: a run on the owner's key would bill us."""
    return (
        debate.status == "error"
        and not own_key
        and debate.media_status not in ("queued", "running")
    )


async def recovery_state(redis: AsyncRedis, debate_id: str) -> dict[str, Any]:
    async def present(key: str) -> bool:
        return bool(await redis.exists(key))

    async def number(key: str) -> int:
        raw = await redis.get(key)
        return _int_or_none(raw.decode() if isinstance(raw, bytes) else raw) or 0

    try:
        return {
            "debate_beat": await present(debate_beat_key(debate_id)),
            "media_beat": await present(media_beat_key(debate_id)),
            "debate_attempts": await number(recovery_key("attempts:debate", debate_id)),
            "media_attempts": await number(recovery_key("attempts:media", debate_id)),
            "stop_flag": await present(stop_flag_key(debate_id)),
            "provider_key": await present(provider_key_key(debate_id)),
            "tts_key": await present(tts_key_key(debate_id)),
        }
    except RedisError:
        return {
            "debate_beat": False,
            "media_beat": False,
            "debate_attempts": 0,
            "media_attempts": 0,
            "stop_flag": False,
            "provider_key": False,
            "tts_key": False,
        }


async def usage_by_purpose(db: AsyncSession, debate_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = await db.execute(
        select(
            ProviderUsage.purpose,
            ProviderUsage.key_owner,
            func.count(),
            func.count().filter(ProviderUsage.ok.is_(False)),
            func.sum(ProviderUsage.cost_usd),
        )
        .where(ProviderUsage.debate_id == debate_id)
        .group_by(ProviderUsage.purpose, ProviderUsage.key_owner)
        .order_by(func.sum(ProviderUsage.cost_usd).desc())
    )
    return [
        {
            "purpose": str(purpose),
            "key_owner": str(owner),
            "calls": int(calls),
            "failures": int(failures),
            "cost": _usd(cost),
        }
        for purpose, owner, calls, failures, cost in rows.all()
    ]


async def debate_ledger(db: AsyncSession, debate_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = await db.execute(
        select(CreditTransaction, ledger_category())
        .where(CreditTransaction.debate_id == debate_id)
        .order_by(CreditTransaction.created_at.desc())
    )
    return [ledger_row_out(tx, str(category)) for tx, category in rows.all()]


async def debate_audit(db: AsyncSession, debate_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = await db.scalars(
        select(AdminAuditLog)
        .where(AdminAuditLog.target_type == "debate", AdminAuditLog.target_id == str(debate_id))
        .order_by(AdminAuditLog.created_at.desc())
        .limit(AUDIT_ROWS)
    )
    return [audit_out(entry) for entry in rows.all()]


async def debate_card(
    db: AsyncSession, redis: AsyncRedis, debate: Debate, row: dict[str, Any], *, with_money: bool
) -> dict[str, Any]:
    turns = list(
        (
            await db.scalars(
                select(Turn).where(Turn.debate_id == debate.id).order_by(Turn.seq_index)
            )
        ).all()
    )
    config = dict(debate.config_json or {})
    own_key = bool((config.get("billing") or {}).get("own_key"))
    return {
        "debate": row,
        "motion": await motions.motion_summary(db, debate.motion_id),
        "topic": str(config.get("topic") or debate.title or ""),
        "config": clean_config(config),
        "totals": dict(debate.totals_json or {}),
        "turns": [turn_row(t) for t in turns],
        "verdict": dict(debate.verdict_json or {}),
        "moderation": dict(debate.moderation_json or {}),
        "wants_public": wants_public(debate),
        "media": media_out(debate),
        "recovery": await recovery_state(redis, str(debate.id)),
        "usage": await usage_by_purpose(db, debate.id) if with_money else None,
        "ledger": await debate_ledger(db, debate.id) if with_money else None,
        "refundable": refundable(row["charged"] or 0.0) if with_money else None,
        "resume_from": resume_point(turns) if can_resume(debate, own_key) else None,
        "audit": await debate_audit(db, debate.id),
    }


# --- moderation -------------------------------------------------------------------------------


async def moderation_queue(db: AsyncSession, recent: int = 30) -> dict[str, Any]:
    flagged = (
        await db.execute(
            select(Debate, User.email, User.display_name)
            .outerjoin(User, User.id == Debate.user_id)
            .where(Debate.moderation_status == "flagged")
            .order_by(Debate.ended_at.asc().nulls_last(), Debate.created_at.asc())
        )
    ).all()
    models = await debaters(db, [d.id for d, _, _ in flagged])
    items = []
    for debate, email, name in flagged:
        raw = debate.moderation_json or {}
        items.append(
            {
                "id": str(debate.id),
                "title": debate.title or "Untitled debate",
                "owner": {"id": str(debate.user_id), "email": email, "display_name": name}
                if debate.user_id and email
                else None,
                "models": models.get(debate.id, []),
                "created_at": debate.created_at,
                "ended_at": debate.ended_at,
                "reason": raw.get("reason") or None,
                "source": raw.get("source") or None,
                "checked_at": raw.get("checked_at") or None,
                "publish_requested": wants_public(debate),
            }
        )
    entries = list(
        (
            await db.scalars(
                select(AdminAuditLog)
                .where(AdminAuditLog.action.in_(DECISIONS))
                .order_by(AdminAuditLog.created_at.desc())
                .limit(recent)
            )
        ).all()
    )
    ids = []
    for entry in entries:
        try:
            ids.append(uuid.UUID(entry.target_id or ""))
        except ValueError:
            continue
    titles = {
        str(did): title
        for did, title in (
            await db.execute(select(Debate.id, Debate.title).where(Debate.id.in_(ids)))
        ).all()
    }
    decisions = [
        {
            "debate_id": entry.target_id,
            "title": titles.get(entry.target_id or ""),
            "action": entry.action,
            "actor_email": entry.actor_email,
            "reason": entry.reason,
            "created_at": entry.created_at,
        }
        for entry in entries
    ]
    return {"flagged": items, "recent": decisions}


# --- trending ---------------------------------------------------------------------------------


def batch_row(batch: TrendingBatch, hidden: int, current: bool) -> dict[str, Any]:
    stats: dict[str, Any] = batch.stats_json or {}

    def stat(name: str) -> int | None:
        return _int_or_none(stats.get(name))

    return {
        "id": str(batch.id),
        "created_at": batch.created_at,
        "model": batch.model,
        "topic_count": batch.topic_count,
        "hidden": hidden,
        "cost_usd": _usd(batch.cost_usd),
        "current": current,
        "feeds_ok": stat("feeds_ok"),
        "feeds_total": stat("feeds_total"),
        "headlines_fresh": stat("headlines_fresh"),
        "headlines_blocked": stat("headlines_blocked"),
        "headlines_sent": stat("headlines_sent"),
        "topics_asked": stat("topics_asked"),
        "dropped": len(stats.get("dropped") or []),
    }


def _hidden_counts() -> Any:
    return (
        select(TrendingTopic.batch_id, func.count().label("hidden"))
        .where(TrendingTopic.is_hidden.is_(True))
        .group_by(TrendingTopic.batch_id)
        .subquery("hidden")
    )


async def newest_batch_id(db: AsyncSession) -> uuid.UUID | None:
    return await db.scalar(
        select(TrendingBatch.id).order_by(TrendingBatch.created_at.desc()).limit(1)
    )


async def trending_batches(
    db: AsyncSession, *, limit: int, offset: int
) -> tuple[int, list[dict[str, Any]]]:
    hidden = _hidden_counts()
    total = await db.scalar(select(func.count()).select_from(TrendingBatch))
    newest = await newest_batch_id(db)
    rows = await db.execute(
        select(TrendingBatch, func.coalesce(hidden.c.hidden, 0))
        .outerjoin(hidden, hidden.c.batch_id == TrendingBatch.id)
        .order_by(TrendingBatch.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return int(total or 0), [
        batch_row(batch, int(n), batch.id == newest) for batch, n in rows.all()
    ]


def topic_out(topic: TrendingTopic) -> dict[str, Any]:
    return {
        "id": str(topic.id),
        "rank": topic.rank,
        "label": topic.label,
        "question": topic.question,
        "brief": topic.brief or "",
        "category": topic.category,
        "heat": topic.heat,
        "outlets": topic.outlets,
        "sources": [s for s in topic.sources_json or [] if isinstance(s, dict)],
        "is_hidden": topic.is_hidden,
    }


async def trending_batch(db: AsyncSession, batch_id: uuid.UUID) -> dict[str, Any] | None:
    batch = await db.get(TrendingBatch, batch_id)
    if batch is None:
        return None
    topics = list(
        (
            await db.scalars(
                select(TrendingTopic)
                .where(TrendingTopic.batch_id == batch_id)
                .order_by(TrendingTopic.rank)
            )
        ).all()
    )
    stats: dict[str, Any] = batch.stats_json or {}
    hidden = sum(1 for t in topics if t.is_hidden)
    return {
        "batch": batch_row(batch, hidden, batch.id == await newest_batch_id(db)),
        "topics": [topic_out(t) for t in topics],
        "dropped": [d for d in stats.get("dropped") or [] if isinstance(d, dict)],
        "blocked": [b for b in stats.get("blocked") or [] if isinstance(b, dict)],
    }


def recently_viewed_key(admin_id: uuid.UUID, debate_id: uuid.UUID) -> str:
    """Set for an hour after an admin opened a private debate (one audit row, not one a click)."""
    return f"admin:viewed:{admin_id}:{debate_id}"


def is_private(debate: Debate) -> bool:
    return not debate.is_public and debate.user_id is not None
