"""Minimal fixed-window rate limiting backed by Redis."""

import logging

from fastapi import HTTPException, Request, status
from redis.exceptions import RedisError

from app.core.config import settings
from app.core.redis import get_async_redis, rate_limit_key

logger = logging.getLogger(__name__)

WINDOW_SECONDS = 3600
DEVICE_CODE_LOOKUPS_PER_HOUR = 60
ADMIN_LOGIN_ATTEMPTS = 5
ADMIN_LOGIN_WINDOW_SECONDS = 15 * 60


def _client_id(request: Request) -> str:
    return request.client.host if request.client else "unknown"


async def enforce_limit(
    request: Request, *, bucket: str, limit: int, window_seconds: int, what: str
) -> None:
    """Fixed-window counter per client IP. `limit <= 0` disables the check."""
    if limit <= 0:
        return

    key = rate_limit_key(bucket, _client_id(request))
    try:
        redis = get_async_redis()
        async with redis.pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.expire(key, window_seconds, nx=True)
            pipe.ttl(key)
            count, _, ttl = await pipe.execute()
    except RedisError:
        logger.warning("Rate limiter unavailable; allowing request")
        return

    if int(count) > limit:
        retry_after = max(int(ttl), 1) if isinstance(ttl, int) else window_seconds
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many {what}. Try again in {-(-retry_after // 60)} minutes.",
            headers={"Retry-After": str(retry_after)},
        )


async def enforce_debate_create_limit(request: Request) -> None:
    """FastAPI dependency: cap debates created per client IP per hour."""
    await enforce_limit(
        request,
        bucket="create_debate",
        limit=settings.DEBATE_CREATE_RATE_LIMIT,
        window_seconds=WINDOW_SECONDS,
        what="debates created",
    )


async def enforce_login_limit(request: Request) -> None:
    """Cap login/registration attempts per client IP per hour."""
    await enforce_limit(
        request,
        bucket="login",
        limit=settings.LOGIN_RATE_LIMIT,
        window_seconds=WINDOW_SECONDS,
        what="sign-in attempts",
    )


async def enforce_admin_login_limit(request: Request) -> None:
    """Cap sign-in attempts to the admin panel per IP: one guessed password opens everything,
    so this limit is fixed and much lower than LOGIN_RATE_LIMIT."""
    await enforce_limit(
        request,
        bucket="admin_login",
        limit=ADMIN_LOGIN_ATTEMPTS,
        window_seconds=ADMIN_LOGIN_WINDOW_SECONDS,
        what="sign-in attempts",
    )


async def enforce_device_code_limit(request: Request) -> None:
    """Cap look-ups of `debatr login` codes per IP: a signed-in user could otherwise guess the
    pending code of someone else's terminal and hand it a token of their own account."""
    await enforce_limit(
        request,
        bucket="device_code",
        limit=DEVICE_CODE_LOOKUPS_PER_HOUR,
        window_seconds=WINDOW_SECONDS,
        what="device code checks",
    )
