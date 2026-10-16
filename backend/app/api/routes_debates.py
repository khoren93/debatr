"""Debates: estimate, create (or save a draft), start, list, detail, stop, delete, publish.

Every debate belongs to the signed-in user who created it. Public debates (gallery /
share link) and ownerless legacy rows are readable by anyone; only owners and the admin
session can change them.
"""

import contextlib
import logging
import shutil
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette.concurrency import run_in_threadpool

from app.api.serializers import can_manage, can_view, detail_out, share_url, summary_out
from app.core.auth import get_current_user, require_user
from app.core.config import settings
from app.core.db import get_db
from app.core.ids import new_slug
from app.core.ratelimit import enforce_debate_create_limit
from app.core.redis import get_async_redis, provider_key_key, stop_flag_key, tts_key_key
from app.core.security import decrypt_secret
from app.models.models import Debate, DebateParticipant, User, utcnow
from app.schemas.schemas import (
    DebateConfig,
    DebateDetail,
    DebateResponse,
    DebateSummary,
    EstimateOut,
    PublishOut,
    PublishRequest,
    RenderReport,
    RendersOut,
    StartDebateRequest,
    StopDebateResponse,
)
from app.services.engagement import engagement_out
from app.services.estimate import Pricing, estimate_debate, pricing_from_models
from app.services.media.paths import MediaPaths
from app.services.media.tts.elevenlabs import system_key_status
from app.services.openrouter_client import openrouter_client
from app.services.queue_manager import enqueue_debate_start
from app.services.views import count_view

logger = logging.getLogger(__name__)
router = APIRouter()

ACTIVE_STATUSES = ("queued", "running")


def _parse_uuid(debate_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(debate_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="Invalid debate id") from e


async def load_debate(db: AsyncSession, debate_id: str, *, full: bool = False) -> Debate:
    options = [selectinload(Debate.participants), selectinload(Debate.user)]
    if full:
        options.append(selectinload(Debate.turns))
    stmt = select(Debate).options(*options).where(Debate.id == _parse_uuid(debate_id))
    debate = (await db.execute(stmt)).scalar_one_or_none()
    if debate is None:
        raise HTTPException(status_code=404, detail="Debate not found")
    return debate


def _require_manage(debate: Debate, user: User | None, request: Request) -> None:
    if not can_manage(debate, user, request):
        raise HTTPException(status_code=403, detail="You do not own this debate")


def _resolve_provider_key(user: User | None, request_key: str | None) -> tuple[str | None, bool]:
    """(key, own_key): a key sent with the request wins, then the account's saved key."""
    if request_key and request_key.strip():
        return request_key.strip(), True
    if user is not None and user.openrouter_key_enc:
        key = decrypt_secret(user.openrouter_key_enc)
        if key:
            return key, True
        logger.warning("Stored OpenRouter key of %s cannot be decrypted", user.email)
    return None, False


def _tts_key(config: DebateConfig, request_key: str | None) -> str | None:
    """The user's ElevenLabs key, kept only when the auto audio build will use it."""
    plan = config.media_plan
    if plan is None or plan.provider != "elevenlabs" or "audio" not in plan.outputs:
        return None
    return request_key.strip() if request_key and request_key.strip() else None


async def _effective_tts_provider(config: DebateConfig, own_tts_key: bool) -> str | None:
    plan = config.media_plan
    if plan is None or "audio" not in plan.outputs:
        return None
    if plan.provider == "elevenlabs" and not own_tts_key:
        ok, _reason = await run_in_threadpool(system_key_status)
        if not ok:
            return "edge"
    return plan.provider


def _paid_models(config: DebateConfig, pricing: Pricing) -> list[str]:
    paid: set[str] = set()
    for p in config.participants:
        prompt_price, completion_price = pricing.get(p.model_id, (0.0, 0.0))
        if prompt_price > 0 or completion_price > 0:
            paid.add(p.model_id)
    return sorted(paid)


async def _estimate(
    config: DebateConfig, user: User | None, own_key: bool, own_tts_key: bool = False
) -> EstimateOut:
    pricing = pricing_from_models(await openrouter_client.get_models())
    est = estimate_debate(
        config.persisted(),
        pricing,
        own_key=own_key,
        tts_provider=await _effective_tts_provider(config, own_tts_key),
        own_tts_key=own_tts_key,
        tts_price_per_1k=settings.TTS_CREDIT_PRICE_PER_1K_CHARS,
        markup=settings.CREDIT_MARKUP,
        default_model=settings.DEFAULT_MODEL_ID,
    )
    out = EstimateOut(
        **est.as_dict(),
        own_key=own_key,
        own_tts_key=own_tts_key,
        paid_models=_paid_models(config, pricing),
    )
    if user is not None:
        before = float(user.credits_usd or 0)
        out.credits_before = before
        out.credits_after = round(before - out.credits_cost_usd, 6)
        out.sufficient = out.credits_cost_usd <= 0 or before >= out.credits_cost_usd
    else:
        out.sufficient = out.credits_cost_usd <= 0
    return out


def _require_sufficient(est: EstimateOut) -> None:
    if est.sufficient:
        return
    raise HTTPException(
        status_code=status.HTTP_402_PAYMENT_REQUIRED,
        detail=(
            f"Insufficient credits: this run needs about ${est.credits_cost_usd:.2f} and you "
            f"have ${est.credits_before or 0:.2f}. Top up or use your own OpenRouter key."
        ),
    )


def _apply_config(debate: Debate, config: DebateConfig, own_key: bool) -> None:
    debate.title = config.topic.strip()
    debate.config_json = {**config.persisted(), "billing": {"own_key": own_key}}
    debate.participants = [
        DebateParticipant(
            role=p.role,
            model_id=p.model_id,
            persona_name=p.display_name,
            voice_name=p.voice_name,
            avatar_url=p.avatar_url,
        )
        for p in config.participants
    ]


async def _enqueue(
    db: AsyncSession, debate: Debate, provider_key: str | None, tts_key: str | None = None
) -> None:
    """Queue the run. User keys go to Redis with a TTL, never to Postgres."""
    debate_id = str(debate.id)
    try:
        redis = get_async_redis()
        if provider_key:
            await redis.set(provider_key_key(debate_id), provider_key, ex=settings.PROVIDER_KEY_TTL)
        if tts_key:
            await redis.set(tts_key_key(debate_id), tts_key, ex=settings.PROVIDER_KEY_TTL)
        else:
            await redis.delete(tts_key_key(debate_id))
        await run_in_threadpool(enqueue_debate_start, debate_id)
    except RedisError:
        logger.exception("Failed to enqueue debate %s", debate_id)
        debate.status = "error"
        debate.error_message = "Job queue unavailable"
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Job queue is unavailable, please try again later",
        ) from None


