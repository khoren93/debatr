"""Numbers for the admin overview: read-only queries plus pure assembly (periods, buckets,
deltas, the "needs attention" list).

Periods end now and compare with the period just before (`all` has none). Series are bucketed
by UTC hour (24 h), day (up to 120 days) or ISO week, with empty buckets filled in. Costs come
from `provider_usage`, which only exists since migration 0012: `cost_tracked_since` tells the
page when a period reaches further back than that. Views by source come from `view_days` (UTC
days, since migration 0016): no hourly series, and the 24 h tile counts today.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import DateTime, Integer, and_, case, cast, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.core.config import settings
from app.models.models import (
    AdminAuditLog,
    CreditTransaction,
    Debate,
    DebateLike,
    DebateParticipant,
    DebateVote,
    MailMessage,
    ProviderUsage,
    TrendingBatch,
    User,
    UserActivityDay,
    ViewDay,
)
from app.services.admin.mail import problem_clause
from app.services.views import SOURCES

Bucket = Literal["hour", "day", "week"]
PERIODS: dict[str, timedelta | None] = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
    "90d": timedelta(days=90),
    "all": None,
}
DAILY_UP_TO = timedelta(days=120)
FINISHED = ("completed", "error", "stopped")
LOGIN_FAILURES = ("auth.login_failed", "auth.totp_failed", "auth.locked", "auth.sudo_failed")


# --- periods and buckets (pure) ----------------------------------------------------------------


@dataclass(frozen=True)
class Window:
    period: str
    start: datetime
    end: datetime
    previous_start: datetime | None  # the period before, for deltas (None for "all")
    bucket: Bucket


def truncate(moment: datetime, bucket: Bucket) -> datetime:
    moment = moment.astimezone(UTC)
    if bucket == "hour":
        return moment.replace(minute=0, second=0, microsecond=0)
    day = moment.replace(hour=0, minute=0, second=0, microsecond=0)
    return day - timedelta(days=day.weekday()) if bucket == "week" else day


def window_for(period: str, now: datetime, first: datetime | None = None) -> Window:
    """The period ending `now`; `first` (the oldest account) starts "all"."""
    span = PERIODS[period]
    if span is None:
        start = truncate(first or now, "day")
        bucket: Bucket = "day" if now - start <= DAILY_UP_TO else "week"
        return Window(period, start, now, None, bucket)
    return Window(
        period, now - span, now, now - 2 * span, "hour" if span <= timedelta(days=1) else "day"
    )


def bucket_starts(window: Window) -> list[datetime]:
    step = {"hour": timedelta(hours=1), "day": timedelta(days=1), "week": timedelta(days=7)}[
        window.bucket
    ]
    cursor, last = truncate(window.start, window.bucket), truncate(window.end, window.bucket)
    starts: list[datetime] = []
    while cursor <= last:
        starts.append(cursor)
        cursor += step
    return starts


def fill_series(window: Window, columns: dict[str, dict[datetime, float]]) -> list[dict[str, Any]]:
    """One point per bucket with every column (0 where a bucket had nothing)."""
    points: list[dict[str, Any]] = []
    for start in bucket_starts(window):
        point: dict[str, Any] = {"t": start}
        for name, values in columns.items():
            point[name] = values.get(start, 0)
        points.append(point)
    return points


def tile(value: float, previous: float | None) -> dict[str, float | None]:
    return {"value": value, "previous": previous}


def error_rate(failed: float, finished: float) -> float | None:
    return round(failed / finished, 4) if finished else None


# --- the "needs attention" list (pure) ---------------------------------------------------------


Severity = Literal["critical", "warning", "info"]


@dataclass
class Signals:
    flagged: int = 0
    failed_24h: int = 0
    stuck_debates: int = 0
    stuck_media: int = 0
    media_failed_24h: int = 0
    negative_balances: int = 0
    negative_total: float = 0.0
    login_failures_24h: int = 0
    mail_off: bool = False  # production without a mail relay
    mail_problems_24h: int = 0  # letters not sent or not delivered
    openrouter_balance: float | None = None
    openrouter_error: str | None = None
    elevenlabs_ok: bool | None = None  # None: no system key
    elevenlabs_reason: str | None = None
    elevenlabs_used: int | None = None
    elevenlabs_limit: int | None = None
    trending_age_hours: float | None = None  # None: no batch at all
    trending_every_hours: int = 0
    backup_age_hours: float | None = None  # None: never recorded
    check_backups: bool = False
    recovery_codes_left: int | None = None
    extra: list[dict[str, Any]] = field(default_factory=list)


OPENROUTER_LOW_USD = 5.0
OPENROUTER_CRITICAL_USD = 1.0
BACKUP_MAX_HOURS = 26.0
TRENDING_SLACK_HOURS = 6.0


def _plural(n: int, word: str) -> str:
    return f"{n} {word if n == 1 else word + 's'}"


def _money(value: float) -> str:
    amount = abs(value)
    return f"${amount:.4f}" if 0 < amount < 0.01 else f"${amount:.2f}"


def _item(
    key: str, severity: Severity, title: str, detail: str = "", href: str | None = None
) -> dict[str, Any]:
    return {"key": key, "severity": severity, "title": title, "detail": detail, "href": href}


def attention_items(s: Signals) -> list[dict[str, Any]]:
    """What an admin should look at now, most severe first."""
    items: list[dict[str, Any]] = []
    if s.stuck_debates or s.stuck_media:
        parts = [_plural(s.stuck_debates, "debate")] if s.stuck_debates else []
        parts += [_plural(s.stuck_media, "audio build")] if s.stuck_media else []
        items.append(
            _item(
                "stuck",
                "critical",
                "Runs without a worker",
                f"{' and '.join(parts)} queued or running with no heartbeat for 5+ minutes",
                "/admin/system#runs",
            )
        )
    if s.openrouter_balance is not None and s.openrouter_balance < OPENROUTER_LOW_USD:
        severity: Severity = (
            "critical" if s.openrouter_balance < OPENROUTER_CRITICAL_USD else "warning"
        )
        items.append(
            _item(
                "openrouter",
                severity,
                "OpenRouter balance is low",
                f"${s.openrouter_balance:.2f} left on the system key",
                "https://openrouter.ai/settings/credits",
            )
        )
    elif s.openrouter_error:
        items.append(
            _item("openrouter", "warning", "OpenRouter balance unknown", s.openrouter_error)
        )
    if s.elevenlabs_ok is False:
        items.append(
            _item(
                "elevenlabs",
                "critical",
                "ElevenLabs key rejected",
                s.elevenlabs_reason or "premium voices are off",
            )
        )
    elif s.elevenlabs_limit:
        left = max(0, s.elevenlabs_limit - (s.elevenlabs_used or 0))
        if left < s.elevenlabs_limit * 0.1:
            items.append(
                _item(
                    "elevenlabs",
                    "critical" if left < s.elevenlabs_limit * 0.02 else "warning",
                    "ElevenLabs characters running out",
                    f"{left:,} of {s.elevenlabs_limit:,} left this period",
                )
            )
    if s.mail_off:
        items.append(
            _item(
                "mail",
                "critical",
                "Mail is off",
                "no relay set up (MAIL_SMTP_HOST, _PASSWORD, MAIL_FROM): confirmation and reset "
                "letters are not sent",
                "/admin/mail",
            )
        )
    elif s.mail_problems_24h:
        items.append(
            _item(
                "mail",
                "warning",
                f"{_plural(s.mail_problems_24h, 'letter')} not delivered in 24 h",
                "refused by the relay, bounced or marked as spam",
                "/admin/mail?status=problems",
            )
        )
    if s.check_backups and (s.backup_age_hours is None or s.backup_age_hours > BACKUP_MAX_HOURS):
        when = (
            "never recorded"
            if s.backup_age_hours is None
            else f"last one {s.backup_age_hours:.0f} h ago"
        )
        items.append(
            _item("backup", "critical", "No recent database backup", when, "/admin/system#health")
        )
    if s.flagged:
        items.append(
            _item(
                "moderation",
                "warning",
                f"{_plural(s.flagged, 'debate')} {'waits' if s.flagged == 1 else 'wait'} "
                "for moderation",
                "flagged by the AI check; approve or reject",
                "/admin/moderation",
            )
        )
    if s.failed_24h:
        items.append(
            _item(
                "failed",
                "warning",
                f"{_plural(s.failed_24h, 'debate')} failed in 24 h",
                "a turn got no answer; owners can resume",
                "/admin/debates?status=error",
            )
        )
    if s.media_failed_24h:
        items.append(
            _item(
                "media",
                "warning",
                f"{_plural(s.media_failed_24h, 'audio build')} failed in 24 h",
                "",
                "/admin/debates?media=error",
            )
        )
    if s.negative_balances:
        items.append(
            _item(
                "balances",
                "warning",
                f"{_plural(s.negative_balances, 'account')} below zero",
                f"{_money(s.negative_total)} in total (runs cost more than estimated)",
                "/admin/users?balance=negative",
            )
        )
    if s.login_failures_24h:
        items.append(
            _item(
                "logins",
                "warning" if s.login_failures_24h >= 3 else "info",
                f"{_plural(s.login_failures_24h, 'failed console sign-in')} in 24 h",
                "wrong passwords or codes",
                "/admin/audit?tab=security&ok=false",
            )
        )
    if s.trending_every_hours > 0:
        limit = s.trending_every_hours + TRENDING_SLACK_HOURS
        if s.trending_age_hours is None or s.trending_age_hours > limit:
            age = (
                "no batch yet"
                if s.trending_age_hours is None
                else f"newest is {s.trending_age_hours:.0f} h old"
            )
            items.append(
                _item(
                    "trending",
                    "warning",
                    "Trending topics are stale",
                    age,
                    "/admin/trending",
                )
            )
    if s.recovery_codes_left is not None and s.recovery_codes_left <= 3:
        items.append(
            _item(
                "recovery",
                "info",
                f"{_plural(s.recovery_codes_left, 'recovery code')} left",
                "make new ones on the Security page",
                "/admin/security",
            )
        )
    items.extend(s.extra)
    order = {"critical": 0, "warning": 1, "info": 2}
    return sorted(items, key=lambda item: order[item["severity"]])


# --- queries -----------------------------------------------------------------------------------


def _bucket(column: Any, bucket: Bucket) -> ColumnElement[Any]:
    return func.date_trunc(bucket, func.timezone("UTC", column))


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


async def _count(db: AsyncSession, query: Any) -> int:
    return int(await db.scalar(query) or 0)


async def _series(
    db: AsyncSession, column: Any, window: Window, *where: Any, value: Any = None
) -> dict[datetime, float]:
    bucket = _bucket(column, window.bucket).label("bucket")
    measure = value if value is not None else func.count()
    rows = await db.execute(
        select(bucket, measure)
        .where(column >= window.start, column < window.end, *where)
        .group_by(bucket)
    )
    return {_aware(t): float(v or 0) for t, v in rows.all()}


def _between(column: Any, start: datetime | None, end: datetime) -> ColumnElement[bool]:
    return and_(column >= start, column < end) if start is not None else column < end


def ledger_category() -> ColumnElement[str]:
    """`services/ledger.category` in SQL."""
    return case(
        (CreditTransaction.kind == "debate", "models"),
        (
            and_(
                CreditTransaction.kind == "media",
                or_(
                    CreditTransaction.provider_ref.like("%:images:%"),
                    CreditTransaction.description.like("AI pictures:%"),
                ),
            ),
            "pictures",
        ),
        (
            and_(
                CreditTransaction.kind == "media",
                or_(
                    CreditTransaction.provider_ref.like("%:music:%"),
                    CreditTransaction.description.like("Music:%"),
                ),
            ),
            "music",
        ),
        (
            and_(
                CreditTransaction.kind == "media",
                or_(
                    CreditTransaction.provider_ref.like("%:cover:%"),
                    CreditTransaction.description.like("AI cover:%"),
                ),
            ),
            "cover",
        ),
        (CreditTransaction.kind == "media", "voices"),
        else_=CreditTransaction.kind,
    )


async def first_account(db: AsyncSession) -> datetime | None:
    first = await db.scalar(select(func.min(User.created_at)))
    return _aware(first) if first else None


async def user_tiles(db: AsyncSession, window: Window, now: datetime) -> dict[str, Any]:
    async def new_between(start: datetime | None, end: datetime) -> int:
        return await _count(
            db, select(func.count()).select_from(User).where(_between(User.created_at, start, end))
        )

    async def active_since(start: datetime, end: datetime) -> int:
        if end - start <= timedelta(days=1):
            return await _count(
                db,
                select(func.count())
                .select_from(User)
                .where(User.last_seen_at >= start, User.last_seen_at < end),
            )
        return await _count(
            db,
            select(func.count(func.distinct(UserActivityDay.user_id))).where(
                UserActivityDay.day >= start.date(), UserActivityDay.day <= end.date()
            ),
        )

    today = now.date()

    async def active_days(days: int) -> int:
        return await _count(
            db,
            select(func.count(func.distinct(UserActivityDay.user_id))).where(
                UserActivityDay.day > today - timedelta(days=days)
            ),
        )

    previous = window.previous_start
    return {
        "new": tile(
            await new_between(window.start, window.end),
            await new_between(previous, window.start) if previous else None,
        ),
        "active": tile(
            await active_since(window.start, window.end),
            await active_since(previous, window.start) if previous else None,
        ),
        "total": await _count(db, select(func.count()).select_from(User)),
        "dau": await active_days(1),
        "wau": await active_days(7),
        "mau": await active_days(30),
    }


async def debate_tiles(db: AsyncSession, window: Window) -> dict[str, Any]:
    async def by_status(start: datetime | None, end: datetime) -> dict[str, int]:
        rows = await db.execute(
            select(Debate.status, func.count())
            .where(_between(Debate.created_at, start, end))
            .group_by(Debate.status)
        )
        return {str(status): int(n) for status, n in rows.all()}

    now_counts = await by_status(window.start, window.end)
    before = await by_status(window.previous_start, window.start) if window.previous_start else None

    def total(counts: dict[str, int] | None, *statuses: str) -> int | None:
        if counts is None:
            return None
        return sum(n for status, n in counts.items() if not statuses or status in statuses)

    def rate(counts: dict[str, int] | None) -> float | None:
        if counts is None:
            return None
        return error_rate(total(counts, "error") or 0, total(counts, *FINISHED) or 0)

    finished_at = cast(Debate.media_json["finished_at"].as_string(), DateTime(timezone=True))

    async def media(status: str, start: datetime | None, end: datetime) -> int:
        return await _count(
            db,
            select(func.count())
            .select_from(Debate)
            .where(Debate.media_status == status, _between(finished_at, start, end)),
        )

    async def published(start: datetime | None, end: datetime) -> int:
        return await _count(
            db,
            select(func.count())
            .select_from(Debate)
            .where(Debate.is_public.is_(True), _between(Debate.published_at, start, end)),
        )

    async def reactions(model: Any, column: Any, start: datetime | None, end: datetime) -> int:
        return await _count(
            db, select(func.count()).select_from(model).where(_between(column, start, end))
        )

    renders = await db.scalar(
        text(
            "SELECT coalesce(sum(value::int), 0) FROM debates, "
            "json_each_text(coalesce(media_json -> 'renders', '{}'::json)) "
            "WHERE debates.created_at >= :start AND debates.created_at < :end"
        ),
        {"start": window.start, "end": window.end},
    )
    previous = window.previous_start

    def whole_days(start: datetime, end: datetime) -> ColumnElement[bool]:
        """The UTC days after `start`'s, up to `end`'s: a period's whole days."""
        return and_(ViewDay.day > start.date(), ViewDay.day <= end.date())

    async def views(start: datetime, end: datetime) -> int:
        return await _count(
            db, select(func.coalesce(func.sum(ViewDay.views), 0)).where(whole_days(start, end))
        )

    source_rows = await db.execute(
        select(ViewDay.source, func.sum(ViewDay.views))
        .where(whole_days(window.start, window.end))
        .group_by(ViewDay.source)
    )
    views_by_source = {str(source): int(n or 0) for source, n in source_rows.all()}

    running = await _count(
        db, select(func.count()).select_from(Debate).where(Debate.status.in_(("queued", "running")))
    )
    return {
        "started": tile(total(now_counts) or 0, total(before)),
        "completed": tile(total(now_counts, "completed") or 0, total(before, "completed")),
        "failed": tile(total(now_counts, "error") or 0, total(before, "error")),
        "stopped": tile(total(now_counts, "stopped") or 0, total(before, "stopped")),
        "error_rate": tile(rate(now_counts) or 0.0, rate(before)),
        "running_now": running,
        "media_ready": tile(
            await media("ready", window.start, window.end),
            await media("ready", previous, window.start) if previous else None,
        ),
        "media_failed": tile(
            await media("error", window.start, window.end),
            await media("error", previous, window.start) if previous else None,
        ),
        "renders": int(renders or 0),
        "published": tile(
            await published(window.start, window.end),
            await published(previous, window.start) if previous else None,
        ),
        "likes": tile(
            await reactions(DebateLike, DebateLike.created_at, window.start, window.end),
            await reactions(DebateLike, DebateLike.created_at, previous, window.start)
            if previous
            else None,
        ),
        "votes": tile(
            await reactions(DebateVote, DebateVote.created_at, window.start, window.end),
            await reactions(DebateVote, DebateVote.created_at, previous, window.start)
            if previous
            else None,
        ),
        "views": tile(
            await views(window.start, window.end),
            await views(previous, window.start) if previous else None,
        ),
        "views_by_source": views_by_source,
    }


