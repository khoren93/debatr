"""Levers and alerts of the admin console (permission `system`).

- `GET /settings`: every lever with its value, env default and who changed it last, plus
  OpenRouter's catalogue (the wizard's `ModelInfo`, so the console uses the wizard's model
  picker) for the model levers.
- `PUT /settings/{key}` / `POST /settings/{key}/reset`: sudo and a reason; the
  `runtime_settings` row and the audit entry are written in one transaction, and every process
  sees the change within `runtime_settings.CACHE_SECONDS`.
- `GET /alerts`, `POST /alerts/test`: whether Telegram is set up, the recent alerts, a test
  message. Which alerts go out is the `muted_alerts` lever (its catalogue comes with
  `GET /settings`); a change of it is itself an alert that cannot be muted.
"""

from typing import Any, get_args

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.access import AdminContext, read_only_db, require_admin, require_sudo
from app.core.db import get_db
from app.models.models import RuntimeSetting, utcnow
from app.schemas.admin import (
    AlertEventOut,
    AlertsOut,
    AlertTestOut,
    LeverChangeRequest,
    LeverKind,
    LeverOut,
    ReasonRequest,
    SettingsOut,
)
from app.schemas.schemas import ModelInfo, ModelPricing
from app.services import alerts, runtime_settings
from app.services.admin import audit
from app.services.alert_events import EVENTS
from app.services.openrouter_client import openrouter_client
from app.services.runtime_settings import LEVER_KEYS, Levers

router = APIRouter()
manage_system = require_admin("system")

KINDS: dict[str, LeverKind] = {
    "registration_open": "bool",
    "maintenance": "bool",
    "maintenance_message": "text",
    "disabled_models": "models",
    "signup_bonus_usd": "float",
    "free_models_per_minute": "int",
    "max_active_debates_per_user": "int",
    "max_active_media_per_user": "int",
    "muted_alerts": "alerts",
    "free_verdict_model": "model",
    "free_debates_per_day": "int",
    "free_max_rounds": "int",
    "free_max_debaters": "int",
    "free_lengths": "lengths",
    "credit_markup": "factor",
    "min_debate_charge_usd": "float",
    "tts_price_per_1k_chars": "float",
    "music_price_per_min": "float",
    "ai_covers": "choice",
    "trending_daily_topics": "int",
    "trending_shown_topics": "int",
    "topic_model": "model",
    "topic_review_model": "model",
}


def bounds(key: str) -> tuple[float | None, float | None]:
    """The lever's ge / le limits (from the Levers model)."""
    low: float | None = None
    high: float | None = None
    for item in Levers.model_fields[key].metadata:
        low = getattr(item, "ge", low)
        high = getattr(item, "le", high)
    return low, high


def choices(key: str) -> list[str] | None:
    """The values of a "choice" lever (its Literal type)."""
    if KINDS[key] != "choice":
        return None
    return [str(v) for v in get_args(Levers.model_fields[key].annotation)]


def levers_out(rows: dict[str, RuntimeSetting]) -> list[LeverOut]:
    current = runtime_settings.resolve({key: row.value_json for key, row in rows.items()})
    defaults = runtime_settings.defaults()
    out: list[LeverOut] = []
    for key in LEVER_KEYS:
        row = rows.get(key)
        low, high = bounds(key)
        out.append(
            LeverOut(
                key=key,
                kind=KINDS[key],
                value=getattr(current, key),
                default=defaults[key],
                overridden=row is not None,
                minimum=low,
                maximum=high,
                choices=choices(key),
                updated_at=row.updated_at if row else None,
                updated_by=row.updated_by if row else None,
            )
        )
    return out


async def _rows(db: AsyncSession) -> dict[str, RuntimeSetting]:
    found = (await db.scalars(select(RuntimeSetting))).all()
    return {row.key: row for row in found if row.key in LEVER_KEYS}


async def _settings_out(db: AsyncSession) -> SettingsOut:
    rows = await _rows(db)
    catalogue: dict[str, ModelInfo] = {}
    for model in await openrouter_client.get_models():
        try:
            info = ModelInfo.model_validate(model)
        except ValidationError:  # an odd catalogue entry must not take the page down
            continue
        catalogue[info.id] = info
    current = runtime_settings.resolve({key: row.value_json for key, row in rows.items()})
    # Models a lever names that left the catalogue (still turned off, still in use).
    named = [*current.disabled_models, current.free_verdict_model]
    named += [current.topic_model, current.topic_review_model]
    for model_id in filter(None, named):
        catalogue.setdefault(
            model_id,
            ModelInfo(
                id=model_id,
                name=model_id,
                context_length=0,
                pricing=ModelPricing(prompt="0", completion="0"),
                is_free=model_id.endswith(":free"),
            ),
        )
    return SettingsOut(
        levers=levers_out(rows),
        models=sorted(catalogue.values(), key=lambda m: m.id),
        alert_events=[
            AlertEventOut(kind=e.kind, group=e.group, label=e.label, hint=e.hint, at_once=e.at_once)
            for e in EVENTS
        ],
        cache_seconds=runtime_settings.CACHE_SECONDS,
    )


