"""What every paid provider call costs (`provider_usage`), for the admin console's money pages.

`record` is called once per call (or try) by the places that talk to providers: the turn stream
(orchestrator._generate), the worker's LLM helpers (media/llm.py) and the TTS step. The debate a
call belongs to comes from `attributed` jobs through a context variable, so deep helpers (the
director, sketches, pictures) need no extra arguments; `ContextThreadPool` carries it into
worker threads. Writing never fails the caller: a lost row is logged, never raised.

Calls made for an account outside a debate (the wizard's AI topic ideas) name it with
`on_behalf_of`.

`key_owner` says who pays the provider: "user" when the call ran on the account's own key (the
debate's OpenRouter key in Redis, an own ElevenLabs key), "system" otherwise.
"""

import functools
import logging
import uuid
from collections.abc import Callable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from contextvars import ContextVar, copy_context
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import select

from app.core.sync_db import get_sync_session
from app.models.models import Debate, ProviderUsage

logger = logging.getLogger(__name__)

KeyOwner = Literal["system", "user"]
ErrorKind = Literal[
    "rate_limit",
    "provider_5xx",
    "connection",
    "timeout",
    "empty",
    "classifier",
    "auth",
    "credits",
    "bad_request",
    "free_quota",
    "other",
]

_debate: ContextVar[str | None] = ContextVar("usage_debate", default=None)
_user: ContextVar[str | None] = ContextVar("usage_user", default=None)


def key_owner(api_key: str | None) -> KeyOwner:
    """Worker calls pass a key only when it is the user's (else the client uses the system's)."""
    return "user" if api_key else "system"


def current_debate() -> str | None:
    return _debate.get()


def attributed[**P, R](job: Callable[P, R]) -> Callable[P, R]:
    """Decorate an RQ job whose first argument (or `debate_id`) is a debate id: provider calls
    made while it runs are booked to that debate."""

    @functools.wraps(job)
    def run(*args: P.args, **kwargs: P.kwargs) -> R:
        debate_id = str(kwargs.get("debate_id") or (args[0] if args else "")) or None
        token = _debate.set(debate_id)
        try:
            return job(*args, **kwargs)
        finally:
            _debate.reset(token)

    return run


@contextmanager
def on_behalf_of(user_id: str | None) -> Iterator[None]:
    """Book the provider calls made inside to this account (calls outside any debate)."""
    token = _user.set(user_id)
    try:
        yield
    finally:
        _user.reset(token)


class ContextThreadPool(ThreadPoolExecutor):
    """A thread pool whose tasks see the submitting thread's context (the current debate)."""

    def submit[**P, R](self, fn: Callable[P, R], /, *args: P.args, **kwargs: P.kwargs) -> Future[R]:
        context = copy_context()
        return super().submit(context.run, fn, *args, **kwargs)  # type: ignore[arg-type]


def classify_error(
    status: int | None,
    *,
    timed_out: bool = False,
    empty: bool = False,
    classifier: bool = False,
    free_quota: bool = False,
) -> ErrorKind:
    """One word for why a call failed, for failure rates by model and provider."""
    if free_quota:
        return "free_quota"
    if classifier:
        return "classifier"
    if timed_out:
        return "timeout"
    if empty:
        return "empty"
    if status is None:
        return "connection"
    if status == 429:
        return "rate_limit"
    if status in (401, 403):
        return "auth"
    if status == 402:
        return "credits"
    if status >= 500:
        return "provider_5xx"
    if 400 <= status < 500:
        return "bad_request"
    return "other"


def _number(usage: dict[str, Any] | None, *names: str) -> int:
    for name in names:
        value = (usage or {}).get(name)
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                return 0
    return 0


def usage_row(
    purpose: str,
    *,
    model: str,
    key: KeyOwner,
    usage: dict[str, Any] | None = None,
    provider: str = "openrouter",
    chars: int = 0,
    cost_usd: float | None = None,
    ok: bool = True,
    error_kind: str | None = None,
    duration_ms: int | None = None,
    debate_id: str | None = None,
    meta: dict[str, Any] | None = None,
) -> ProviderUsage:
    """The row for one call (pure; `record` writes it). The cost is OpenRouter's own figure
    from `usage.cost` unless `cost_usd` is given (TTS estimates)."""
    cost = cost_usd if cost_usd is not None else float((usage or {}).get("cost") or 0.0)
    debate = debate_id if debate_id is not None else current_debate()
    user = _user.get()
    return ProviderUsage(
        purpose=purpose[:32],
        provider=provider[:16],
        model=(model or "unknown")[:160],
        key_owner=key,
        tokens_in=_number(usage, "prompt_tokens", "tokens_in"),
        tokens_out=_number(usage, "completion_tokens", "tokens_out"),
        chars=max(0, int(chars)),
        cost_usd=Decimal(str(round(max(0.0, cost), 6))),
        ok=ok,
        error_kind=error_kind if not ok else None,
        duration_ms=duration_ms,
        debate_id=uuid.UUID(debate) if debate else None,
        user_id=uuid.UUID(user) if user and not debate else None,  # a debate names its owner
        meta_json=meta or {},
    )


def record(purpose: str, **fields: Any) -> None:
    """Write one usage row (see `usage_row` for the fields). Never raises."""
    try:
        row = usage_row(purpose, **fields)
    except Exception:
        logger.warning("Unusable usage record for %s", purpose, exc_info=True)
        return
    _write(row)


def _write(row: ProviderUsage) -> None:
    try:
        with get_sync_session() as db:
            if row.debate_id is not None:
                owner = db.execute(select(Debate.user_id).where(Debate.id == row.debate_id)).first()
                if owner is None:  # deleted meanwhile: the money was still spent
                    row.debate_id = None
                else:
                    row.user_id = owner[0]
            db.add(row)
            db.commit()
    except Exception:
        logger.warning("Could not record %s usage of %s", row.purpose, row.model, exc_info=True)
