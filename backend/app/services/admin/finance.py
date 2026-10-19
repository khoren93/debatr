"""The admin console's Finance and Models pages.

Finance: the ledger (top-ups, bonuses, refunds, adjustments, charges by category) against what
providers cost us on the system keys (`provider_usage`), per day / week / month, with the
margin, the effective markup (charges over the cost of what we bill) and the cost we never bill
(scene director, sketches, picture checks, highlights, verdict structuring, the gallery check,
trending topics). Stripe sessions are reconciled with the `topup` rows.

Models: per answering model, tries and failures by kind, timing percentiles, cost and tokens
per turn (`provider_usage`), debates, judge and audience wins and fact-check accuracy (the
leaderboard's pure `ranking.build_leaderboard` over every finished debate) and which `:free`
models the Free Router pinned.
"""

import csv
import io
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import Integer, case, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import (
    CreditTransaction,
    Debate,
    DebateParticipant,
    DebateVote,
    ProviderUsage,
    User,
)
from app.services import ranking
from app.services.admin.stats import ledger_category
from app.services.free_router import is_free_router
from app.services.ledger import text_cell

Bucket = Literal["day", "week", "month"]
# Periods of the Finance page: how far back and how the series is bucketed.
FINANCE_PERIODS: dict[str, tuple[timedelta | None, Bucket]] = {
    "30d": (timedelta(days=30), "day"),
    "90d": (timedelta(days=90), "week"),
    "12m": (timedelta(days=365), "month"),
    "all": (None, "month"),
}
MODEL_PERIODS: dict[str, timedelta | None] = {
    "30d": timedelta(days=30),
    "90d": timedelta(days=90),
    "all": None,
}
# provider_usage purposes whose cost the owner pays (through `totals.cost`, the TTS and the
# picture charges); everything else on the system key is ours alone.
BILLED_PURPOSES = frozenset({"turn", "verdict", "factcheck", "image", "tts"})
CHARGE_CATEGORIES = ("models", "voices", "pictures")
TOP_ROWS = 10


def _usd(value: Any) -> float:
    return round(float(value or 0), 6)


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


# --- periods and buckets (pure) ---------------------------------------------------------------


def truncate(moment: datetime, bucket: Bucket) -> datetime:
    day = _aware(moment).replace(hour=0, minute=0, second=0, microsecond=0)
    if bucket == "week":
        return day - timedelta(days=day.weekday())
    if bucket == "month":
        return day.replace(day=1)
    return day


def next_bucket(start: datetime, bucket: Bucket) -> datetime:
    if bucket == "day":
        return start + timedelta(days=1)
    if bucket == "week":
        return start + timedelta(days=7)
    return (start.replace(day=28) + timedelta(days=4)).replace(day=1)


def bucket_starts(start: datetime, end: datetime, bucket: Bucket) -> list[datetime]:
    cursor, last = truncate(start, bucket), truncate(end, bucket)
    out = []
    while cursor <= last:
        out.append(cursor)
        cursor = next_bucket(cursor, bucket)
    return out


def finance_window(
    period: str, now: datetime, first: datetime | None
) -> tuple[datetime, datetime, Bucket]:
    span, bucket = FINANCE_PERIODS[period]
    start = now - span if span is not None else truncate(first or now, "month")
    return start, now, bucket


# --- the money summary (pure) -----------------------------------------------------------------