# --- routes --------------------------------------------------------------


@router.post("/estimate", response_model=EstimateOut)
async def estimate(
    config: DebateConfig, user: User | None = Depends(get_current_user)
) -> EstimateOut:
    """Cost, length and credit impact of a configuration before running it."""
    _key, own_key = _resolve_provider_key(user, config.user_provider_key)
    own_tts_key = _tts_key(config, config.user_tts_key) is not None
    return await _estimate(config, user, own_key, own_tts_key)


@router.get("", response_model=list[DebateSummary])
async def list_debates(
    status_filter: str | None = Query(None, alias="status", max_length=20),
    q: str | None = Query(None, max_length=200),
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> list[DebateSummary]:
    """The signed-in user's debates, newest first."""
    conditions: list[Any] = [Debate.user_id == user.id]
    if status_filter:
        conditions.append(Debate.status == status_filter)
    if q and q.strip():
        conditions.append(Debate.title.ilike(f"%{q.strip()}%"))
    stmt = (
        select(Debate)
        .options(selectinload(Debate.participants))
        .where(*conditions)
        .order_by(Debate.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    debates = (await db.execute(stmt)).scalars().all()
    return [summary_out(d) for d in debates]


@router.post(
    "",
    response_model=DebateResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(enforce_debate_create_limit)],
)
async def create_debate(
    config: DebateConfig,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> DebateResponse:
    """Create a debate and queue it, or save it as a draft when `draft` is true."""
    provider_key, own_key = _resolve_provider_key(user, config.user_provider_key)
    tts_key = _tts_key(config, config.user_tts_key)
    if not config.draft:
        _require_sufficient(await _estimate(config, user, own_key, tts_key is not None))

    debate = Debate(user_id=user.id, status="draft" if config.draft else "queued")
    _apply_config(debate, config, own_key)
    db.add(debate)
    await db.commit()
    debate_id = str(debate.id)
    if config.draft:
        return DebateResponse(debate_id=debate_id, status="draft", message="Draft saved")
    await _enqueue(db, debate, provider_key, tts_key)
    return DebateResponse(debate_id=debate_id, status="queued", message="Debate created and queued")


@router.patch("/{debate_id}", response_model=DebateResponse)
async def update_draft(
    debate_id: str,
    config: DebateConfig,
    request: Request,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> DebateResponse:
    """Replace the configuration of a draft."""
    debate = await load_debate(db, debate_id)
    _require_manage(debate, user, request)
    if debate.status != "draft":
        raise HTTPException(status_code=409, detail="Only drafts can be edited")
    _key, own_key = _resolve_provider_key(user, config.user_provider_key)
    _apply_config(debate, config, own_key)
    await db.commit()
    return DebateResponse(debate_id=debate_id, status="draft", message="Draft updated")


@router.post("/{debate_id}/start", response_model=DebateResponse)
async def start_draft(
    debate_id: str,
    request: Request,
    body: StartDebateRequest | None = None,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> DebateResponse:
    """Queue a draft."""
    debate = await load_debate(db, debate_id)
    _require_manage(debate, user, request)
    if debate.status != "draft":
        raise HTTPException(status_code=409, detail=f"Debate is already {debate.status}")
    stored = dict(debate.config_json or {})
    stored.pop("billing", None)
    config = DebateConfig.model_validate(stored)
    provider_key, own_key = _resolve_provider_key(user, body.user_provider_key if body else None)
    tts_key = _tts_key(config, body.user_tts_key if body else None)
    _require_sufficient(await _estimate(config, user, own_key, tts_key is not None))
    debate.config_json = {**config.persisted(), "billing": {"own_key": own_key}}
    debate.status = "queued"
    debate.error_message = None
    await db.commit()
    await _enqueue(db, debate, provider_key, tts_key)
    return DebateResponse(debate_id=debate_id, status="queued", message="Debate queued")


@router.get("/{debate_id}", response_model=DebateDetail)
async def get_debate(
    debate_id: str,
    request: Request,
    viewer: User | None = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DebateDetail:
    """Debate details including participants and all turns."""
    debate = await load_debate(db, debate_id, full=True)
    if not can_view(debate, viewer, request):
        raise HTTPException(status_code=403, detail="This debate is private")
    await count_view(db, debate, viewer, request)
    return detail_out(debate, viewer, await engagement_out(db, debate, viewer))


@router.post("/{debate_id}/stop", response_model=StopDebateResponse)
async def stop_debate(
    debate_id: str,
    request: Request,
    user: User | None = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StopDebateResponse:
    """Stop a queued or running debate. The current turn finishes early."""
    debate = await load_debate(db, debate_id)
    _require_manage(debate, user, request)
    if debate.status not in ACTIVE_STATUSES:
        raise HTTPException(status_code=409, detail=f"Debate is already {debate.status}")

    debate.status = "stopped"
    debate.ended_at = utcnow()
    await db.commit()

    try:
        await get_async_redis().set(stop_flag_key(debate_id), "1", ex=3600)
    except RedisError:
        logger.warning("Could not set stop flag for %s; worker will stop at next turn", debate_id)
    from app.services.events import publish_event_async

    await publish_event_async(
        debate_id, "debate_stopped", {"debate_id": debate_id, "status": "stopped"}
    )
    return StopDebateResponse(debate_id=debate_id, status="stopped")


@router.delete("/{debate_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_debate(
    debate_id: str,
    request: Request,
    user: User | None = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a debate, its turns and generated media."""
    debate = await load_debate(db, debate_id)
    _require_manage(debate, user, request)
    if debate.status in ACTIVE_STATUSES:
        # Make sure the worker stops touching it.
        with contextlib.suppress(RedisError):
            await get_async_redis().set(stop_flag_key(debate_id), "1", ex=3600)
    await db.delete(debate)
    await db.commit()
    await run_in_threadpool(shutil.rmtree, MediaPaths(debate_id).dir, True)


@router.post("/{debate_id}/publish", response_model=PublishOut)
async def publish_debate(
    debate_id: str,
    body: PublishRequest,
    request: Request,
    user: User | None = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PublishOut:
    """Make a finished debate public (gallery + share link)."""
    debate = await load_debate(db, debate_id)
    _require_manage(debate, user, request)
    if debate.status != "completed":
        raise HTTPException(status_code=409, detail="Only completed debates can be published")
    if not debate.slug:
        for _ in range(5):
            candidate = new_slug()
            taken = await db.scalar(select(Debate.id).where(Debate.slug == candidate))
            if taken is None:
                debate.slug = candidate
                break
        if not debate.slug:
            raise HTTPException(status_code=500, detail="Could not allocate a share link")
    debate.is_public = True
    debate.category = body.category or debate.category
    debate.published_at = debate.published_at or utcnow()
    await db.commit()
    return PublishOut(is_public=True, slug=debate.slug, share_url=share_url(debate))


@router.delete("/{debate_id}/publish", response_model=PublishOut)
async def unpublish_debate(
    debate_id: str,
    request: Request,
    user: User | None = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PublishOut:
    debate = await load_debate(db, debate_id)
    _require_manage(debate, user, request)
    debate.is_public = False
    await db.commit()
    return PublishOut(is_public=False, slug=debate.slug, share_url=None)


@router.post("/{debate_id}/renders", response_model=RendersOut)
async def report_render(
    debate_id: str,
    body: RenderReport,
    request: Request,
    user: User | None = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RendersOut:
    """The browser reports a finished MP4 render (used for the usage stats)."""
    debate = await load_debate(db, debate_id)
    _require_manage(debate, user, request)
    state = dict(debate.media_json or {})
    renders = dict(state.get("renders") or {})
    renders[body.kind] = int(renders.get(body.kind) or 0) + 1
    debate.media_json = {**state, "renders": renders}
    await db.commit()
    return RendersOut(renders={k: int(v) for k, v in renders.items()})
