"""Accounts in the admin console: the list (search, filters, sorting, CSV), the account card and
the data side of the changes an admin makes (app/api/admin/routes_users.py records them).

The list computes its totals in SQL (ledger, debates, tokens per account), so filters and sorts
on them work across pages. The card reads one account's rows and builds its statistics with pure
functions (`period_stats`, `favorite_models`, `spend_days`), as does the CSV.
"""

import csv
import io
import secrets
import uuid
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy import Select, and_, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.core.config import settings
from app.core.security import mask_key
from app.models.models import (
    AdminAuditLog,
    ApiToken,
    CreditTransaction,
    Debate,
    DebateLike,
    DebateParticipant,
    DebateVote,
    ProviderUsage,
    User,
)
from app.schemas.admin import UserFilters, UserSort
from app.services import ledger
from app.services.admin.audit import entry_out
from app.services.admin.stats import ledger_category
from app.services.debate_control import ACTIVE_STATUSES
from app.services.engagement import recount

CHARGE_KINDS = ("debate", "media")
CREDIT_KINDS = ("bonus", "refund")
SPEND_CATEGORIES = ("models", "voices", "pictures", "music", "cover")
FINISHED = ("completed", "error", "stopped")
FREE_ROUTER = "openrouter/free"
LIST_LIMIT = 200
EXPORT_LIMIT = 20_000
CARD_DAYS = 30
AUDIT_ROWS = 50
# Characters of a temporary password: no look-alikes (0/o, 1/l/i).
PASSWORD_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"


# --- search and filters -------------------------------------------------------------------------


def like_pattern(text: str) -> str:
    """`%text%` for ILIKE with the wildcards of the text itself escaped."""
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def search_condition(q: str) -> ColumnElement[bool] | None:
    """An exact id, or email / name containing the text."""
    text = q.strip()
    if not text:
        return None
    try:
        return User.id == uuid.UUID(text)
    except ValueError:
        pattern = like_pattern(text)
        return or_(
            User.email.ilike(pattern, escape="\\"), User.display_name.ilike(pattern, escape="\\")
        )


def day_start(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=UTC)


def _ledger_totals() -> Any:
    category = ledger_category()
    charge = -CreditTransaction.amount_usd
    return (
        select(
            CreditTransaction.user_id.label("user_id"),
            func.sum(CreditTransaction.amount_usd)
            .filter(CreditTransaction.kind == "topup")
            .label("topped_up"),
            func.sum(charge).filter(CreditTransaction.kind.in_(CHARGE_KINDS)).label("spent"),
            *(
                func.sum(charge).filter(category == name).label(f"spent_{name}")
                for name in SPEND_CATEGORIES
            ),
        )
        .group_by(CreditTransaction.user_id)
        .subquery("ledger")
    )


def _debate_totals() -> Any:
    return (
        select(
            Debate.user_id.label("user_id"),
            func.count().label("debates"),
            func.count().filter(Debate.status == "error").label("failed"),
            func.count().filter(Debate.is_public.is_(True)).label("public"),
            func.sum(Debate.likes_count).label("likes"),
            func.sum(Debate.votes_count).label("votes"),
        )
        .where(Debate.user_id.is_not(None), Debate.status != "draft")
        .group_by(Debate.user_id)
        .subquery("debates")
    )


def _token_totals(now: datetime) -> Any:
    return (
        select(ApiToken.user_id.label("user_id"), func.count().label("tokens"))
        .where(or_(ApiToken.expires_at.is_(None), ApiToken.expires_at > now))
        .group_by(ApiToken.user_id)
        .subquery("tokens")
    )