@dataclass
class Money:
    """Sums of one bucket (or the whole period)."""

    topups: float = 0.0
    bonuses: float = 0.0
    refunds: float = 0.0
    adjustments_in: float = 0.0
    adjustments_out: float = 0.0
    charged_models: float = 0.0
    charged_voices: float = 0.0
    charged_pictures: float = 0.0
    cost_billed: float = 0.0  # system-key cost of what we charge for
    cost_unbilled: float = 0.0  # system-key cost nobody pays us for
    cost_openrouter: float = 0.0
    cost_elevenlabs: float = 0.0

    @property
    def charged(self) -> float:
        return round(self.charged_models + self.charged_voices + self.charged_pictures, 6)

    @property
    def cost(self) -> float:
        return round(self.cost_billed + self.cost_unbilled, 6)

    @property
    def margin(self) -> float:
        """What charges brought in, less refunds, less everything providers cost us."""
        return round(self.charged - self.refunds - self.cost, 6)

    @property
    def markup(self) -> float | None:
        """Charges over the cost of what we bill (the `credit_markup` lever, roughly; minimum
        charges push it up, runs keep the markup they started with)."""
        return round(self.charged / self.cost_billed, 3) if self.cost_billed else None

    def out(self) -> dict[str, Any]:
        return {
            **{k: round(v, 6) for k, v in self.__dict__.items()},
            "charged": self.charged,
            "cost": self.cost,
            "margin": self.margin,
            "markup": self.markup,
        }


def add_ledger(money: Money, kind: str, category: str, amount: float) -> None:
    if kind == "topup":
        money.topups += amount
    elif kind == "bonus":
        money.bonuses += amount
    elif kind == "refund":
        money.refunds += amount
    elif kind == "adjustment":
        if amount >= 0:
            money.adjustments_in += amount
        else:
            money.adjustments_out -= amount
    elif category in CHARGE_CATEGORIES:
        # Charges are negative rows; a positive one would be a correction of a charge.
        setattr(money, f"charged_{category}", getattr(money, f"charged_{category}") - amount)


def add_cost(money: Money, purpose: str, provider: str, cost: float) -> None:
    if purpose in BILLED_PURPOSES:
        money.cost_billed += cost
    else:
        money.cost_unbilled += cost
    if provider == "elevenlabs":
        money.cost_elevenlabs += cost
    else:
        money.cost_openrouter += cost


def finance_csv(rows: list[dict[str, Any]]) -> str:
    columns = [
        "bucket_start_utc",
        "topups",
        "bonuses",
        "refunds",
        "adjustments_in",
        "adjustments_out",
        "charged_models",
        "charged_voices",
        "charged_pictures",
        "charged",
        "cost_billed",
        "cost_unbilled",
        "cost_openrouter",
        "cost_elevenlabs",
        "cost",
        "margin",
        "markup",
    ]
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(columns)
    for row in rows:
        writer.writerow(
            [
                text_cell(_aware(row["t"]).strftime("%Y-%m-%d")),
                *(
                    "" if row[c] is None else f"{row[c]:.6f}" if c != "markup" else f"{row[c]:.3f}"
                    for c in columns[1:]
                ),
            ]
        )
    return buffer.getvalue()


# --- the money queries ------------------------------------------------------------------------


def _bucket_sql(column: Any, bucket: Bucket) -> Any:
    return func.date_trunc(bucket, func.timezone("UTC", column))


async def first_activity(db: AsyncSession) -> datetime | None:
    first = await db.scalar(select(func.min(CreditTransaction.created_at)))
    return _aware(first) if first else None