def _usd(value: Any) -> float:
    return round(float(value or 0), 6)


async def money(db: AsyncSession, window: Window) -> dict[str, Any]:
    category = ledger_category().label("category")

    async def ledger(start: datetime | None, end: datetime) -> dict[str, float]:
        rows = await db.execute(
            select(category, func.sum(CreditTransaction.amount_usd))
            .where(_between(CreditTransaction.created_at, start, end))
            .group_by(category)
        )
        return {str(name): _usd(total) for name, total in rows.all()}

    async def costs(start: datetime | None, end: datetime) -> dict[tuple[str, str], float]:
        rows = await db.execute(
            select(ProviderUsage.key_owner, ProviderUsage.purpose, func.sum(ProviderUsage.cost_usd))
            .where(_between(ProviderUsage.created_at, start, end))
            .group_by(ProviderUsage.key_owner, ProviderUsage.purpose)
        )
        return {(str(k), str(p)): _usd(total) for k, p, total in rows.all()}

    def summary(entries: dict[str, float], spent: dict[tuple[str, str], float]) -> dict[str, Any]:
        charged = {
            name: -entries.get(name, 0.0)
            for name in ("models", "voices", "pictures", "music", "cover")
        }
        charged_total = round(sum(charged.values()), 6)
        system = round(sum(v for (k, _), v in spent.items() if k == "system"), 6)
        return {
            "topups": entries.get("topup", 0.0),
            "bonuses": entries.get("bonus", 0.0),
            "refunds": entries.get("refund", 0.0),
            "adjustments": entries.get("adjustment", 0.0),
            "charged": charged,
            "charged_total": charged_total,
            "cost_system": system,
            "cost_user_keys": round(sum(v for (k, _), v in spent.items() if k == "user"), 6),
            "cost_by_purpose": {
                p: round(v, 6) for (k, p), v in sorted(spent.items()) if k == "system"
            },
            "margin": round(charged_total - system, 6),
        }

    now_summary = summary(
        await ledger(window.start, window.end), await costs(window.start, window.end)
    )
    if window.previous_start is not None:
        before = summary(
            await ledger(window.previous_start, window.start),
            await costs(window.previous_start, window.start),
        )
        for key in ("topups", "charged_total", "cost_system", "margin"):
            now_summary[f"{key}_previous"] = before[key]
    balances = (
        await db.execute(
            select(
                func.coalesce(func.sum(case((User.credits_usd > 0, User.credits_usd), else_=0)), 0),
                func.count().filter(User.credits_usd < 0),
                func.coalesce(func.sum(case((User.credits_usd < 0, User.credits_usd), else_=0)), 0),
            )
        )
    ).one()
    tracked = await db.scalar(select(func.min(ProviderUsage.created_at)))
    return {
        **now_summary,
        "liabilities": _usd(balances[0]),
        "negative_balances": int(balances[1] or 0),
        "negative_total": _usd(balances[2]),
        "cost_tracked_since": _aware(tracked) if tracked else None,
    }