def filter_conditions(
    filters: UserFilters, totals: Mapping[str, ColumnElement[Any]], now: datetime
) -> list[ColumnElement[bool]]:
    out: list[ColumnElement[bool]] = []
    found = search_condition(filters.q)
    if found is not None:
        out.append(found)
    if filters.paid is not None:
        out.append(totals["topped_up"] > 0 if filters.paid else totals["topped_up"] <= 0)
    if filters.balance == "positive":
        out.append(User.credits_usd > 0)
    elif filters.balance == "negative":
        out.append(User.credits_usd < 0)
    if filters.own_key is not None:
        key = User.openrouter_key_enc
        out.append(key.is_not(None) if filters.own_key else key.is_(None))
    if filters.tokens is not None:
        out.append(totals["tokens"] > 0 if filters.tokens else totals["tokens"] == 0)
    if filters.status is not None:
        out.append(User.is_active.is_(filters.status == "active"))
    if filters.staff is not None:
        role = User.admin_role
        out.append(role.is_not(None) if filters.staff else role.is_(None))
    if filters.created_from is not None:
        out.append(User.created_at >= day_start(filters.created_from))
    if filters.created_to is not None:
        out.append(User.created_at < day_start(filters.created_to) + timedelta(days=1))
    if filters.active_days is not None:
        out.append(User.last_seen_at >= now - timedelta(days=filters.active_days))
    return out


def users_query(
    filters: UserFilters, sort: UserSort, descending: bool, now: datetime
) -> Select[Any]:
    """Accounts with their totals, filtered and sorted (no limit yet)."""
    money, runs, tokens = _ledger_totals(), _debate_totals(), _token_totals(now)
    totals: dict[str, ColumnElement[Any]] = {
        "topped_up": func.coalesce(money.c.topped_up, 0),
        "spent": func.coalesce(money.c.spent, 0),
        **{f"spent_{n}": func.coalesce(money.c[f"spent_{n}"], 0) for n in SPEND_CATEGORIES},
        "debates": func.coalesce(runs.c.debates, 0),
        "failed": func.coalesce(runs.c.failed, 0),
        "public": func.coalesce(runs.c.public, 0),
        "likes": func.coalesce(runs.c.likes, 0),
        "votes": func.coalesce(runs.c.votes, 0),
        "tokens": func.coalesce(tokens.c.tokens, 0),
    }
    sorts: dict[str, Any] = {
        "created": User.created_at,
        "last_seen": User.last_seen_at,
        "balance": User.credits_usd,
        "email": User.email,
        "topped_up": totals["topped_up"],
        "spent": totals["spent"],
        "debates": totals["debates"],
        "likes": totals["likes"],
    }
    column = sorts[sort]
    order = column.desc() if descending else column.asc()
    return (
        select(User, *(value.label(name) for name, value in totals.items()))
        .outerjoin(money, money.c.user_id == User.id)
        .outerjoin(runs, runs.c.user_id == User.id)
        .outerjoin(tokens, tokens.c.user_id == User.id)
        .where(*filter_conditions(filters, totals, now))
        .order_by(order.nulls_last(), User.id)
    )


def _usd(value: Any) -> float:
    return round(float(value or 0), 6)


def row_out(user: User, totals: Mapping[Any, Any]) -> dict[str, Any]:
    return {
        "id": str(user.id),
        "email": user.email,
        "display_name": user.display_name,
        "created_at": user.created_at,
        "last_login_at": user.last_login_at,
        "last_seen_at": user.last_seen_at,
        "is_active": user.is_active,
        "role": user.admin_role,
        "credits_usd": _usd(user.credits_usd),
        "own_key": user.openrouter_key_enc is not None,
        "tokens": int(totals["tokens"] or 0),
        "topped_up": _usd(totals["topped_up"]),
        "spent": _usd(totals["spent"]),
        "spent_by": {n: _usd(totals[f"spent_{n}"]) for n in SPEND_CATEGORIES},
        "debates": int(totals["debates"] or 0),
        "failed": int(totals["failed"] or 0),
        "public": int(totals["public"] or 0),
        "likes": int(totals["likes"] or 0),
        "votes": int(totals["votes"] or 0),
    }


async def list_users(
    db: AsyncSession,
    filters: UserFilters,
    *,
    sort: UserSort,
    descending: bool,
    limit: int,
    offset: int,
    now: datetime,
) -> tuple[int, list[dict[str, Any]]]:
    query = users_query(filters, sort, descending, now)
    total = await db.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
    rows = await db.execute(query.limit(limit).offset(offset))
    return int(total or 0), [row_out(row[0], row._mapping) for row in rows.all()]