async def money_series(
    db: AsyncSession, start: datetime, end: datetime, bucket: Bucket
) -> tuple[list[dict[str, Any]], Money, dict[str, float]]:
    """Per-bucket money, the period's totals and the system-key cost by purpose."""
    buckets = {t: Money() for t in bucket_starts(start, end, bucket)}
    total = Money()
    category = ledger_category()
    t = _bucket_sql(CreditTransaction.created_at, bucket).label("t")
    ledger_rows = await db.execute(
        select(t, CreditTransaction.kind, category, func.sum(CreditTransaction.amount_usd))
        .where(CreditTransaction.created_at >= start, CreditTransaction.created_at < end)
        .group_by(t, CreditTransaction.kind, category)
    )
    for when, kind, cat, amount in ledger_rows.all():
        value = float(amount or 0)
        add_ledger(total, str(kind), str(cat), value)
        target = buckets.get(_aware(when))
        if target is not None:
            add_ledger(target, str(kind), str(cat), value)
    u = _bucket_sql(ProviderUsage.created_at, bucket).label("t")
    usage_rows = await db.execute(
        select(u, ProviderUsage.purpose, ProviderUsage.provider, func.sum(ProviderUsage.cost_usd))
        .where(
            ProviderUsage.created_at >= start,
            ProviderUsage.created_at < end,
            ProviderUsage.key_owner == "system",
        )
        .group_by(u, ProviderUsage.purpose, ProviderUsage.provider)
    )
    by_purpose: dict[str, float] = defaultdict(float)
    for when, purpose, provider, cost in usage_rows.all():
        value = float(cost or 0)
        by_purpose[str(purpose)] += value
        add_cost(total, str(purpose), str(provider), value)
        target = buckets.get(_aware(when))
        if target is not None:
            add_cost(target, str(purpose), str(provider), value)
    series = [{"t": when, **money.out()} for when, money in buckets.items()]
    return series, total, {k: _usd(v) for k, v in sorted(by_purpose.items(), key=lambda i: -i[1])}


async def balances_now(db: AsyncSession) -> dict[str, Any]:
    row = (
        await db.execute(
            select(
                func.coalesce(func.sum(case((User.credits_usd > 0, User.credits_usd), else_=0)), 0),
                func.count().filter(User.credits_usd < 0),
                func.coalesce(func.sum(case((User.credits_usd < 0, User.credits_usd), else_=0)), 0),
            )
        )
    ).one()
    return {
        "liabilities": _usd(row[0]),
        "negative_balances": int(row[1] or 0),
        "negative_total": _usd(row[2]),
    }


async def top_accounts(
    db: AsyncSession, start: datetime, end: datetime, *, kinds: tuple[str, ...], sign: int
) -> list[dict[str, Any]]:
    """Accounts by the sum of their ledger rows of `kinds` (sign -1: charges as positive)."""
    total = func.sum(CreditTransaction.amount_usd * sign).label("total")
    rows = await db.execute(
        select(User.id, User.email, total)
        .join(User, User.id == CreditTransaction.user_id)
        .where(
            CreditTransaction.kind.in_(kinds),
            CreditTransaction.created_at >= start,
            CreditTransaction.created_at < end,
        )
        .group_by(User.id, User.email)
        .order_by(total.desc())
        .limit(TOP_ROWS)
    )
    return [
        {"user_id": str(uid), "email": email, "amount": _usd(amount)}
        for uid, email, amount in rows.all()
        if float(amount or 0) > 0
    ]


async def stripe_topups(db: AsyncSession, start: datetime, end: datetime) -> dict[str, float]:
    """`stripe:<session id>` refs of the period's top-ups and their amounts."""
    rows = await db.execute(
        select(CreditTransaction.provider_ref, CreditTransaction.amount_usd).where(
            CreditTransaction.kind == "topup",
            CreditTransaction.provider_ref.like("stripe:%"),
            CreditTransaction.created_at >= start,
            CreditTransaction.created_at < end,
        )
    )
    return {str(ref).removeprefix("stripe:"): float(amount) for ref, amount in rows.all()}


def reconcile(sessions: list[dict[str, Any]], credited: dict[str, float]) -> dict[str, Any]:
    """Paid Stripe sessions against the top-up rows: paid but never credited (money taken,
    nothing given: fix at once) and credited without a paid session in the list."""
    paid = [s for s in sessions if s.get("payment_status") == "paid"]
    ids = {str(s["id"]) for s in paid}
    missing = [s for s in paid if str(s["id"]) not in credited]
    return {
        "sessions": len(paid),
        "paid_total": round(sum(float(s.get("amount_total") or 0) / 100 for s in paid), 2),
        "credited": len(credited),
        "credited_total": round(sum(credited.values()), 2),
        "missing": [
            {
                "id": str(s["id"]),
                "email": s.get("customer_email") or (s.get("customer_details") or {}).get("email"),
                "amount": round(float(s.get("amount_total") or 0) / 100, 2),
                "created": datetime.fromtimestamp(int(s.get("created") or 0), UTC),
            }
            for s in missing
        ],
        "unmatched": sorted(ref for ref in credited if ref not in ids),
    }


