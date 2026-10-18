"""Operator alerts in Telegram (optional: ALERT_TELEGRAM_BOT_TOKEN + ALERT_TELEGRAM_CHAT_ID).

Raised at once: a console sign-in and a locked second factor (the API, `notify_soon`), a failed
trending batch (its job). Found by `check_alerts_job` (the scheduler, every CHECK_SECONDS on the
background queue): a series of failed console sign-ins, newly flagged debates, a spike of failed
debates, runs without a worker, a low OpenRouter balance, a rejected ElevenLabs key or its
characters running out, top-ups and a full disk. The rules are pure (`decide`) over a snapshot
(`Facts`); the job only gathers it.

Antispam: an alert with `quiet` seconds holds a Redis key that long, so a lasting condition is
reported once and again only when it escalates (each severity has its own key). New flagged
debates, top-ups and stuck runs are told apart from the ones already reported by the ids the
last check saw. Every alert, sent or not (no Telegram configured, Telegram refused), lands in
RECENT_KEY for the console's Settings page.

Sending never raises, and the bot token never reaches a log: httpx errors print the URL, which
carries the token, so only their class name is kept. The alerts need the scheduler and a worker
on the background queue: when every worker is down, nothing reports it.
"""

import asyncio
import contextlib
import json
import logging
import shutil
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from html import escape
from typing import Any, Literal

import httpx
from redis import Redis
from redis.asyncio import Redis as AsyncRedis
from redis.exceptions import RedisError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.redis import debate_beat_key, get_async_redis, get_sync_redis, media_beat_key
from app.models.models import AdminAuditLog, CreditTransaction, Debate, User, utcnow

logger = logging.getLogger(__name__)

Severity = Literal["critical", "warning", "info"]
ICONS: dict[str, str] = {"critical": "🔴", "warning": "🟠", "info": "🔵"}

TELEGRAM_API = "https://api.telegram.org"
SEND_TIMEOUT = 10.0
# Tests swap these for httpx.MockTransport.
TRANSPORT: httpx.BaseTransport | None = None
ASYNC_TRANSPORT: httpx.AsyncBaseTransport | None = None

CHECK_SECONDS = 300
JOB_TIMEOUT = 120
LOCK_KEY = "alerts:lock"
RECENT_KEY = "alerts:recent"
RECENT_KEPT = 50
SEEN_TTL = 3 * 3600

HOUR = 3600
LOGIN_WINDOW = timedelta(minutes=15)
LOGIN_FAILURES_ALERT = 5
LOGIN_FAILURES = ("auth.login_failed", "auth.totp_failed", "auth.locked", "auth.sudo_failed")
ERROR_WINDOW = timedelta(hours=1)
ERRORS_MIN = 3
ERROR_SHARE = 0.3
ERROR_SHARE_CRITICAL = 0.6
STUCK_AFTER = timedelta(minutes=10)
TOPUP_WINDOW = timedelta(minutes=30)
OPENROUTER_LOW_USD = 5.0
OPENROUTER_CRITICAL_USD = 1.0
ELEVENLABS_LOW = 0.10
ELEVENLABS_CRITICAL = 0.02
DISK_WARNING = 0.85
DISK_CRITICAL = 0.95
BALANCE_KEY = "admin:openrouter_balance"  # shared with the overview (routes_overview)
BALANCE_SECONDS = 300


@dataclass(frozen=True)
class Alert:
    kind: str
    title: str
    detail: str = ""
    severity: Severity = "warning"
    path: str | None = None  # a console page, e.g. "/admin/moderation"
    quiet: int = 0  # seconds the same alert stays quiet after it went out

    @property
    def quiet_key(self) -> str:
        return f"alert:quiet:{self.kind}:{self.severity}"


# --- messages ---------------------------------------------------------------------------------


def console_url(path: str | None) -> str | None:
    if not path:
        return None
    host = settings.admin_hostname
    if host:
        return f"{'https' if settings.is_production else 'http'}://{host}{path}"
    return f"{settings.SITE_URL.rstrip('/')}{path}"


def message(alert: Alert) -> str:
    """The Telegram text (HTML parse mode, everything escaped)."""
    head = f"{ICONS[alert.severity]} <b>{escape(alert.title)}</b>"
    if not settings.is_production:
        head = f"[{escape(settings.ENVIRONMENT)}] {head}"
    lines = [head]
    if alert.detail:
        lines.append(escape(alert.detail))
    url = console_url(alert.path)
    if url:
        lines.append(f'<a href="{escape(url, quote=True)}">Open in the console</a>')
    return "\n".join(lines)


