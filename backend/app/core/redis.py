"""Shared Redis connections and key helpers."""

import redis
from redis import asyncio as aioredis

from app.core.config import settings

_sync_client: redis.Redis | None = None
_async_client: aioredis.Redis | None = None


def get_sync_redis() -> redis.Redis:
    """Blocking client for RQ and the worker. Created lazily per process."""
    global _sync_client
    if _sync_client is None:
        _sync_client = redis.from_url(settings.REDIS_URL)
    return _sync_client


def get_async_redis() -> aioredis.Redis:
    """Async client for the API process (pub/sub, rate limiting)."""
    global _async_client
    if _async_client is None:
        _async_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    return _async_client


async def close_async_redis() -> None:
    global _async_client
    if _async_client is not None:
        await _async_client.aclose()
        _async_client = None


# --- Key layout -----------------------------------------------------------


def debate_channel(debate_id: str) -> str:
    return f"debate:{debate_id}"


def provider_key_key(debate_id: str) -> str:
    return f"debate:{debate_id}:provider_key"


def stop_flag_key(debate_id: str) -> str:
    return f"debate:{debate_id}:stop"


def tts_key_key(debate_id: str) -> str:
    """User-supplied TTS (ElevenLabs) key for one media build. Never stored in Postgres."""
    return f"debate:{debate_id}:tts_key"


def rate_limit_key(bucket: str, client_id: str) -> str:
    return f"ratelimit:{bucket}:{client_id}"


def device_request_key(device_code_hash: str) -> str:
    """State of one `debatr login` device request (app.services.api_tokens), by the hash of its
    secret device code."""
    return f"device:{device_code_hash}"


def device_user_code_key(user_code: str) -> str:
    """The code the user confirms in the browser -> hash of the device code."""
    return f"device:user:{user_code}"


def device_claim_key(device_code_hash: str) -> str:
    """Set once when the request is approved or denied, so it is decided only once."""
    return f"device:{device_code_hash}:claim"