# --- models -----------------------------------------------------------------------------------


@dataclass
class DebateFacts:
    models: dict[str, str]  # participant id -> model (the pinned one for a Free Router)
    pinned: list[str]  # models a Free Router pinned in this debate
    votes: dict[str, int]
    judge_winner: str | None
    claims: dict[str, dict[str, int]]


def debaters_of(config: dict[str, Any], participants: list[tuple[str, str]]) -> DebateFacts:
    """Participant ids ("participant_<i>", the config's order) of the debaters with the model
    that answered; `participants` are (role, model_id) rows in the same order."""
    configured = config.get("participants") or []
    models: dict[str, str] = {}
    pinned: list[str] = []
    for index, (role, model) in enumerate(participants):
        if role != "debater":
            continue
        wanted = str((configured[index] if index < len(configured) else {}).get("model_id") or "")
        if is_free_router(model):
            continue  # never pinned (a debate from before pinning): no contender
        models[f"participant_{index}"] = model
        if is_free_router(wanted) and model != wanted:
            pinned.append(model)
    return DebateFacts(models=models, pinned=pinned, votes={}, judge_winner=None, claims={})


async def usage_by_model(db: AsyncSession, since: datetime | None) -> dict[str, dict[str, Any]]:
    ttft = cast(ProviderUsage.meta_json["ttft_ms"].as_string(), Integer)
    where: list[Any] = [ProviderUsage.purpose.in_(("turn", "verdict"))]
    if since is not None:
        where.append(ProviderUsage.created_at >= since)
    rows = await db.execute(
        select(
            ProviderUsage.model,
            func.count(),
            func.count().filter(ProviderUsage.ok.is_(True)),
            func.count().filter(ProviderUsage.key_owner == "user"),
            func.percentile_cont(0.5).within_group(ProviderUsage.duration_ms),
            func.percentile_cont(0.9).within_group(ProviderUsage.duration_ms),
            func.percentile_cont(0.5).within_group(ttft),
            func.percentile_cont(0.9).within_group(ttft),
            func.sum(ProviderUsage.cost_usd),
            func.avg(ProviderUsage.tokens_out).filter(ProviderUsage.ok.is_(True)),
        )
        .where(*where)
        .group_by(ProviderUsage.model)
    )
    out: dict[str, dict[str, Any]] = {}
    for model, tries, ok, own, d50, d90, t50, t90, cost, tokens in rows.all():

        def ms(value: Any) -> int | None:
            return int(value) if value is not None else None

        out[str(model)] = {
            "tries": int(tries),
            "ok": int(ok),
            "own_key_tries": int(own),
            "duration_p50_ms": ms(d50),
            "duration_p90_ms": ms(d90),
            "ttft_p50_ms": ms(t50),
            "ttft_p90_ms": ms(t90),
            "cost": _usd(cost),
            "avg_tokens_out": int(tokens) if tokens is not None else None,
            "errors": {},
        }
    errors = await db.execute(
        select(ProviderUsage.model, ProviderUsage.error_kind, func.count())
        .where(*where, ProviderUsage.ok.is_(False))
        .group_by(ProviderUsage.model, ProviderUsage.error_kind)
    )
    for model, kind, n in errors.all():
        if str(model) in out:
            out[str(model)]["errors"][str(kind or "other")] = int(n)
    return out