async def series(db: AsyncSession, window: Window, *, with_money: bool) -> list[dict[str, Any]]:
    columns: dict[str, dict[datetime, float]] = {
        "signups": await _series(db, User.created_at, window),
    }
    if window.bucket != "hour":
        # A date has no time zone to convert: truncate it as it is.
        bucket = func.date_trunc(window.bucket, cast(UserActivityDay.day, DateTime)).label("bucket")
        rows = await db.execute(
            select(bucket, func.count(func.distinct(UserActivityDay.user_id)))
            .where(
                UserActivityDay.day >= window.start.date(), UserActivityDay.day <= window.end.date()
            )
            .group_by(bucket)
        )
        columns["active"] = {_aware(t): float(n) for t, n in rows.all()}
    for status in FINISHED:
        columns[status] = await _series(db, Debate.created_at, window, Debate.status == status)
    if window.bucket != "hour":
        columns.update(await views_by_source(db, window))
    if with_money:
        charge = func.sum(-CreditTransaction.amount_usd)
        columns["charged"] = await _series(
            db,
            CreditTransaction.created_at,
            window,
            CreditTransaction.kind.in_(("debate", "media")),
            value=charge,
        )
        columns["topups"] = await _series(
            db,
            CreditTransaction.created_at,
            window,
            CreditTransaction.kind == "topup",
            value=func.sum(CreditTransaction.amount_usd),
        )
        columns["cost"] = await _series(
            db,
            ProviderUsage.created_at,
            window,
            ProviderUsage.key_owner == "system",
            value=func.sum(ProviderUsage.cost_usd),
        )
    points = fill_series(window, columns)
    if window.bucket == "hour":
        for point in points:
            point["active"] = None  # activity is kept per day
            point.update(dict.fromkeys(view_columns(), None))  # and so are views
    return points


