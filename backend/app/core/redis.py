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


def debate_beat_key(debate_id: str) -> str:
    """Heartbeat of the job running a debate step (app.services.heartbeat)."""
    return f"debate:{debate_id}:beat"


def media_beat_key(debate_id: str) -> str:
    """Heartbeat of the job building a debate's audio."""
    return f"debate:{debate_id}:media_beat"


def cover_beat_key(debate_id: str) -> str:
    """Heartbeat of the job drawing a debate's AI cover."""
    return f"debate:{debate_id}:cover_beat"


def recovery_key(kind: str, debate_id: str) -> str:
    """Recovery bookkeeping of one run (app.services.recovery): `seen` / `attempts`."""
    return f"recovery:{kind}:{debate_id}"


def free_models_window_key(minute: int) -> str:
    """Requests to `:free` models on the system key in one clock minute."""
    return f"ratelimit:free-models:{minute}"


def free_runs_key(user_id: str) -> str:
    """Sorted set of the account's free debates (score = start time): the daily allowance."""
    return f"free-runs:{user_id}"


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


def email_token_key(kind: str, token_hash: str) -> str:
    """A link we mailed (services/email_check): `verify` or `reset`, by the hash of its token."""
    return f"email:{kind}:{token_hash}"


def trending_lock_key() -> str:
    """Held while a trending-topics batch is being built (app.services.trending)."""
    return "trending:refresh:lock"


def trending_queued_key() -> str:
    """Set by the API when it enqueues a refresh, so stale reads enqueue it only once."""
    return "trending:refresh:queued"


# --- Admin console (app.admin.access, app.services.admin) --------------------


def admin_session_key(token_hash: str) -> str:
    """One admin console session, by the SHA-256 of its cookie (the cookie is never stored)."""
    return f"admin:session:{token_hash}"


def admin_user_sessions_key(user_id: str) -> str:
    """Set of the session hashes of one admin, to list and revoke them."""
    return f"admin:sessions:{user_id}"


def admin_ticket_key(ticket_hash: str) -> str:
    """A sign-in between the password and the TOTP code (minutes only)."""
    return f"admin:ticket:{ticket_hash}"


def admin_enroll_key(user_id: str) -> str:
    """Hash of the one-time enrollment code printed by `app.manage admin grant`."""
    return f"admin:enroll:{user_id}"


def admin_totp_step_key(user_id: str) -> str:
    """Last accepted TOTP time step of an admin, so a code is never accepted twice."""
    return f"admin:totp_step:{user_id}"


def admin_totp_failures_key(user_id: str) -> str:
    """Wrong codes of an admin in the current window (locks the second factor)."""
    return f"admin:totp_fail:{user_id}"