CSV_HEADER = [
    "id",
    "email",
    "name",
    "created_utc",
    "last_seen_utc",
    "status",
    "role",
    "balance_usd",
    "topped_up_usd",
    "spent_usd",
    "spent_models_usd",
    "spent_voices_usd",
    "spent_pictures_usd",
    "spent_music_usd",
    "spent_cover_usd",
    "debates",
    "failed",
    "public",
    "likes_received",
    "votes_received",
    "own_openrouter_key",
    "api_tokens",
]


def _csv_time(value: datetime | None) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S") if value else ""


def users_csv(rows: Iterable[Mapping[str, Any]]) -> str:
    """The list as CSV; text cells cannot start a spreadsheet formula (ledger.text_cell)."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(CSV_HEADER)
    for row in rows:
        spent_by = row["spent_by"]
        writer.writerow(
            [
                row["id"],
                ledger.text_cell(row["email"]),
                ledger.text_cell(row["display_name"]),
                _csv_time(row["created_at"]),
                _csv_time(row["last_seen_at"]),
                "active" if row["is_active"] else "disabled",
                row["role"] or "",
                f"{row['credits_usd']:.6f}",
                f"{row['topped_up']:.6f}",
                f"{row['spent']:.6f}",
                *(f"{spent_by[n]:.6f}" for n in SPEND_CATEGORIES),
                row["debates"],
                row["failed"],
                row["public"],
                row["likes"],
                row["votes"],
                "yes" if row["own_key"] else "no",
                row["tokens"],
            ]
        )
    return buffer.getvalue()


# --- the account card (pure statistics) ---------------------------------------------------------


@dataclass(frozen=True)
class DebateFacts:
    id: uuid.UUID
    created_at: datetime
    status: str
    models: tuple[str, ...]  # debaters
    own_key: bool
    via_token: bool
    tokens_in: int
    tokens_out: int


@dataclass(frozen=True)
class TxFacts:
    created_at: datetime
    kind: str
    category: str
    amount: float


def is_free_model(model_id: str) -> bool:
    return model_id == FREE_ROUTER or model_id.endswith(":free")


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def period_stats(
    debates: Iterable[DebateFacts],
    txs: Iterable[TxFacts],
    *,
    since: datetime | None,
    cost_system: float,
) -> dict[str, Any]:
    """One account's numbers since `since` (None: all time). Drafts are not runs."""
    runs = [
        d
        for d in debates
        if d.status != "draft" and (since is None or _aware(d.created_at) >= since)
    ]
    rows = [t for t in txs if since is None or _aware(t.created_at) >= since]
    by_status = Counter(d.status for d in runs)
    finished = sum(by_status[s] for s in FINISHED)
    spent_by = {
        name: round(
            sum(-t.amount for t in rows if t.kind in CHARGE_KINDS and t.category == name), 6
        )
        for name in SPEND_CATEGORIES
    }
    credited = sum(
        t.amount
        for t in rows
        if t.kind in CREDIT_KINDS or (t.kind == "adjustment" and t.amount > 0)
    )
    free = sum(1 for d in runs if d.models and all(is_free_model(m) for m in d.models))
    return {
        "debates": len(runs),
        "completed": by_status["completed"],
        "failed": by_status["error"],
        "stopped": by_status["stopped"],
        "error_rate": round(by_status["error"] / finished, 4) if finished else None,
        "free_debates": free,
        "paid_debates": len(runs) - free,
        "own_key_debates": sum(1 for d in runs if d.own_key),
        "token_debates": sum(1 for d in runs if d.via_token),
        "tokens_in": sum(d.tokens_in for d in runs),
        "tokens_out": sum(d.tokens_out for d in runs),
        "topped_up": round(sum(t.amount for t in rows if t.kind == "topup"), 6),
        "credited": round(credited, 6),
        "spent": round(sum(spent_by.values()), 6),
        "spent_by": spent_by,
        "avg_debate_cost": round(spent_by["models"] / finished, 6) if finished else None,
        "cost_system": round(cost_system, 6),
    }


def favorite_models(debates: Iterable[DebateFacts], limit: int = 5) -> list[dict[str, Any]]:
    """Debater models by the number of the account's debates they argued in."""
    counts: Counter[str] = Counter()
    for d in debates:
        if d.status != "draft":
            counts.update(set(d.models))
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [{"model": model, "debates": n} for model, n in ranked[:limit]]


