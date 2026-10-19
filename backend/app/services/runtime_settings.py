"""Levers the admin console changes without a deploy (the `runtime_settings` table).

Only the fields of `Levers` exist, each with its type and limits; without a row a lever takes
its env setting, so nothing changes until an admin moves it. Rows are read through a short
per-process cache (CACHE_SECONDS): a change reaches every API process and worker within that
time. `current()` serves the API, `current_sync()` the workers. Changing a lever is the
console's job (app/api/admin/routes_settings.py, audited); this module only reads and checks.
A broken row (a value from an older version, a type that no longer fits) is ignored with a
warning instead of failing requests.
"""

import logging
import re
import time
from typing import Any, get_args

from fastapi import HTTPException, status
from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings
from app.core.db import AsyncSessionLocal
from app.core.sync_db import get_sync_session
from app.models.models import RuntimeSetting
from app.schemas.schemas import LengthPreset
from app.services.alert_events import KINDS as ALERT_KINDS
from app.services.free_router import FREE_SUFFIX

logger = logging.getLogger(__name__)

CACHE_SECONDS = 5.0
LENGTHS: tuple[str, ...] = get_args(LengthPreset)
MODEL_ID = re.compile(r"^[\w.\-:/]{1,120}$")
MAX_DISABLED_MODELS = 200
DEFAULT_MAINTENANCE_MESSAGE = (
    "Debatr is being updated: new debates and audio builds are paused for a few minutes. "
    "Debates already running finish as usual."
)