async def views_since(db: AsyncSession) -> Any:
    """The first UTC day with views by source (they are kept since migration 0016)."""
    return await db.scalar(select(func.min(ViewDay.day)))


def view_columns() -> list[str]:
    """The series' view columns, one per source: `views_search`, `views_ai`…"""
    return [f"views_{source}" for source in SOURCES]


async def views_by_source(db: AsyncSession, window: Window) -> dict[str, dict[datetime, float]]:
    """Views per bucket and source (from whole UTC days)."""
    bucket = func.date_trunc(window.bucket, cast(ViewDay.day, DateTime)).label("bucket")
    rows = await db.execute(
        select(bucket, ViewDay.source, func.sum(ViewDay.views))
        .where(ViewDay.day >= window.start.date(), ViewDay.day <= window.end.date())
        .group_by(bucket, ViewDay.source)
    )
    columns: dict[str, dict[datetime, float]] = {name: {} for name in view_columns()}
    for t, source, n in rows.all():
        name = f"views_{source}"
        if name in columns:
            columns[name][_aware(t)] = float(n or 0)
    return columns


async def top_models(db: AsyncSession, window: Window, limit: int = 8) -> list[dict[str, Any]]:
    debates = await db.execute(
        select(DebateParticipant.model_id, func.count(func.distinct(DebateParticipant.debate_id)))
        .join(Debate, Debate.id == DebateParticipant.debate_id)
        .where(
            DebateParticipant.role == "debater",
            Debate.created_at >= window.start,
            Debate.created_at < window.end,
        )
        .group_by(DebateParticipant.model_id)
    )
    counts = {str(model): int(n) for model, n in debates.all()}
    ttft = cast(ProviderUsage.meta_json["ttft_ms"].as_string(), Integer)
    tries = await db.execute(
        select(
            ProviderUsage.model,
            func.count(),
            func.count().filter(ProviderUsage.ok.is_(False)),
            func.avg(ttft),
            func.sum(ProviderUsage.cost_usd),
        )
        .where(
            ProviderUsage.purpose.in_(("turn", "verdict")),
            ProviderUsage.created_at >= window.start,
            ProviderUsage.created_at < window.end,
        )
        .group_by(ProviderUsage.model)
    )
    stats = {str(m): (int(n), int(f), avg, _usd(c)) for m, n, f, avg, c in tries.all()}
    rows = []
    for model in set(counts) | set(stats):
        n, failed, avg, cost = stats.get(model, (0, 0, None, 0.0))
        rows.append(
            {
                "model": model,
                "debates": counts.get(model, 0),
                "turns": n,
                "failure_rate": round(failed / n, 4) if n else None,
                "avg_ttft_ms": int(avg) if avg is not None else None,
                "cost": cost,
            }
        )
    rows.sort(key=lambda r: (r["debates"], r["turns"]), reverse=True)
    return rows[:limit]