def spend_days(
    txs: Iterable[TxFacts], now: datetime, days: int = CARD_DAYS
) -> list[dict[str, Any]]:
    """Charges per UTC day for the last `days` days (today included), by category."""
    today = now.astimezone(UTC).date()
    buckets: dict[date, dict[str, Any]] = {}
    for n in range(days - 1, -1, -1):
        day = today - timedelta(days=n)
        buckets[day] = {"day": day, **{name: 0.0 for name in SPEND_CATEGORIES}}
    for t in txs:
        bucket = buckets.get(_aware(t.created_at).date())
        if bucket is not None and t.kind in CHARGE_KINDS and t.category in SPEND_CATEGORIES:
            bucket[t.category] = round(bucket[t.category] - t.amount, 6)
    return list(buckets.values())


# --- the account card (queries) -----------------------------------------------------------------


def profile_out(user: User) -> dict[str, Any]:
    return {
        "id": str(user.id),
        "email": user.email,
        "display_name": user.display_name,
        "avatar_seed": user.avatar_seed or "",
        "created_at": user.created_at,
        "last_login_at": user.last_login_at,
        "last_seen_at": user.last_seen_at,
        "is_active": user.is_active,
        "role": user.admin_role,
        "two_factor": user.totp_enabled_at is not None,
        "credits_usd": _usd(user.credits_usd),
        "openrouter_key_masked": mask_key(user.openrouter_key_last4)
        if user.openrouter_key_enc
        else None,
    }


async def _debaters(db: AsyncSession, debate_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[str]]:
    if not debate_ids:
        return {}
    rows = await db.execute(
        select(DebateParticipant.debate_id, DebateParticipant.model_id)
        .where(DebateParticipant.debate_id.in_(debate_ids), DebateParticipant.role == "debater")
        .order_by(DebateParticipant.id)
    )
    out: dict[uuid.UUID, list[str]] = {}
    for debate_id, model in rows.all():
        out.setdefault(debate_id, []).append(str(model))
    return out


def _int(value: Any) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


async def debate_facts(db: AsyncSession, user_id: uuid.UUID) -> list[DebateFacts]:
    rows = (
        await db.execute(
            select(
                Debate.id,
                Debate.created_at,
                Debate.status,
                Debate.api_token_id,
                Debate.config_json[("billing", "own_key")].as_string(),
                Debate.totals_json["tokens_in"].as_string(),
                Debate.totals_json["tokens_out"].as_string(),
            ).where(Debate.user_id == user_id)
        )
    ).all()
    models = await _debaters(db, [row[0] for row in rows])
    return [
        DebateFacts(
            id=did,
            created_at=created,
            status=str(status),
            models=tuple(models.get(did, [])),
            own_key=own_key == "true",
            via_token=token_id is not None,
            tokens_in=_int(tokens_in),
            tokens_out=_int(tokens_out),
        )
        for did, created, status, token_id, own_key, tokens_in, tokens_out in rows
    ]


async def tx_facts(db: AsyncSession, user_id: uuid.UUID) -> list[TxFacts]:
    rows = await db.execute(
        select(
            CreditTransaction.created_at,
            CreditTransaction.kind,
            ledger_category(),
            CreditTransaction.amount_usd,
        ).where(CreditTransaction.user_id == user_id)
    )
    return [
        TxFacts(created_at=created, kind=str(kind), category=str(category), amount=float(amount))
        for created, kind, category, amount in rows.all()
    ]


async def system_cost(db: AsyncSession, user_id: uuid.UUID, since: datetime | None) -> float:
    query = select(func.coalesce(func.sum(ProviderUsage.cost_usd), 0)).where(
        ProviderUsage.user_id == user_id, ProviderUsage.key_owner == "system"
    )
    if since is not None:
        query = query.where(ProviderUsage.created_at >= since)
    return _usd(await db.scalar(query))


