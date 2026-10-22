"""The admin overview (`GET /api/admin/overview`): tiles, series, money, the "needs attention"
list and the period's tops, in one cached answer.

Statistics run in a read-only transaction with a statement timeout (`access.read_only_db`).
The answer is cached in Redis for CACHE_SECONDS per period and permission scope (`refresh=true`
skips it); provider balances are cached a few minutes on their own. Money and the top spenders
need the `money` permission (a moderator sees the rest).
"""

import contextlib
import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.admin.access import AdminContext, read_only_db, require_admin
from app.core.config import settings
from app.core.redis import debate_beat_key, get_async_redis, media_beat_key
from app.models.models import utcnow
from app.schemas.admin import OverviewOut, OverviewPeriod
from app.services import mail
from app.services.admin import stats
from app.services.admin.stats import Signals
from app.services.media.tts.elevenlabs import system_key_status, system_quota
from app.services.openrouter_client import openrouter_client
from app.services.views import embedding_sites

logger = logging.getLogger(__name__)
router = APIRouter()

CACHE_SECONDS = 60
BALANCE_SECONDS = 300
BALANCE_KEY = "admin:openrouter_balance"
BACKUP_KEY = "backup:last"  # written by scripts/backup-db.sh


def _cache_key(period: str, with_money: bool) -> str:
    return f"admin:overview:{period}:{'money' if with_money else 'basic'}"


async def _openrouter_balance() -> tuple[float | None, str | None]:
    """The system key's balance, cached so the overview does not call OpenRouter every time."""
    redis = get_async_redis()
    try:
        cached = await redis.get(BALANCE_KEY)
        if cached:
            data = json.loads(cached)
            return data.get("balance"), data.get("error")
    except (RedisError, ValueError):
        pass
    if not settings.OPENROUTER_API_KEY:
        return None, None
    balance, error = await openrouter_client.get_credits()
    with contextlib.suppress(RedisError):
        await redis.set(
            BALANCE_KEY, json.dumps({"balance": balance, "error": error}), ex=BALANCE_SECONDS
        )
    return balance, error


async def _stuck(ids: list[str], key_of: Callable[[str], str]) -> int:
    """How many of the runs have no live heartbeat (their worker is gone)."""
    redis = get_async_redis()
    missing = 0
    try:
        for run_id in ids:
            if not await redis.exists(key_of(run_id)):
                missing += 1
    except RedisError:
        return 0
    return missing


async def _backup_age_hours(now: datetime) -> float | None:
    try:
        raw = await get_async_redis().get(BACKUP_KEY)
        at = datetime.fromisoformat(json.loads(raw)["at"].replace("Z", "+00:00")) if raw else None
    except (RedisError, ValueError, KeyError, TypeError):
        return None
    return (now - at.astimezone(UTC)).total_seconds() / 3600 if at else None


async def _signals(db: AsyncSession, now: datetime) -> Signals:
    signals = await stats.attention_counts(db, now)
    debates, media = await stats.active_runs(db, now)
    signals.stuck_debates = await _stuck(debates, debate_beat_key)
    signals.stuck_media = await _stuck(media, media_beat_key)
    signals.openrouter_balance, signals.openrouter_error = await _openrouter_balance()
    if settings.ELEVENLABS_API_KEY:
        ok, reason = await run_in_threadpool(system_key_status)
        signals.elevenlabs_ok, signals.elevenlabs_reason = ok, reason
        quota = await run_in_threadpool(system_quota) if ok else None
        if quota:
            signals.elevenlabs_used, signals.elevenlabs_limit = quota["used"], quota["limit"]
    signals.trending_every_hours = settings.TRENDING_REFRESH_HOURS
    signals.mail_off = settings.is_production and not mail.enabled()
    signals.check_backups = settings.is_production
    signals.backup_age_hours = await _backup_age_hours(now)
    return signals


async def build_overview(
    db: AsyncSession, period: OverviewPeriod, *, with_money: bool, now: datetime
) -> OverviewOut:
    window = stats.window_for(period, now, await stats.first_account(db))
    signals = await _signals(db, now)
    return OverviewOut.model_validate(
        {
            "period": period,
            "start": window.start,
            "end": window.end,
            "previous_start": window.previous_start,
            "bucket": window.bucket,
            "generated_at": now,
            "users": await stats.user_tiles(db, window, now),
            "debates": await stats.debate_tiles(db, window),
            "money": await stats.money(db, window) if with_money else None,
            "series": await stats.series(db, window, with_money=with_money),
            "attention": stats.attention_items(signals),
            "top_models": await stats.top_models(db, window),
            "top_spenders": await stats.top_spenders(db, window) if with_money else None,
            "top_debates": await stats.top_debates(db, window),
            "views_since": await stats.views_since(db),
            "embeds": await embedding_sites(),
        }
    )


def _with_admin_items(out: OverviewOut, ctx: AdminContext) -> OverviewOut:
    """Items about the signed-in admin (not part of the shared cache)."""
    if settings.admin_skip_2fa:
        return out
    left = len(ctx.user.recovery_codes_json or [])
    extra = stats.attention_items(Signals(recovery_codes_left=left))
    return out.model_copy(update={"attention": [*out.attention, *extra]}) if extra else out


@router.get("/overview", response_model=OverviewOut)
async def overview(
    period: OverviewPeriod = "7d",
    refresh: bool = False,
    ctx: AdminContext = Depends(require_admin("console")),
    db: AsyncSession = Depends(read_only_db),
) -> OverviewOut:
    with_money = ctx.can("money")
    key = _cache_key(period, with_money)
    redis = get_async_redis()
    if not refresh:
        try:
            cached = await redis.get(key)
            if cached:
                return _with_admin_items(OverviewOut.model_validate_json(cached), ctx)
        except (RedisError, ValueError):
            logger.warning("Overview cache unreadable, building it again")
    out = await build_overview(db, period, with_money=with_money, now=utcnow())
    with contextlib.suppress(RedisError):
        await redis.set(key, out.model_dump_json(), ex=CACHE_SECONDS)
    return _with_admin_items(out, ctx)