async def top_spenders(db: AsyncSession, window: Window, limit: int = 5) -> list[dict[str, Any]]:
    spent = func.sum(-CreditTransaction.amount_usd).label("spent")
    rows = await db.execute(
        select(User.id, User.email, User.display_name, spent)
        .select_from(CreditTransaction)
        .join(User, User.id == CreditTransaction.user_id)
        .where(
            CreditTransaction.kind.in_(("debate", "media")),
            CreditTransaction.created_at >= window.start,
            CreditTransaction.created_at < window.end,
        )
        .group_by(User.id, User.email, User.display_name)
        .order_by(spent.desc())
        .limit(limit)
    )
    return [
        {"user_id": str(uid), "email": email, "display_name": name, "spent": _usd(total)}
        for uid, email, name, total in rows.all()
    ]


async def top_debates(db: AsyncSession, window: Window, limit: int = 5) -> list[dict[str, Any]]:
    rows = await db.execute(
        select(
            Debate.id,
            Debate.title,
            Debate.slug,
            Debate.is_public,
            Debate.likes_count,
            Debate.views,
            Debate.votes_count,
        )
        .where(Debate.created_at >= window.start, Debate.created_at < window.end)
        .order_by(Debate.likes_count.desc(), Debate.views.desc(), Debate.created_at.desc())
        .limit(limit)
    )
    return [
        {
            "id": str(did),
            "title": title or "Untitled debate",
            "slug": slug if public else None,
            "url": f"{settings.SITE_URL.rstrip('/')}/d/{slug}" if public and slug else None,
            "likes": int(likes or 0),
            "views": int(views or 0),
            "votes": int(votes or 0),
        }
        for did, title, slug, public, likes, views, votes in rows.all()
    ]