async def reactions(db: AsyncSession, user_id: uuid.UUID, limit: int = 5) -> dict[str, Any]:
    """Likes and votes the account gave, and whose debates got them."""
    owners: dict[uuid.UUID | None, dict[str, int]] = {}
    given = {"likes": 0, "votes": 0}
    for model, key in ((DebateLike, "likes"), (DebateVote, "votes")):
        rows = await db.execute(
            select(Debate.user_id, func.count())
            .select_from(model)
            .join(Debate, Debate.id == model.debate_id)
            .where(model.user_id == user_id)
            .group_by(Debate.user_id)
        )
        for owner_id, n in rows.all():
            owners.setdefault(owner_id, {"likes": 0, "votes": 0})[key] = int(n)
            given[key] += int(n)
    ranked = sorted(owners.items(), key=lambda item: -(item[1]["likes"] + item[1]["votes"]))
    top = ranked[:limit]
    ids = [owner_id for owner_id, _ in top if owner_id is not None]
    people = {
        uid: (email, name)
        for uid, email, name in (
            await db.execute(select(User.id, User.email, User.display_name).where(User.id.in_(ids)))
        ).all()
    }
    return {
        "likes_given": given["likes"],
        "votes_given": given["votes"],
        "owners": [
            {
                "user_id": str(owner_id) if owner_id else None,
                "email": people.get(owner_id, (None, None))[0] if owner_id else None,
                "display_name": people.get(owner_id, (None, None))[1] if owner_id else None,
                **counts,
            }
            for owner_id, counts in top
        ],
    }


def audit_out(entry: AdminAuditLog) -> dict[str, Any]:
    return entry_out(entry)


async def audit_entries(db: AsyncSession, user_id: uuid.UUID) -> list[dict[str, Any]]:
    """What was done to the account, and what it did as an admin, newest first."""
    rows = await db.scalars(
        select(AdminAuditLog)
        .where(
            or_(
                and_(AdminAuditLog.target_type == "user", AdminAuditLog.target_id == str(user_id)),
                AdminAuditLog.actor_user_id == user_id,
            )
        )
        .order_by(AdminAuditLog.created_at.desc())
        .limit(AUDIT_ROWS)
    )
    return [audit_out(entry) for entry in rows.all()]


async def count_debates(db: AsyncSession, user_id: uuid.UUID, *where: Any) -> int:
    query = select(func.count()).select_from(Debate).where(Debate.user_id == user_id, *where)
    return int(await db.scalar(query) or 0)


# --- ledger and debates pages -------------------------------------------------------------------


def ledger_row_out(tx: CreditTransaction, category: str) -> dict[str, Any]:
    meta = tx.meta_json or {}
    return {
        "id": str(tx.id),
        "created_at": tx.created_at,
        "kind": tx.kind,
        "category": category,
        "title": ledger.title(tx),
        "description": tx.description,
        "amount_usd": _usd(tx.amount_usd),
        "balance_after_usd": _usd(tx.balance_after_usd),
        "debate_id": str(tx.debate_id) if tx.debate_id else None,
        "provider": tx.provider,
        "provider_ref": tx.provider_ref,
        "reason": str(meta["reason"]) if meta.get("reason") else None,
    }


async def ledger_page(
    db: AsyncSession, user_id: uuid.UUID, *, limit: int, offset: int
) -> tuple[int, list[dict[str, Any]]]:
    total = await db.scalar(
        select(func.count())
        .select_from(CreditTransaction)
        .where(CreditTransaction.user_id == user_id)
    )
    rows = await db.execute(
        select(CreditTransaction, ledger_category())
        .where(CreditTransaction.user_id == user_id)
        .order_by(CreditTransaction.created_at.desc(), CreditTransaction.id)
        .limit(limit)
        .offset(offset)
    )
    return int(total or 0), [ledger_row_out(tx, str(category)) for tx, category in rows.all()]


def public_url(debate: Debate) -> str | None:
    if not (debate.is_public and debate.slug):
        return None
    return f"{settings.SITE_URL.rstrip('/')}/d/{debate.slug}"


