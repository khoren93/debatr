"""Limits of free debates: runs on the system key whose models are all free, by accounts
without credits.

They cost us OpenRouter's free-model quota, which the whole site shares (1000 requests a day,
a debate takes about a dozen), and their visual scenes. So such an account gets
`free_debates_per_day` of them in any 24 hours, each of at most `free_max_rounds` rounds and
`free_max_debaters` debaters with one of the `free_lengths` reply lengths (levers of the admin
console; 0 or an empty list = no limit). Credits or an own OpenRouter key lift every limit.

Only new runs count (a create or a draft start, never a resume), in a Redis sorted set per
account, so deleting a debate does not give its run back.
"""

import logging
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import HTTPException, status
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.redis import free_runs_key, get_async_redis
from app.models.models import User
from app.schemas.schemas import DebateConfig, FreeDebatesOut, FreeRunsOut
from app.services import runtime_settings
from app.services.free_quota import is_free_model
from app.services.runtime_settings import Levers

logger = logging.getLogger(__name__)

WINDOW_SECONDS = 24 * 3600
# What the site calls the presets (the wizard's labels).
LENGTH_NAMES = {"very_short": "short", "short": "medium", "medium": "long", "long": "very long"}


@dataclass(frozen=True)
class FreeRuns:
    per_day: int
    used: int
    oldest: float | None  # unix time of the oldest run in the window

    @property
    def left(self) -> int:
        return max(0, self.per_day - self.used)

    def next_at(self) -> datetime | None:
        """When the oldest run leaves the window, once none is left (else None)."""
        if self.per_day <= 0 or self.left > 0 or self.oldest is None:
            return None
        return datetime.fromtimestamp(self.oldest + WINDOW_SECONDS, UTC)

    def out(self) -> FreeRunsOut:
        return FreeRunsOut(
            per_day=self.per_day, used=self.used, left=self.left, next_at=self.next_at()
        )


def is_free_run(config: DebateConfig, *, own_key: bool, balance: Decimal | float) -> bool:
    """A run these limits apply to: the system key, every model free, no credits."""
    models = [p.model_id for p in config.participants]
    return not own_key and float(balance) <= 0 and bool(models) and all(map(is_free_model, models))


def site_limits(levers: Levers) -> FreeDebatesOut:
    return FreeDebatesOut(
        per_day=levers.free_debates_per_day,
        max_rounds=levers.free_max_rounds,
        max_debaters=levers.free_max_debaters,
        lengths=list(levers.free_lengths),
    )


def way_out() -> str:
    if settings.payments_mode == "disabled":
        return "For more, add your own OpenRouter key on the Account page."
    return "For more, add credits or your own OpenRouter key on the Account page."


def _words(items: list[str]) -> str:
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} or {items[-1]}"


def size_problem(config: DebateConfig, levers: Levers) -> str | None:
    """Why a free run is too big for the levers, or None."""
    debaters = sum(1 for p in config.participants if p.role == "debater")
    rules: list[str] = []
    if levers.free_max_rounds and config.num_rounds > levers.free_max_rounds:
        rules.append(f"up to {levers.free_max_rounds} rounds")
    if levers.free_max_debaters and debaters > levers.free_max_debaters:
        rules.append(f"up to {levers.free_max_debaters} debaters")
    if levers.free_lengths and config.length_preset not in levers.free_lengths:
        rules.append(f"{_words([LENGTH_NAMES[x] for x in levers.free_lengths])} replies")
    if not rules:
        return None
    return f"Debates on free models have {' and '.join(rules)}. {way_out()}"


def daily_problem(runs: FreeRuns, now: float) -> str | None:
    """Why the account has no free run left today, or None."""
    if runs.per_day <= 0 or runs.left > 0:
        return None
    wait = max(60, int((runs.oldest or now) + WINDOW_SECONDS - now))
    hours, minutes = divmod(wait // 60, 60)
    when = f"{hours} h {minutes} min" if hours else f"{minutes} min"
    return (
        f"You have started your {runs.per_day} free debates of the last 24 hours: the next one "
        f"is free in {when}. {way_out()}"
    )


async def _runs(redis: Redis, user_id: uuid.UUID, per_day: int, now: float) -> FreeRuns:
    key = free_runs_key(str(user_id))
    await redis.zremrangebyscore(key, 0, now - WINDOW_SECONDS)
    scored = await redis.zrange(key, 0, -1, withscores=True)
    scores = sorted(float(score) for _member, score in scored)
    return FreeRuns(per_day=per_day, used=len(scores), oldest=scores[0] if scores else None)


async def check(
    user: User | None, config: DebateConfig, *, own_key: bool
) -> tuple[FreeRuns | None, str | None]:
    """For the estimate: the day's allowance (signed in) and why the run would be refused."""
    if not is_free_run(config, own_key=own_key, balance=user.credits_usd if user else 0):
        return None, None
    levers = await runtime_settings.current()
    problem = size_problem(config, levers)
    if user is None or levers.free_debates_per_day <= 0:
        return None, problem
    try:
        runs = await _runs(get_async_redis(), user.id, levers.free_debates_per_day, time.time())
    except (RedisError, OSError):
        logger.warning("Free runs of %s unreadable", user.id)
        return None, problem
    return runs, problem or daily_problem(runs, time.time())


async def take(db: AsyncSession, user: User, config: DebateConfig, *, own_key: bool) -> None:
    """At a create or a draft start: refuse a free run that is too big (402) or over the day's
    allowance (429), else count it. The user's row stays locked until the caller commits, so two
    requests at once cannot both take the last run."""
    if not is_free_run(config, own_key=own_key, balance=user.credits_usd):
        return
    levers = await runtime_settings.current()
    if problem := size_problem(config, levers):
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=problem)
    if levers.free_debates_per_day <= 0:
        return
    await db.execute(select(User.id).where(User.id == user.id).with_for_update())
    now = time.time()
    try:
        redis = get_async_redis()
        runs = await _runs(redis, user.id, levers.free_debates_per_day, now)
        if problem := daily_problem(runs, now):
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=problem)
        key = free_runs_key(str(user.id))
        await redis.zadd(key, {uuid.uuid4().hex: now})
        await redis.expire(key, WINDOW_SECONDS + 3600)
    except (RedisError, OSError):
        # Queueing the run needs Redis too and answers for it; a lost count is no harm.
        logger.warning("Free runs of %s not counted: Redis unavailable", user.id)