def configured() -> bool:
    return bool(settings.ALERT_TELEGRAM_BOT_TOKEN and settings.ALERT_TELEGRAM_CHAT_ID)


def _send_url() -> str:
    return f"{TELEGRAM_API}/bot{settings.ALERT_TELEGRAM_BOT_TOKEN}/sendMessage"


def _payload(text: str) -> dict[str, Any]:
    return {
        "chat_id": settings.ALERT_TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }


def _outcome(response: httpx.Response) -> str | None:
    """None when Telegram took the message, otherwise why not (never the URL)."""
    if response.status_code == 200:
        return None
    description = None
    with contextlib.suppress(ValueError, AttributeError):
        description = response.json().get("description")
    reason = f": {str(description)[:200]}" if description else ""
    return f"Telegram answered {response.status_code}{reason}"


def send_sync(text: str) -> str | None:
    """Send to the chat; None on success, else the reason."""
    if not configured():
        return "Telegram is not configured"
    try:
        with httpx.Client(timeout=SEND_TIMEOUT, transport=TRANSPORT) as client:
            response = client.post(_send_url(), json=_payload(text))
    except httpx.HTTPError as exc:
        return f"Telegram unreachable ({type(exc).__name__})"
    return _outcome(response)


async def send(text: str) -> str | None:
    if not configured():
        return "Telegram is not configured"
    try:
        async with httpx.AsyncClient(timeout=SEND_TIMEOUT, transport=ASYNC_TRANSPORT) as client:
            response = await client.post(_send_url(), json=_payload(text))
    except httpx.HTTPError as exc:
        return f"Telegram unreachable ({type(exc).__name__})"
    return _outcome(response)


def _entry(alert: Alert, error: str | None) -> str:
    return json.dumps(
        {
            "at": utcnow().isoformat(),
            "kind": alert.kind,
            "severity": alert.severity,
            "title": alert.title,
            "detail": alert.detail,
            "path": alert.path,
            "sent": error is None,
            "error": error,
        }
    )


def _log_failure(alert: Alert, error: str | None) -> None:
    if error and configured():
        logger.warning("Alert %s was not sent: %s", alert.kind, error)


def raise_sync(alert: Alert, redis: Redis | None = None) -> bool:
    """Send `alert` unless the same one is quiet, and record it. True when Telegram took it."""
    try:
        conn = redis or get_sync_redis()
        if alert.quiet and not conn.set(alert.quiet_key, "1", nx=True, ex=alert.quiet):
            return False
    except RedisError:
        logger.warning("Alert %s skipped: Redis is unavailable", alert.kind)
        return False
    error = send_sync(message(alert))
    _log_failure(alert, error)
    with contextlib.suppress(RedisError):
        conn.lpush(RECENT_KEY, _entry(alert, error))
        conn.ltrim(RECENT_KEY, 0, RECENT_KEPT - 1)
    return error is None


async def deliver(alert: Alert, redis: AsyncRedis | None = None) -> str | None:
    """Send `alert` now (no antispam) and record it: None when Telegram took it."""
    error = await send(message(alert))
    _log_failure(alert, error)
    with contextlib.suppress(RedisError):
        conn = redis or get_async_redis()
        await conn.lpush(RECENT_KEY, _entry(alert, error))  # type: ignore[misc]
        await conn.ltrim(RECENT_KEY, 0, RECENT_KEPT - 1)  # type: ignore[misc]
    return error


async def raise_async(alert: Alert, redis: AsyncRedis | None = None) -> bool:
    try:
        conn = redis or get_async_redis()
        if alert.quiet and not await conn.set(alert.quiet_key, "1", nx=True, ex=alert.quiet):
            return False
    except RedisError:
        logger.warning("Alert %s skipped: Redis is unavailable", alert.kind)
        return False
    return await deliver(alert, conn) is None


_tasks: set[asyncio.Task[None]] = set()


async def _raise_quietly(alert: Alert) -> None:
    try:
        await raise_async(alert)
    except Exception:
        logger.exception("Alert %s failed", alert.kind)