async def debates_page(
    db: AsyncSession, user_id: uuid.UUID, *, limit: int, offset: int
) -> tuple[int, list[dict[str, Any]]]:
    total = await count_debates(db, user_id)
    debates = list(
        (
            await db.scalars(
                select(Debate)
                .where(Debate.user_id == user_id)
                .order_by(Debate.created_at.desc(), Debate.id)
                .limit(limit)
                .offset(offset)
            )
        ).all()
    )
    ids = [d.id for d in debates]
    models = await _debaters(db, ids)
    charged: dict[uuid.UUID, float] = {}
    if ids:
        rows = await db.execute(
            select(CreditTransaction.debate_id, func.sum(CreditTransaction.amount_usd))
            .where(CreditTransaction.debate_id.in_(ids))
            .group_by(CreditTransaction.debate_id)
        )
        charged = {did: -_usd(total) for did, total in rows.all() if did is not None}
    out = []
    for d in debates:
        billing = (d.config_json or {}).get("billing") or {}
        out.append(
            {
                "id": str(d.id),
                "title": d.title or "Untitled debate",
                "status": d.status,
                "created_at": d.created_at,
                "ended_at": d.ended_at,
                "models": models.get(d.id, []),
                "is_public": d.is_public,
                "url": public_url(d),
                "moderation_status": d.moderation_status,
                "media_status": d.media_status,
                "likes": d.likes_count or 0,
                "votes": d.votes_count or 0,
                "views": d.views or 0,
                "charged": charged.get(d.id, 0.0),
                "own_key": bool(billing.get("own_key")),
                "via_token": d.api_token_id is not None,
                "error": (d.error_message or "")[:300] or None,
            }
        )
    return total, out


# --- changes ------------------------------------------------------------------------------------


def temporary_password(groups: int = 4, size: int = 4) -> str:
    """ "k7mq-…": 16 random characters (≈ 79 bits), easy to read out or type."""
    return "-".join(
        "".join(secrets.choice(PASSWORD_ALPHABET) for _ in range(size)) for _ in range(groups)
    )


async def active_debates(db: AsyncSession, user_id: uuid.UUID) -> list[Debate]:
    found = await db.scalars(
        select(Debate).where(Debate.user_id == user_id, Debate.status.in_(ACTIVE_STATUSES))
    )
    return list(found.all())


async def revoke_tokens(
    db: AsyncSession, user_id: uuid.UUID, token_id: uuid.UUID | None = None
) -> int:
    query = delete(ApiToken).where(ApiToken.user_id == user_id)
    if token_id is not None:
        query = query.where(ApiToken.id == token_id)
    result = await db.execute(query)
    return int(getattr(result, "rowcount", 0) or 0)


async def unpublish_all(db: AsyncSession, user_id: uuid.UUID) -> int:
    result = await db.execute(
        update(Debate)
        .where(Debate.user_id == user_id, Debate.is_public.is_(True))
        .values(is_public=False)
    )
    return int(getattr(result, "rowcount", 0) or 0)


async def remove_reactions(db: AsyncSession, user_id: uuid.UUID) -> tuple[int, int]:
    """Delete every like and vote the account gave and rebuild those debates' counters (against
    boosting). (likes, votes) removed; not committed."""
    reacted: set[uuid.UUID] = set()
    removed: list[int] = []
    for model in (DebateLike, DebateVote):
        found = await db.scalars(select(model.debate_id).where(model.user_id == user_id))
        ids = set(found.all())
        reacted |= ids
        await db.execute(delete(model).where(model.user_id == user_id))
        removed.append(len(ids))
    for debate_id in reacted:
        await recount(db, debate_id, commit=False)
    return removed[0], removed[1]


@dataclass(frozen=True)
class Deleted:
    debate_ids: list[str]
    active_ids: list[str]  # were queued or running: their workers get the stop flag


async def delete_account(db: AsyncSession, user: User) -> Deleted:
    """Delete the account with its debates (turns, lineups, likes and votes on them go with
    them; ledger rows, tokens and activity go with the account). Likes and votes the account
    gave elsewhere disappear too, so those debates' counters are rebuilt. Not committed; the
    caller removes the media files after the commit."""
    owned = list((await db.scalars(select(Debate.id).where(Debate.user_id == user.id))).all())
    active = [d.id for d in await active_debates(db, user.id)]
    reacted: set[uuid.UUID] = set()
    for model in (DebateLike, DebateVote):
        found = await db.scalars(select(model.debate_id).where(model.user_id == user.id))
        reacted.update(found.all())
    await db.execute(delete(Debate).where(Debate.user_id == user.id))
    await db.execute(delete(User).where(User.id == user.id))
    for debate_id in reacted - set(owned):
        await recount(db, debate_id, commit=False)
    return Deleted(debate_ids=[str(i) for i in owned], active_ids=[str(i) for i in active])
