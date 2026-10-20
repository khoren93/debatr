"""AI covers of a finished debate (services/media/cover.py), for its owner.

- POST   /api/debates/{id}/cover              draw a new version (optional own hook)
- PUT    /api/debates/{id}/cover              show another version (null: the markup cover)
- DELETE /api/debates/{id}/cover/{version}    remove a version and its files
The state comes with the debate (`DebateDetail.cover`). A cover runs on the account's (or the
request's) OpenRouter key when there is one, else it is paid from the balance once it is ready;
API tokens with a spending limit can only use an own key.
"""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette.concurrency import run_in_threadpool

from app.api.routes_debates import resolve_provider_key
from app.api.serializers import can_manage, cover_out, cover_policy
from app.core.auth import request_api_token, require_user
from app.core.config import settings
from app.core.db import get_db
from app.core.redis import get_async_redis, provider_key_key
from app.models.models import Debate, User
from app.schemas.schemas import CoverOut, CoverRequest, CoverSelect
from app.services import runtime_settings
from app.services.credits import cover_charge_usd, lever_prices
from app.services.fair_share import require_cover_slot
from app.services.media import cover as covers
from app.services.media.paths import MediaPaths
from app.services.queue_manager import enqueue_cover_build

logger = logging.getLogger(__name__)
router = APIRouter()


async def _owned(db: AsyncSession, debate_id: str, user: User) -> Debate:
    try:
        key = uuid.UUID(debate_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="Invalid debate id") from e
    stmt = select(Debate).options(selectinload(Debate.user)).where(Debate.id == key)
    debate = (await db.execute(stmt)).scalar_one_or_none()
    if debate is None:
        raise HTTPException(status_code=404, detail="Debate not found")
    if not can_manage(debate, user):
        raise HTTPException(status_code=403, detail="You do not own this debate")
    return debate


async def _out(debate: Debate, user: User) -> CoverOut:
    return cover_out(debate, await cover_policy(debate, user))


@router.post("/{debate_id}/cover", response_model=CoverOut, status_code=status.HTTP_202_ACCEPTED)
async def generate_cover(
    debate_id: str,
    body: CoverRequest,
    request: Request,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> CoverOut:
    """Queue a new cover version (the art director picks the hook unless `hook` is sent)."""
    debate = await _owned(db, debate_id, user)
    levers = await runtime_settings.current()
    if levers.ai_covers == "off":
        raise HTTPException(status_code=403, detail="AI covers are turned off")
    runtime_settings.require_runs_open(levers)
    if debate.status not in ("completed", "stopped"):
        raise HTTPException(status_code=409, detail="The debate has not finished yet")
    if debate.cover_status in covers.ACTIVE:
        raise HTTPException(status_code=409, detail="A cover is already being drawn")
    hook = (body.hook or "").strip() or None
    if hook and not covers.fit_hook(hook):
        raise HTTPException(status_code=400, detail="The hook needs at least one word")
    provider_key, own_key = resolve_provider_key(user, body.user_provider_key)
    token = request_api_token(request)
    if not own_key and token is not None and token.spend_limit_usd is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="API tokens with a spending limit cannot buy AI covers: use your own "
            "OpenRouter key or the website.",
        )
    prices = lever_prices(levers)
    price = float(cover_charge_usd(settings.COVER_PRICE_USD, prices.markup))
    if not own_key and float(user.credits_usd or 0) < price:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=f"An AI cover costs about ${price:.2f}: top up or add your own OpenRouter key.",
        )
    await require_cover_slot(db, user.id)
    debate.cover_json = covers.queued_state(
        debate.cover_json,
        source="owner",
        own_key=own_key,
        free=False,
        prices=prices.as_dict(),
        hook=hook,
    )
    debate.cover_status = "queued"
    await db.commit()
    try:
        if own_key and provider_key:
            await get_async_redis().set(
                provider_key_key(debate_id), provider_key, ex=settings.PROVIDER_KEY_TTL
            )
        await run_in_threadpool(enqueue_cover_build, debate_id)
    except RedisError:
        logger.exception("Failed to queue the cover of %s", debate_id)
        debate.cover_status = "error"
        debate.cover_json = {**(debate.cover_json or {}), "error": "Job queue unavailable"}
        await db.commit()
        raise HTTPException(
            status_code=503, detail="Job queue is unavailable, please try again later"
        ) from None
    return await _out(debate, user)


@router.put("/{debate_id}/cover", response_model=CoverOut)
async def select_cover(
    debate_id: str,
    body: CoverSelect,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> CoverOut:
    """Show another version everywhere (`version: null`: the markup cover)."""
    debate = await _owned(db, debate_id, user)
    try:
        debate.cover_json = covers.select_version(dict(debate.cover_json or {}), body.version)
    except KeyError:
        raise HTTPException(status_code=404, detail="No such cover version") from None
    await db.commit()
    return await _out(debate, user)


@router.delete("/{debate_id}/cover/{version_id}", response_model=CoverOut)
async def delete_cover(
    debate_id: str,
    version_id: str,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> CoverOut:
    """Remove a version and its files (the newest one left is shown when it was current)."""
    debate = await _owned(db, debate_id, user)
    try:
        state, removed = covers.remove_version(dict(debate.cover_json or {}), version_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="No such cover version") from None
    debate.cover_json = state
    await db.commit()
    await run_in_threadpool(covers.delete_files, MediaPaths(debate_id), removed)
    return await _out(debate, user)
