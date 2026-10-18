"""The System page of the admin console (`/api/admin/system/*`, permission `system`): queues,
workers and the scheduler; runs in flight with "recover now"; limits; providers; health.

Reads use a read-only transaction; RQ and the file system are read in a thread pool. Changes
(requeue or delete a failed job, recover a run, delete orphan media folders) name a reason and
are audited; deleting folders also needs sudo and checks every folder again on the server.
"""

import contextlib
import json
import logging
import time
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.admin.access import AdminContext, read_only_db, require_admin, sudo_required
from app.core.config import settings
from app.core.db import get_db
from app.core.redis import get_async_redis, get_sync_redis
from app.models.models import utcnow
from app.schemas.admin import (
    ActionOut,
    HealthOut,
    LimitsOut,
    OrphansDeleteOut,
    OrphansDeleteRequest,
    ProvidersOut,
    QueuesOut,
    ReasonRequest,
    RecoverRequest,
    RunsOut,
)
from app.services.admin import audit, system
from app.services.media.tts.elevenlabs import system_key_status, system_quota
from app.services.openrouter_client import openrouter_client

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/system")

ACCOUNT_KEY = "admin:openrouter_account"
ACCOUNT_SECONDS = 300

can_see = require_admin("system")


async def _record(
    db: AsyncSession,
    ctx: AdminContext,
    request: Request,
    action: str,
    target_type: str,
    target_id: str | None,
    reason: str,
    **details: object,
) -> None:
    await audit.record(
        db,
        action,
        request=request,
        actor=ctx.user,
        target_type=target_type,
        target_id=target_id,
        reason=reason,
        after=dict(details) or None,
    )


async def _openrouter_account(refresh: bool = False) -> dict[str, object]:
    """The system key's account, cached a few minutes (the page polls)."""
    redis = get_async_redis()
    if not refresh:
        with contextlib.suppress(RedisError, ValueError):
            cached = await redis.get(ACCOUNT_KEY)
            if cached:
                return json.loads(cached)
    account = await openrouter_client.account()
    with contextlib.suppress(RedisError):
        await redis.set(ACCOUNT_KEY, json.dumps(account), ex=ACCOUNT_SECONDS)
    return account


# --- queues, workers, scheduler -----------------------------------------------------------------


@router.get("/queues", response_model=QueuesOut)
async def queues(_ctx: AdminContext = Depends(can_see)) -> QueuesOut:
    try:
        data = await run_in_threadpool(system.queues_sync, get_sync_redis())
    except RedisError as exc:
        raise HTTPException(status_code=503, detail=f"Redis is unavailable: {exc}") from None
    return QueuesOut.model_validate(data)


async def _job_action(
    job_id: str,
    action: str,
    body: ReasonRequest,
    request: Request,
    ctx: AdminContext,
    db: AsyncSession,
) -> ActionOut:
    try:
        job = await run_in_threadpool(
            system.failed_job_action_sync, get_sync_redis(), job_id, action
        )
    except LookupError:
        raise HTTPException(status_code=404, detail="No such failed job") from None
    await _record(
        db,
        ctx,
        request,
        f"job.{'requeued' if action == 'requeue' else 'deleted'}",
        "job",
        job_id,
        body.reason,
        func=job["func"],
        queue=job["queue"],
        debate_id=job["debate_id"],
    )
    message = "Queued again" if action == "requeue" else "Deleted"
    return ActionOut(status=action, message=f"{message}: {job['func']}")


@router.post("/jobs/{job_id}/requeue", response_model=ActionOut)
async def requeue_job(
    job_id: str,
    body: ReasonRequest,
    request: Request,
    ctx: AdminContext = Depends(can_see),
    db: AsyncSession = Depends(get_db),
) -> ActionOut:
    return await _job_action(job_id, "requeue", body, request, ctx, db)


@router.post("/jobs/{job_id}/delete", response_model=ActionOut)
async def delete_job(
    job_id: str,
    body: ReasonRequest,
    request: Request,
    ctx: AdminContext = Depends(can_see),
    db: AsyncSession = Depends(get_db),
) -> ActionOut:
    return await _job_action(job_id, "delete", body, request, ctx, db)


# --- runs in flight -------------------------------------------------------------------------------


@router.get("/runs", response_model=RunsOut)
async def runs(
    _ctx: AdminContext = Depends(can_see), db: AsyncSession = Depends(read_only_db)
) -> RunsOut:
    found = await system.runs(db, get_sync_redis(), get_async_redis(), utcnow())
    return RunsOut.model_validate({"runs": found})