class Levers(BaseModel):
    """The levers and their limits (the console shows the same ranges)."""

    # New accounts (POST /api/auth/register); signing in keeps working.
    registration_open: bool = True
    # No new debates, resumes or audio builds; runs already going finish.
    maintenance: bool = False
    maintenance_message: str = Field(default="", max_length=300)
    # Hidden from the model list (wizard, CLI, MCP), refused when a debate starts; the Free
    # Router skips them (orchestrator, free_router.fallback_models).
    disabled_models: list[str] = Field(default_factory=list, max_length=MAX_DISABLED_MODELS)
    signup_bonus_usd: float = Field(default=0.0, ge=0, le=100)
    free_models_per_minute: int = Field(default=18, ge=0, le=20)
    max_active_debates_per_user: int = Field(default=2, ge=0, le=20)
    max_active_media_per_user: int = Field(default=2, ge=0, le=20)
    # Telegram alerts that are not sent (kinds of services/alert_events; the rest go out).
    muted_alerts: list[str] = Field(default_factory=list, max_length=len(ALERT_KINDS))
    # Structures the verdict and answers the gallery check of debates on free models only
    # (orchestrator._verdict_model); `:free` only, so such a debate never costs us. Empty: the
    # paid VERDICT_MODEL does it.
    free_verdict_model: str = Field(default="", max_length=120)
    # Free debates (services/free_limits): a day's allowance per account and their size;
    # 0 / an empty list = no limit.
    free_debates_per_day: int = Field(default=5, ge=0, le=100)
    free_max_rounds: int = Field(default=3, ge=0, le=10)
    free_max_debaters: int = Field(default=4, ge=0, le=7)
    free_lengths: list[LengthPreset] = Field(default_factory=lambda: ["very_short", "short"])

    @field_validator("maintenance_message")
    @classmethod
    def _message(cls, value: str) -> str:
        return " ".join(value.split())

    @field_validator("disabled_models")
    @classmethod
    def _models(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        for raw in value:
            model_id = raw.strip()
            if not MODEL_ID.match(model_id):
                raise ValueError(f"not a model id: {raw[:40]!r}")
            if model_id not in cleaned:
                cleaned.append(model_id)
        return cleaned

    @field_validator("free_verdict_model")
    @classmethod
    def _free_model(cls, value: str) -> str:
        model_id = value.strip()
        if model_id and not (MODEL_ID.match(model_id) and model_id.endswith(FREE_SUFFIX)):
            raise ValueError(f"not a free (:free) model: {value[:40]!r}")
        return model_id

    @field_validator("free_lengths")
    @classmethod
    def _lengths(cls, value: list[str]) -> list[str]:
        return [length for length in LENGTHS if length in value]  # shortest first, no repeats

    @field_validator("muted_alerts")
    @classmethod
    def _alerts(cls, value: list[str]) -> list[str]:
        unknown = [kind for kind in value if kind not in ALERT_KINDS]
        if unknown:
            raise ValueError(f"no such alert: {unknown[0][:40]!r}")
        return [kind for kind in ALERT_KINDS if kind in value]  # the catalogue's order

    def notice(self) -> str:
        """What a refused request says during maintenance."""
        return self.maintenance_message or DEFAULT_MAINTENANCE_MESSAGE


LEVER_KEYS: tuple[str, ...] = tuple(Levers.model_fields)


def defaults() -> dict[str, Any]:
    """Each lever's value without a row: its env setting (or the built-in default)."""
    return {
        **Levers().model_dump(),
        "signup_bonus_usd": max(0.0, min(100.0, settings.SIGNUP_BONUS_USD)),
        "free_models_per_minute": max(0, min(20, settings.FREE_MODELS_PER_MINUTE)),
        "max_active_debates_per_user": max(0, min(20, settings.MAX_ACTIVE_DEBATES_PER_USER)),
        "max_active_media_per_user": max(0, min(20, settings.MAX_ACTIVE_MEDIA_PER_USER)),
        "free_verdict_model": _env_free_model(),
        "free_debates_per_day": max(0, min(100, settings.FREE_DEBATES_PER_DAY)),
        "free_max_rounds": max(0, min(10, settings.FREE_MAX_ROUNDS)),
        "free_max_debaters": max(0, min(7, settings.FREE_MAX_DEBATERS)),
        "free_lengths": [
            p for p in LENGTHS if p in settings.FREE_LENGTHS.replace(" ", "").split(",")
        ],
    }


def _env_free_model() -> str:
    try:
        return Levers(free_verdict_model=settings.FREE_VERDICT_MODEL).free_verdict_model
    except ValidationError:
        logger.warning("FREE_VERDICT_MODEL is not a :free model, ignoring it")
        return ""


def validate_value(key: str, value: Any) -> Any:
    """The value as stored, or ValueError with a message for the console."""
    if key not in LEVER_KEYS:
        raise ValueError(f"No such setting: {key}")
    try:
        levers = Levers.model_validate({**defaults(), key: value})
    except ValidationError as exc:
        error = exc.errors()[0]
        raise ValueError(f"{key}: {error['msg']}") from None
    return getattr(levers, key)


def resolve(stored: dict[str, Any]) -> Levers:
    """Defaults with the valid stored values on top."""
    values = defaults()
    for key, raw in stored.items():
        if key not in LEVER_KEYS:
            continue
        try:
            values[key] = validate_value(key, raw)
        except ValueError as exc:
            logger.warning("Ignoring runtime setting %s: %s", key, exc)
    return Levers.model_validate(values)


# --- reading (cached per process) ---------------------------------------------------------------

_cache: tuple[float, dict[str, Any]] | None = None


def invalidate() -> None:
    global _cache
    _cache = None


def _fresh() -> dict[str, Any] | None:
    if _cache is not None and time.monotonic() - _cache[0] < CACHE_SECONDS:
        return _cache[1]
    return None


def _remember(stored: dict[str, Any]) -> None:
    global _cache
    _cache = (time.monotonic(), stored)


def _stale() -> dict[str, Any]:
    return _cache[1] if _cache is not None else {}


async def _stored() -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        rows = await db.execute(select(RuntimeSetting.key, RuntimeSetting.value_json))
        return {key: value for key, value in rows.all()}


def _stored_sync() -> dict[str, Any]:
    with get_sync_session() as db:
        rows = db.execute(select(RuntimeSetting.key, RuntimeSetting.value_json))
        return {key: value for key, value in rows.all()}


async def current() -> Levers:
    stored = _fresh()
    if stored is None:
        try:
            stored = await _stored()
        except (SQLAlchemyError, OSError):
            logger.warning("Runtime settings unreadable, using the last known values")
            stored = _stale()
        _remember(stored)
    return resolve(stored)


def current_sync() -> Levers:
    stored = _fresh()
    if stored is None:
        try:
            stored = _stored_sync()
        except (SQLAlchemyError, OSError):
            logger.warning("Runtime settings unreadable, using the last known values")
            stored = _stale()
        _remember(stored)
    return resolve(stored)


# --- checks for the public API -------------------------------------------------------------------


def require_runs_open(levers: Levers) -> None:
    """503 while maintenance mode holds new runs."""
    if levers.maintenance:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=levers.notice())


def disabled_in(model_ids: list[str], levers: Levers) -> list[str]:
    off = set(levers.disabled_models)
    return sorted({model_id for model_id in model_ids if model_id in off})


def require_models_enabled(model_ids: list[str], levers: Levers) -> None:
    """400 naming the models that are turned off."""
    off = disabled_in(model_ids, levers)
    if off:
        names = ", ".join(off)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{names} {'is' if len(off) == 1 else 'are'} turned off for now: "
            "pick another model",
        )