def _known(key: str) -> None:
    if key not in LEVER_KEYS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such setting")


async def _effective(db: AsyncSession, key: str) -> Any:
    rows = await _rows(db)
    current = runtime_settings.resolve({k: row.value_json for k, row in rows.items()})
    return getattr(current, key)


def _tell_mutes(key: str, actor: str, before: Any, after: Any) -> None:
    """Muting alerts goes to the chat itself (after the commit, so it names what holds)."""
    if key == "muted_alerts" and before != after:
        alerts.notify_soon(alerts.mutes_changed_alert(actor, list(before), list(after)))


@router.get("/settings", response_model=SettingsOut)
async def get_settings(
    _ctx: AdminContext = Depends(manage_system),
    db: AsyncSession = Depends(read_only_db),
) -> SettingsOut:
    return await _settings_out(db)


@router.put("/settings/{key}", response_model=SettingsOut)
async def change_setting(
    key: str,
    body: LeverChangeRequest,
    request: Request,
    ctx: AdminContext = Depends(manage_system),
    _sudo: AdminContext = Depends(require_sudo),
    db: AsyncSession = Depends(get_db),
) -> SettingsOut:
    _known(key)
    try:
        value = runtime_settings.validate_value(key, body.value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    before = await _effective(db, key)
    row = await db.get(RuntimeSetting, key, with_for_update=True)
    if row is None:
        db.add(
            RuntimeSetting(
                key=key, value_json=value, updated_at=utcnow(), updated_by=ctx.user.email
            )
        )
    else:
        row.value_json = value
        row.updated_at = utcnow()
        row.updated_by = ctx.user.email
    await audit.record(
        db,
        "settings.changed",
        request=request,
        actor=ctx.user,
        target_type="setting",
        target_id=key,
        reason=body.reason,
        before={key: before},
        after={key: value},
        commit=False,
    )
    await db.commit()
    runtime_settings.invalidate()
    _tell_mutes(key, ctx.user.email, before, value)
    return await _settings_out(db)


@router.post("/settings/{key}/reset", response_model=SettingsOut)
async def reset_setting(
    key: str,
    body: ReasonRequest,
    request: Request,
    ctx: AdminContext = Depends(manage_system),
    _sudo: AdminContext = Depends(require_sudo),
    db: AsyncSession = Depends(get_db),
) -> SettingsOut:
    """Back to the env setting (the row goes)."""
    _known(key)
    row = await db.get(RuntimeSetting, key, with_for_update=True)
    if row is None:
        raise HTTPException(status_code=409, detail="This setting already follows the env value")
    before = await _effective(db, key)
    await db.delete(row)
    await audit.record(
        db,
        "settings.reset",
        request=request,
        actor=ctx.user,
        target_type="setting",
        target_id=key,
        reason=body.reason,
        before={key: before},
        after={key: runtime_settings.defaults()[key]},
        commit=False,
    )
    await db.commit()
    runtime_settings.invalidate()
    _tell_mutes(key, ctx.user.email, before, runtime_settings.defaults()[key])
    return await _settings_out(db)


@router.get("/alerts", response_model=AlertsOut)
async def get_alerts(_ctx: AdminContext = Depends(manage_system)) -> AlertsOut:
    return AlertsOut.model_validate(
        {
            "configured": alerts.configured(),
            "check_every_seconds": alerts.CHECK_SECONDS,
            "recent": await alerts.recent(),
        }
    )


@router.post("/alerts/test", response_model=AlertTestOut)
async def test_alert(
    request: Request,
    ctx: AdminContext = Depends(manage_system),
    db: AsyncSession = Depends(get_db),
) -> AlertTestOut:
    """A test message to the alerts chat (recorded like any alert)."""
    alert = alerts.Alert(
        kind="test",
        title="Test alert from the admin console",
        detail=f"sent by {ctx.user.email}",
        severity="info",
        path="/admin/settings",
    )
    error = await alerts.deliver(alert)
    await audit.record(
        db,
        "alerts.tested",
        request=request,
        actor=ctx.user,
        after={"sent": error is None, "error": error},
        ok=error is None,
    )
    return AlertTestOut(sent=error is None, error=error)