@router.post("/runs/{debate_id}/recover", response_model=ActionOut)
async def recover(
    debate_id: str,
    body: RecoverRequest,
    request: Request,
    ctx: AdminContext = Depends(can_see),
    db: AsyncSession = Depends(get_db),
) -> ActionOut:
    """Queue a run whose worker is gone again now (the watchdog would after two checks)."""
    try:
        uuid.UUID(debate_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="No such debate") from None
    # The recovery module pulls in the worker's orchestrator: imported only when needed.
    from app.services.recovery import recover_now

    try:
        status = await run_in_threadpool(recover_now, debate_id, body.kind)
    except LookupError:
        raise HTTPException(status_code=404, detail="No such debate") from None
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    await _record(
        db,
        ctx,
        request,
        "run.recovered",
        "debate",
        debate_id,
        body.reason,
        kind=body.kind,
        now=status,
    )
    return ActionOut(status=status, message=f"The {body.kind} run is {status} again")


# --- limits and providers -------------------------------------------------------------------------


@router.get("/limits", response_model=LimitsOut)
async def limits(
    _ctx: AdminContext = Depends(can_see), db: AsyncSession = Depends(read_only_db)
) -> LimitsOut:
    account = await _openrouter_account()
    total = account.get("total_credits")
    data = await system.limits(
        db, get_async_redis(), utcnow(), float(total) if isinstance(total, int | float) else None
    )
    return LimitsOut.model_validate(data)


@router.get("/providers", response_model=ProvidersOut)
async def providers(refresh: bool = False, _ctx: AdminContext = Depends(can_see)) -> ProvidersOut:
    account = await _openrouter_account(refresh)
    total, used = account.get("total_credits"), account.get("total_usage")
    if isinstance(total, int | float) and isinstance(used, int | float):
        account = {**account, "balance": round(total - used, 6)}
    elevenlabs: dict[str, object] = {"configured": bool(settings.ELEVENLABS_API_KEY)}
    if settings.ELEVENLABS_API_KEY:
        ok, reason = await run_in_threadpool(system_key_status, force=refresh)
        elevenlabs.update({"ok": ok, "reason": reason})
        quota = await run_in_threadpool(system_quota) if ok else None
        if quota:
            elevenlabs.update(quota)
    payments = {
        "mode": settings.payments_mode,
        "currency": settings.STRIPE_CURRENCY,
        "topup_amounts": settings.topup_amounts,
        "signup_bonus_usd": settings.SIGNUP_BONUS_USD,
        "credit_markup": settings.CREDIT_MARKUP,
        "tts_price_per_1k_chars": settings.TTS_CREDIT_PRICE_PER_1K_CHARS,
    }
    return ProvidersOut(
        checked_at=datetime.now(UTC),
        openrouter=account,
        elevenlabs=elevenlabs,
        payments=payments,
    )


# --- health ---------------------------------------------------------------------------------------


@router.get("/health", response_model=HealthOut)
async def health(
    refresh: bool = False,
    _ctx: AdminContext = Depends(can_see),
    db: AsyncSession = Depends(read_only_db),
) -> HealthOut:
    redis = get_async_redis()
    now = utcnow()
    return HealthOut.model_validate(
        {
            "version": settings.APP_VERSION,
            "environment": settings.ENVIRONMENT,
            "alembic_current": await system.alembic_current(db),
            "alembic_head": await run_in_threadpool(system.alembic_head),
            "database": await system.database_health(db),
            "redis": await system.redis_health(redis),
            "media": await system.media_health(db, redis, refresh=refresh, now=now),
            "backup": await system.last_backup(redis),
            "config": system.config_flags(),
        }
    )


@router.post("/media/orphans/delete", response_model=OrphansDeleteOut)
async def delete_orphans(
    body: OrphansDeleteRequest,
    request: Request,
    ctx: AdminContext = Depends(can_see),
    db: AsyncSession = Depends(get_db),
) -> OrphansDeleteOut:
    """Delete the listed media folders of debates that no longer exist (sudo). Every name is
    checked again here: a folder whose debate exists, or that changed within the hour, stays."""
    if not ctx.session.is_sudo(time.time()):
        raise sudo_required()
    root = settings.media_root_path
    folders, _disk = await run_in_threadpool(system.scan_media_sync, root)
    existing = await system.existing_debates(db, (f.name for f in folders))
    allowed = {f.name for f in system.orphans(folders, set(existing), time.time())}
    names = list(dict.fromkeys(body.names))
    chosen = [n for n in names if n in allowed]
    skipped = [n for n in names if n not in allowed]
    freed = await run_in_threadpool(system.delete_folders_sync, root, chosen)
    with contextlib.suppress(RedisError):
        await get_async_redis().delete(system.MEDIA_CACHE_KEY)
    await _record(
        db,
        ctx,
        request,
        "media.orphans_deleted",
        "media",
        None,
        body.reason,
        deleted=len(chosen),
        bytes=freed,
        names=chosen[:100],
        skipped=skipped[:100],
    )
    logger.info(
        "Admin %s deleted %d orphan media folders (%d bytes)", ctx.user.email, len(chosen), freed
    )
    return OrphansDeleteOut(deleted=len(chosen), bytes=freed, skipped=skipped)