async def attention_counts(db: AsyncSession, now: datetime) -> Signals:
    """The database part of the signals (Redis and providers are added by the caller)."""
    day_ago = now - timedelta(hours=24)
    finished_at = cast(Debate.media_json["finished_at"].as_string(), DateTime(timezone=True))
    negative = (
        await db.execute(
            select(
                func.count().filter(User.credits_usd < 0),
                func.coalesce(func.sum(case((User.credits_usd < 0, User.credits_usd), else_=0)), 0),
            )
        )
    ).one()
    newest_batch = await db.scalar(select(func.max(TrendingBatch.created_at)))
    return Signals(
        flagged=await _count(
            db,
            select(func.count()).select_from(Debate).where(Debate.moderation_status == "flagged"),
        ),
        failed_24h=await _count(
            db,
            select(func.count())
            .select_from(Debate)
            .where(Debate.status == "error", Debate.ended_at >= day_ago),
        ),
        media_failed_24h=await _count(
            db,
            select(func.count())
            .select_from(Debate)
            .where(Debate.media_status == "error", finished_at >= day_ago),
        ),
        negative_balances=int(negative[0] or 0),
        negative_total=_usd(negative[1]),
        login_failures_24h=await _count(
            db,
            select(func.count())
            .select_from(AdminAuditLog)
            .where(AdminAuditLog.action.in_(LOGIN_FAILURES), AdminAuditLog.created_at >= day_ago),
        ),
        mail_problems_24h=await _count(
            db,
            select(func.count())
            .select_from(MailMessage)
            .where(problem_clause(), MailMessage.created_at >= day_ago),
        ),
        trending_age_hours=(now - _aware(newest_batch)).total_seconds() / 3600
        if newest_batch
        else None,
    )


async def active_runs(db: AsyncSession, now: datetime) -> tuple[list[str], list[str]]:
    """Ids of debates and audio builds queued/running for 5+ minutes (the caller checks their
    heartbeats in Redis)."""
    old = now - timedelta(minutes=5)
    debates = await db.scalars(
        select(Debate.id).where(
            Debate.status.in_(("queued", "running")),
            func.coalesce(Debate.started_at, Debate.created_at) < old,
        )
    )
    started = cast(Debate.media_json["started_at"].as_string(), DateTime(timezone=True))
    media = await db.scalars(
        select(Debate.id).where(Debate.media_status.in_(("queued", "running")), started < old)
    )
    return [str(i) for i in debates.all()], [str(i) for i in media.all()]