def notify_soon(alert: Alert) -> None:
    """From a request: send in the background, the answer does not wait for Telegram."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    task = loop.create_task(_raise_quietly(alert))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def recent(redis: AsyncRedis | None = None) -> list[dict[str, Any]]:
    """The last alerts, newest first (for the console)."""
    try:
        raw: list[Any] = await (redis or get_async_redis()).lrange(RECENT_KEY, 0, RECENT_KEPT - 1)  # type: ignore[misc]
    except RedisError:
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        with contextlib.suppress(ValueError, TypeError):
            out.append(json.loads(item))
    return out


# --- alerts raised at once --------------------------------------------------------------------

BROWSERS = (("Edg/", "Edge"), ("OPR/", "Opera"), ("Firefox/", "Firefox"), ("Chrome/", "Chrome"))
SYSTEMS = (
    ("iPhone", "iOS"),
    ("iPad", "iOS"),
    ("Android", "Android"),
    ("Mac OS X", "macOS"),
    ("Windows", "Windows"),
    ("Linux", "Linux"),
)


def agent_label(agent: str | None) -> str:
    """ "Chrome on macOS" from a user-agent (the console's describeAgent, in short)."""
    if not agent:
        return ""
    browser = next((name for mark, name in BROWSERS if mark in agent), None)
    if browser is None:
        browser = "Safari" if "Safari/" in agent else "a browser"
    system = next((name for mark, name in SYSTEMS if mark in agent), None)
    return f"{browser} on {system}" if system else browser


def sign_in_alert(email: str, method: str, ip: str | None, agent: str | None) -> Alert:
    """`method`: how the second factor was passed ("recovery code" is worth a closer look)."""
    where = " · ".join(part for part in (ip, agent_label(agent)) if part)
    return Alert(
        kind="signin",
        title=f"Console sign-in: {email}",
        detail=f"with {method}" + (f" · {where}" if where else ""),
        severity="warning" if method == "a recovery code" else "info",
        path="/admin/audit?tab=security",
    )


def locked_alert(email: str, ip: str | None) -> Alert:
    return Alert(
        kind="locked",
        title=f"Console second factor locked: {email}",
        detail="too many wrong codes" + (f" · last from {ip}" if ip else ""),
        severity="critical",
        path="/admin/audit?tab=security&ok=false",
        quiet=15 * 60,
    )


def trending_failed_alert(reason: str) -> Alert:
    return Alert(
        kind="trending",
        title="Trending batch failed",
        detail=f"{reason[:300]} · the site keeps the previous batch",
        severity="warning",
        path="/admin/trending",
        quiet=6 * HOUR,
    )


# --- the periodic check (pure rules) ----------------------------------------------------------


@dataclass
class Facts:
    login_failures: int = 0  # console sign-in failures in LOGIN_WINDOW
    login_ips: list[str] = field(default_factory=list)
    new_flagged: list[tuple[str, str | None]] = field(default_factory=list)  # (id, title)
    finished_last_hour: int = 0
    failed_last_hour: int = 0
    stuck_debates: int = 0
    stuck_media: int = 0
    openrouter_balance: float | None = None
    elevenlabs_rejected: str | None = None  # the reason, when the system key is refused
    elevenlabs_used: int | None = None
    elevenlabs_limit: int | None = None
    new_topups: list[tuple[str, float, str | None]] = field(
        default_factory=list
    )  # (user, $, email)
    disk_used: float | None = None  # share of the disk that holds MEDIA_ROOT


def _plural(n: int, word: str) -> str:
    return f"{n} {word if n == 1 else word + 's'}"


def _usd(value: float) -> str:
    return f"${value:,.2f}"


def _listing(items: list[str], shown: int = 3) -> str:
    text = "; ".join(items[:shown])
    return f"{text} and {len(items) - shown} more" if len(items) > shown else text


def decide(f: Facts) -> list[Alert]:
    alerts: list[Alert] = []
    if f.login_failures >= LOGIN_FAILURES_ALERT:
        ips = ", ".join(f.login_ips[:3]) or "unknown addresses"
        alerts.append(
            Alert(
                "logins",
                f"{f.login_failures} failed console sign-ins in 15 min",
                f"from {ips}",
                "warning",
                "/admin/audit?tab=security&ok=false",
                quiet=HOUR,
            )
        )
    if f.stuck_debates or f.stuck_media:
        parts = [_plural(f.stuck_debates, "debate")] if f.stuck_debates else []
        parts += [_plural(f.stuck_media, "audio build")] if f.stuck_media else []
        alerts.append(
            Alert(
                "stuck",
                "Runs without a worker",
                f"{' and '.join(parts)} with no heartbeat and no job waiting for 10+ minutes; "
                "recovery did not pick them up",
                "critical",
                "/admin/system#runs",
                quiet=HOUR,
            )
        )
    if f.failed_last_hour >= ERRORS_MIN:
        share = f.failed_last_hour / max(f.finished_last_hour, f.failed_last_hour)
        if share >= ERROR_SHARE:
            alerts.append(
                Alert(
                    "errors",
                    f"{f.failed_last_hour} of {f.finished_last_hour} debates failed in the last "
                    "hour",
                    "a model or provider may be down: see Models",
                    "critical" if share >= ERROR_SHARE_CRITICAL else "warning",
                    "/admin/debates?status=error",
                    quiet=3 * HOUR,
                )
            )
    if f.openrouter_balance is not None and f.openrouter_balance < OPENROUTER_LOW_USD:
        critical = f.openrouter_balance < OPENROUTER_CRITICAL_USD
        alerts.append(
            Alert(
                "openrouter",
                "OpenRouter balance is low",
                f"{_usd(f.openrouter_balance)} left on the system key",
                "critical" if critical else "warning",
                "/admin/system#providers",
                quiet=(6 if critical else 12) * HOUR,
            )
        )
    if f.elevenlabs_rejected:
        alerts.append(
            Alert(
                "elevenlabs",
                "ElevenLabs key rejected",
                f"{f.elevenlabs_rejected[:200]} · premium voices are off",
                "critical",
                "/admin/system#providers",
                quiet=12 * HOUR,
            )
        )
    elif f.elevenlabs_limit:
        left = max(0, f.elevenlabs_limit - (f.elevenlabs_used or 0))
        if left < f.elevenlabs_limit * ELEVENLABS_LOW:
            alerts.append(
                Alert(
                    "elevenlabs",
                    "ElevenLabs characters running out",
                    f"{left:,} of {f.elevenlabs_limit:,} left this period",
                    "critical" if left < f.elevenlabs_limit * ELEVENLABS_CRITICAL else "warning",
                    "/admin/system#providers",
                    quiet=12 * HOUR,
                )
            )
    if f.disk_used is not None and f.disk_used >= DISK_WARNING:
        critical = f.disk_used >= DISK_CRITICAL
        alerts.append(
            Alert(
                "disk",
                f"Disk {f.disk_used:.0%} full",
                "media files, database and images share it: delete orphan media folders or "
                "free space on the server",
                "critical" if critical else "warning",
                "/admin/system#health",
                quiet=(2 if critical else 6) * HOUR,
            )
        )
    if f.new_flagged:
        n = len(f.new_flagged)
        alerts.append(
            Alert(
                "flagged",
                f"{_plural(n, 'debate')} flagged for moderation",
                _listing([title or "Untitled debate" for _, title in f.new_flagged]),
                "warning",
                "/admin/moderation",
            )
        )
    if f.new_topups:
        total = sum(amount for _, amount, _ in f.new_topups)
        rows = [f"{email or 'deleted account'} {_usd(amount)}" for _, amount, email in f.new_topups]
        single = len(f.new_topups) == 1
        alerts.append(
            Alert(
                "topup",
                f"Top-up {_usd(total)}" if single else f"{len(rows)} top-ups, {_usd(total)}",
                _listing(rows, 5),
                "info",
                f"/admin/users/{f.new_topups[0][0]}" if single else "/admin/finance",
            )
        )
    return alerts


# --- gathering the facts (worker side) --------------------------------------------------------


def new_ids(redis: Redis, key: str, current: Iterable[str]) -> set[str]:
    """Ids in `current` the previous check did not see. The first check (nothing stored yet)
    reports none, so a fresh Redis does not replay old events."""
    now_ids = set(current)
    raw = redis.get(key)
    redis.set(key, json.dumps(sorted(now_ids)), ex=SEEN_TTL)
    if raw is None:
        return set()
    try:
        before = set(json.loads(raw))
    except (ValueError, TypeError):
        return set()
    return now_ids - before


def seen_twice(redis: Redis, key: str, current: Iterable[str]) -> set[str]:
    """Ids found by this check and the previous one too (a run between two jobs is not stuck)."""
    now_ids = set(current)
    raw = redis.get(key)
    redis.set(key, json.dumps(sorted(now_ids)), ex=SEEN_TTL)
    try:
        before = set(json.loads(raw)) if raw else set()
    except (ValueError, TypeError):
        before = set()
    return now_ids & before


def _stuck(db: Session, redis: Redis, now: datetime) -> tuple[int, int]:
    from app.services.heartbeat import alive
    from app.services.queue_manager import MEDIA_QUEUE_NAME, QUEUE_NAME, waiting_debates

    old = now - STUCK_AFTER
    debates = db.scalars(
        select(Debate.id).where(
            Debate.status.in_(("queued", "running")),
            func.coalesce(Debate.started_at, Debate.created_at) < old,
        )
    ).all()
    media = db.scalars(
        select(Debate.id).where(
            Debate.media_status.in_(("queued", "running")), Debate.created_at < old
        )
    ).all()
    waiting_turns = waiting_debates(redis, QUEUE_NAME) if debates else set()
    waiting_media = waiting_debates(redis, MEDIA_QUEUE_NAME) if media else set()
    lost_debates = [
        str(i)
        for i in debates
        if str(i) not in waiting_turns and not alive(debate_beat_key(str(i)))
    ]
    lost_media = [
        str(i) for i in media if str(i) not in waiting_media and not alive(media_beat_key(str(i)))
    ]
    return (
        len(seen_twice(redis, "alerts:stuck:debates", lost_debates)),
        len(seen_twice(redis, "alerts:stuck:media", lost_media)),
    )


def _openrouter_balance(redis: Redis) -> float | None:
    with contextlib.suppress(RedisError, ValueError, TypeError):
        cached = redis.get(BALANCE_KEY)
        if cached:
            return json.loads(cached).get("balance")
    if not settings.OPENROUTER_API_KEY:
        return None
    from app.services.openrouter_client import openrouter_client

    balance, error = asyncio.run(openrouter_client.get_credits())
    with contextlib.suppress(RedisError):
        redis.set(BALANCE_KEY, json.dumps({"balance": balance, "error": error}), ex=BALANCE_SECONDS)
    return balance


def _disk_used() -> float | None:
    root = settings.media_root_path
    try:
        usage = shutil.disk_usage(root if root.exists() else root.parent)
    except OSError:
        return None
    return usage.used / usage.total if usage.total else None


def gather(db: Session, redis: Redis, now: datetime) -> Facts:
    facts = Facts()
    failures = db.execute(
        select(AdminAuditLog.ip).where(
            AdminAuditLog.action.in_(LOGIN_FAILURES),
            AdminAuditLog.created_at >= now - LOGIN_WINDOW,
        )
    ).scalars()
    ips = list(failures)
    facts.login_failures = len(ips)
    facts.login_ips = sorted({ip for ip in ips if ip})

    flagged = dict(
        db.execute(
            select(Debate.id, Debate.title).where(Debate.moderation_status == "flagged")
        ).all()
    )
    fresh = new_ids(redis, "alerts:seen:flagged", (str(i) for i in flagged))
    facts.new_flagged = [(str(i), title) for i, title in flagged.items() if str(i) in fresh]

    counts = db.execute(
        select(func.count(), func.count().filter(Debate.status == "error")).where(
            Debate.status.in_(("completed", "error", "stopped")),
            Debate.ended_at >= now - ERROR_WINDOW,
        )
    ).one()
    facts.finished_last_hour, facts.failed_last_hour = int(counts[0] or 0), int(counts[1] or 0)

    facts.stuck_debates, facts.stuck_media = _stuck(db, redis, now)

    topups = db.execute(
        select(CreditTransaction.id, CreditTransaction.user_id, CreditTransaction.amount_usd)
        .where(
            CreditTransaction.kind == "topup",
            CreditTransaction.created_at >= now - TOPUP_WINDOW,
        )
        .order_by(CreditTransaction.created_at)
    ).all()
    fresh = new_ids(redis, "alerts:seen:topups", (str(row[0]) for row in topups))
    users = {row[1] for row in topups if str(row[0]) in fresh}
    emails = (
        dict(db.execute(select(User.id, User.email).where(User.id.in_(users))).all())
        if users
        else {}
    )
    facts.new_topups = [
        (str(uid), float(amount), emails.get(uid))
        for tid, uid, amount in topups
        if str(tid) in fresh
    ]

    facts.openrouter_balance = _openrouter_balance(redis)
    if settings.ELEVENLABS_API_KEY:
        from app.services.media.tts.elevenlabs import system_key_status, system_quota

        ok, reason = system_key_status()
        if not ok:
            facts.elevenlabs_rejected = reason or "the key does not work"
        else:
            quota = system_quota()
            if quota:
                facts.elevenlabs_used, facts.elevenlabs_limit = quota["used"], quota["limit"]
    facts.disk_used = _disk_used()
    return facts


def check_alerts_job() -> None:
    """RQ job (scheduler, every CHECK_SECONDS): gather the facts and raise what is due."""
    from app.core.sync_db import get_sync_session

    redis = get_sync_redis()
    if not redis.set(LOCK_KEY, "1", nx=True, ex=JOB_TIMEOUT):
        return
    try:
        with get_sync_session() as db:
            facts = gather(db, redis, utcnow())
        for alert in decide(facts):
            raise_sync(alert, redis)
    finally:
        redis.delete(LOCK_KEY)