async def debate_facts(db: AsyncSession, since: datetime | None) -> list[DebateFacts]:
    where: list[Any] = [Debate.status == "completed"]
    if since is not None:
        where.append(Debate.created_at >= since)
    debates = (
        await db.execute(
            select(Debate.id, Debate.config_json, Debate.verdict_json, Debate.totals_json).where(
                *where
            )
        )
    ).all()
    ids = [row[0] for row in debates]
    lineups: dict[Any, list[tuple[str, str]]] = defaultdict(list)
    votes: dict[Any, dict[str, int]] = defaultdict(dict)
    if ids:
        for debate_id, role, model in (
            await db.execute(
                select(
                    DebateParticipant.debate_id, DebateParticipant.role, DebateParticipant.model_id
                )
                .where(DebateParticipant.debate_id.in_(ids))
                .order_by(DebateParticipant.debate_id, DebateParticipant.id)
            )
        ).all():
            lineups[debate_id].append((str(role), str(model)))
        for debate_id, pid, n in (
            await db.execute(
                select(DebateVote.debate_id, DebateVote.participant_id, func.count())
                .where(DebateVote.debate_id.in_(ids))
                .group_by(DebateVote.debate_id, DebateVote.participant_id)
            )
        ).all():
            votes[debate_id][str(pid)] = int(n)
    out = []
    for debate_id, config, verdict, totals in debates:
        facts = debaters_of(config or {}, lineups.get(debate_id, []))
        facts.votes = votes.get(debate_id, {})
        facts.judge_winner = (verdict or {}).get("winner_id")
        facts.claims = (totals or {}).get("claims") or {}
        out.append(facts)
    return out


def model_rows(
    usage: dict[str, dict[str, Any]],
    debates: list[DebateFacts],
    catalogue: dict[str, dict[str, Any]],
    *,
    with_money: bool,
    turned_off: Iterable[str] = (),
) -> list[dict[str, Any]]:
    """One row per model that answered a turn or argued in a finished debate (`turned_off`: the
    models the Settings page took out of the wizard)."""
    off = set(turned_off)
    standings = {
        s.model_id: s
        for s in ranking.build_leaderboard(
            ranking.DebateRecord(
                models=d.models, votes=d.votes, judge_winner=d.judge_winner, claims=d.claims
            )
            for d in debates
        )
    }
    pins = Counter(model for d in debates for model in d.pinned)
    rows = []
    for model in sorted(set(usage) | set(standings)):
        u = usage.get(model, {})
        s = standings.get(model)
        info = catalogue.get(model) or {}
        tries = int(u.get("tries") or 0)
        ok = int(u.get("ok") or 0)
        rows.append(
            {
                "model": model,
                "name": str(info.get("name") or model),
                "is_free": bool(info.get("is_free", model.endswith(":free"))),
                "in_catalogue": bool(info),
                "disabled": model in off,
                "debates": s.debates if s else 0,
                "tries": tries,
                "failure_rate": round((tries - ok) / tries, 4) if tries else None,
                "errors": u.get("errors") or {},
                "own_key_tries": int(u.get("own_key_tries") or 0),
                "duration_p50_ms": u.get("duration_p50_ms"),
                "duration_p90_ms": u.get("duration_p90_ms"),
                "ttft_p50_ms": u.get("ttft_p50_ms"),
                "ttft_p90_ms": u.get("ttft_p90_ms"),
                "cost_per_turn": round(float(u.get("cost") or 0) / ok, 6)
                if with_money and ok
                else None,
                "avg_tokens_out": u.get("avg_tokens_out"),
                "judge_wins": s.judge_wins if s else 0,
                "judge_contests": s.judge_contests if s else 0,
                "audience_wins": s.audience_wins if s else 0,
                "audience_contests": s.audience_contests if s else 0,
                "claims_checked": s.claims_checked if s else 0,
                "claims_verified": s.claims_verified if s else 0,
                "claims_disputed": s.claims_disputed if s else 0,
                "router_pins": pins.get(model, 0),
            }
        )
    rows.sort(key=lambda r: (-r["tries"], -r["debates"], r["model"]))
    return rows
