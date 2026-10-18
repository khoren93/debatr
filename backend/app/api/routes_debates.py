"""Debates: estimate, create (or save a draft), start, list, detail, stop, delete, publish.

Every debate belongs to the signed-in user who created it. Public debates (gallery /
share link) and ownerless legacy rows are readable by anyone; only owners and the admin
session can change them. Runs started with an API token (CLI, agents) remember the token, stay
private unless the request asks to publish them and must fit in the token's spending limit.
"""

import contextlib
import logging
import shutil
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette.concurrency import run_in_threadpool

from app.api.serializers import can_manage, can_view, detail_out, share_url, summary_out
from app.core.auth import get_current_user, request_api_token, require_user
from app.core.config import settings
from app.core.db import get_db
from app.core.ratelimit import enforce_debate_create_limit
from app.core.redis import get_async_redis, provider_key_key, stop_flag_key, tts_key_key
from app.core.security import decrypt_secret
from app.models.models import ApiToken, Debate, DebateParticipant, User
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
    ResumeEstimateOut,
    StartDebateRequest,
    StopDebateResponse,
)
from app.services import alerts, api_tokens, runtime_settings
from app.services.debate_control import ACTIVE_STATUSES
from app.services.debate_control import stop_debate as stop_debate_run
from app.services.engagement import engagement_out
from app.services.estimate import Pricing, estimate_debate, pricing_from_models
from app.services.fair_share import require_debate_slot
from app.services.media.paths import MediaPaths
from app.services.media.tts.elevenlabs import system_key_status
from app.services.moderation import publish_async
from app.services.openrouter_client import openrouter_client
from app.services.queue_manager import enqueue_debate_start
from app.services.resume import reset_for_resume, resume_point
from app.services.views import count_view

logger = logging.getLogger(__name__)
router = APIRouter()


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


def _require_manage(debate: Debate, user: User | None) -> None:
    if not can_manage(debate, user):
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
    config: DebateConfig,
    user: User | None,
    own_key: bool,
    own_tts_key: bool = False,
    budget: Decimal | None = None,
    from_turn: int = 0,
) -> EstimateOut:
    """`budget`: what the API token making the request may still spend (None = no limit);
    `from_turn`: a resumed run, which pays only the turns from there on."""
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
        fact_check_price=settings.FACT_CHECK_PRICE_USD,
        image_price=settings.MEDIA_IMAGE_PRICE_USD,
        max_images=settings.MEDIA_MAX_IMAGES,
        from_turn=from_turn,
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
    if budget is not None:
        out.token_budget_usd = float(budget)
        out.sufficient = out.sufficient and out.credits_cost_usd <= float(budget)
    return out


def _require_sufficient(est: EstimateOut) -> None:
    if est.sufficient:
        return
    if est.token_budget_usd is not None and est.credits_cost_usd > est.token_budget_usd:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=(
                f"API token spending limit reached: this run needs about "
                f"${est.credits_cost_usd:.2f} and the token may spend "
                f"${est.token_budget_usd:.2f} more. Raise its limit on the Account page or "
                "use free models."
            ),
        )
    raise HTTPException(
        status_code=status.HTTP_402_PAYMENT_REQUIRED,
        detail=(
            f"Insufficient credits: this run needs about ${est.credits_cost_usd:.2f} and you "
            f"have ${est.credits_before or 0:.2f}. Top up or use your own OpenRouter key."
        ),
    )


def _billing(own_key: bool, est: EstimateOut | None) -> dict[str, Any]:
    """`config_json.billing`. The estimate of a started run lets an API token's spending limit
    count runs that have not been charged yet (services.api_tokens.pending_estimate)."""
    billing: dict[str, Any] = {"own_key": own_key}
    if est is not None:
        media = (0.0 if est.own_tts_key else est.tts_cost_usd) + (
            est.images_cost_usd * settings.CREDIT_MARKUP
        )
        billing["estimate_usd"] = est.credits_cost_usd
        billing["media_estimate_usd"] = round(media, 6)
    return billing


async def _token_budget(db: AsyncSession, request: Request) -> Decimal | None:
    return await api_tokens.budget_left(db, request_api_token(request))


async def _require_runnable(config: DebateConfig, *, starting: bool = True) -> None:
    """Levers of the admin console: maintenance holds new runs (`starting`), turned-off models
    are refused (the estimate says so too, before the wizard's Start)."""
    levers = await runtime_settings.current()
    if starting:
        runtime_settings.require_runs_open(levers)
    runtime_settings.require_models_enabled([p.model_id for p in config.participants], levers)


def _apply_config(
    debate: Debate, config: DebateConfig, own_key: bool, est: EstimateOut | None = None
) -> None:
    debate.title = config.topic.strip()
    debate.config_json = {**config.persisted(), "billing": _billing(own_key, est)}
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
    db: AsyncSession,
    debate: Debate,
    provider_key: str | None,
    tts_key: str | None = None,
    from_seq: int = 0,
) -> None:
    """Queue the run (a resumed one from turn `from_seq`). User keys go to Redis with a TTL,
    never to Postgres."""
    debate_id = str(debate.id)
    try:
        redis = get_async_redis()
        if provider_key:
            await redis.set(provider_key_key(debate_id), provider_key, ex=settings.PROVIDER_KEY_TTL)
        if tts_key:
            await redis.set(tts_key_key(debate_id), tts_key, ex=settings.PROVIDER_KEY_TTL)
        else:
            await redis.delete(tts_key_key(debate_id))
        await run_in_threadpool(enqueue_debate_start, debate_id, from_seq)
    except RedisError:
        logger.exception("Failed to enqueue debate %s", debate_id)
        debate.status = "error"
        debate.error_message = "Job queue unavailable"
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Job queue is unavailable, please try again later",
        ) from None


def _announce(
    debate: Debate,
    config: DebateConfig,
    user: User,
    est: EstimateOut,
    own_key: bool,
    token: ApiToken | None,
    *,
    from_draft: bool = False,
) -> None:
    """The "new debate" alert (Telegram, unless muted in the console)."""
    start = alerts.DebateStart(
        debate_id=str(debate.id),
        topic=config.topic.strip(),
        owner=user.email,
        models=[p.model_id for p in config.participants if p.role == "debater"],
        rounds=config.num_rounds,
        cost_usd=est.credits_cost_usd,
        own_key=own_key,
        token=token.name if token is not None else None,
        from_draft=from_draft,
    )
    alerts.notify_soon(alerts.debate_alert(start))


# --- routes --------------------------------------------------------------


@router.post("/estimate", response_model=EstimateOut)
async def estimate(
    config: DebateConfig,
    request: Request,
    user: User | None = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EstimateOut:
    """Cost, length and credit impact of a configuration before running it."""
    await _require_runnable(config, starting=False)
    _key, own_key = _resolve_provider_key(user, config.user_provider_key)
    own_tts_key = _tts_key(config, config.user_tts_key) is not None
    return await _estimate(config, user, own_key, own_tts_key, await _token_budget(db, request))


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
    request: Request,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> DebateResponse:
    """Create a debate and queue it, or save it as a draft when `draft` is true."""
    token = request_api_token(request)
    if token is not None:
        config = api_tokens.with_token_defaults(config)
    provider_key, own_key = _resolve_provider_key(user, config.user_provider_key)
    tts_key = _tts_key(config, config.user_tts_key)
    est: EstimateOut | None = None
    if not config.draft:
        await _require_runnable(config)
        est = await _estimate(
            config, user, own_key, tts_key is not None, await _token_budget(db, request)
        )
        _require_sufficient(est)
        await require_debate_slot(db, user.id)

    debate = Debate(
        user_id=user.id,
        status="draft" if config.draft else "queued",
        api_token_id=token.id if token is not None and not config.draft else None,
    )
    _apply_config(debate, config, own_key, est)
    db.add(debate)
    await db.commit()
    debate_id = str(debate.id)
    if config.draft or est is None:
        return DebateResponse(debate_id=debate_id, status="draft", message="Draft saved")
    await _enqueue(db, debate, provider_key, tts_key)
    _announce(debate, config, user, est, own_key, token)
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
    _require_manage(debate, user)
    if debate.status != "draft":
        raise HTTPException(status_code=409, detail="Only drafts can be edited")
    if request_api_token(request) is not None:
        config = api_tokens.with_token_defaults(config)
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
    _require_manage(debate, user)
    if debate.status != "draft":
        raise HTTPException(status_code=409, detail=f"Debate is already {debate.status}")
    stored = dict(debate.config_json or {})
    stored.pop("billing", None)
    config = DebateConfig.stored(stored)
    await _require_runnable(config)
    provider_key, own_key = _resolve_provider_key(user, body.user_provider_key if body else None)
    tts_key = _tts_key(config, body.user_tts_key if body else None)
    est = await _estimate(
        config, user, own_key, tts_key is not None, await _token_budget(db, request)
    )
    _require_sufficient(est)
    await require_debate_slot(db, user.id)
    debate.config_json = {**config.persisted(), "billing": _billing(own_key, est)}
    # Whoever starts the run answers for it: its charges count against this token's limit.
    token = request_api_token(request)
    debate.api_token_id = token.id if token is not None else None
    debate.status = "queued"
    debate.error_message = None
    await db.commit()
    await _enqueue(db, debate, provider_key, tts_key)
    _announce(debate, config, user, est, own_key, token, from_draft=True)
    return DebateResponse(debate_id=debate_id, status="queued", message="Debate queued")


@dataclass
class _ResumePlan:
    config: DebateConfig
    from_seq: int
    provider_key: str | None
    own_key: bool
    tts_key: str | None
    est: EstimateOut


async def _resume_plan(
    db: AsyncSession, debate: Debate, user: User, request: Request, body: StartDebateRequest | None
) -> _ResumePlan:
    """Check that a failed debate can be resumed with these keys and price the rest of it."""
    _require_manage(debate, user)
    if debate.status != "error":
        raise HTTPException(status_code=409, detail="Only a debate that failed can be resumed")
    if debate.media_status in ("queued", "running"):
        raise HTTPException(status_code=409, detail="Wait for the audio build to finish")
    stored = dict(debate.config_json or {})
    billing = stored.pop("billing", None) or {}
    config = DebateConfig.stored(stored)
    await _require_runnable(config, starting=False)
    provider_key, own_key = _resolve_provider_key(user, body.user_provider_key if body else None)
    if billing.get("own_key") and not own_key:
        # Its turns so far were not charged; the system key would bill the whole debate.
        raise HTTPException(
            status_code=409,
            detail="This debate ran on your own OpenRouter key: add it again to resume it",
        )
    tts_key = _tts_key(config, body.user_tts_key if body else None)
    from_seq = resume_point(debate.turns)
    est = await _estimate(
        config,
        user,
        own_key,
        tts_key is not None,
        await _token_budget(db, request),
        from_turn=from_seq,
    )
    return _ResumePlan(config, from_seq, provider_key, own_key, tts_key, est)


@router.post("/{debate_id}/resume/estimate", response_model=ResumeEstimateOut)
async def estimate_resume(
    debate_id: str,
    request: Request,
    body: StartDebateRequest | None = None,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> ResumeEstimateOut:
    """What `POST /resume` would run and cost, without starting it (the CLI and MCP ask first)."""
    plan = await _resume_plan(db, await load_debate(db, debate_id, full=True), user, request, body)
    return ResumeEstimateOut(**plan.est.model_dump(), from_turn=plan.from_seq)


@router.post("/{debate_id}/resume", response_model=DebateResponse)
async def resume_debate(
    debate_id: str,
    request: Request,
    body: StartDebateRequest | None = None,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> DebateResponse:
    """Run a debate that stopped with an error again from the turn that failed: that turn (and
    anything after it) is dropped, the earlier turns and the participants' models stay."""
    debate = await load_debate(db, debate_id, full=True)
    plan = await _resume_plan(db, debate, user, request, body)
    runtime_settings.require_runs_open(await runtime_settings.current())
    _require_sufficient(plan.est)
    await require_debate_slot(db, debate.user_id or user.id)

    await reset_for_resume(db, debate, plan.from_seq)
    debate.config_json = {**plan.config.persisted(), "billing": _billing(plan.own_key, plan.est)}
    token = request_api_token(request)
    if token is not None:  # from the browser the run stays on the token that started it
        debate.api_token_id = token.id
    await db.commit()
    await _enqueue(db, debate, plan.provider_key, plan.tts_key, from_seq=plan.from_seq)
    return DebateResponse(
        debate_id=debate_id, status="queued", message=f"Resumed from turn {plan.from_seq + 1}"
    )


@router.get("/{debate_id}", response_model=DebateDetail)
async def get_debate(
    debate_id: str,
    request: Request,
    viewer: User | None = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DebateDetail:
    """Debate details including participants and all turns."""
    debate = await load_debate(db, debate_id, full=True)
    if not can_view(debate, viewer):
        raise HTTPException(status_code=403, detail="This debate is private")
    await count_view(db, debate, viewer, request)
    return detail_out(
        debate,
        viewer,
        await engagement_out(db, debate, viewer),
        manager=can_manage(debate, viewer),
    )


@router.post("/{debate_id}/stop", response_model=StopDebateResponse)
async def stop_debate(
    debate_id: str,
    request: Request,
    user: User | None = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StopDebateResponse:
    """Stop a queued or running debate. The current turn finishes early."""
    debate = await load_debate(db, debate_id)
    _require_manage(debate, user)
    if debate.status not in ACTIVE_STATUSES:
        raise HTTPException(status_code=409, detail=f"Debate is already {debate.status}")

    await stop_debate_run(db, debate)
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
    _require_manage(debate, user)
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
    """Make a finished debate public (gallery + share link). A debate flagged by the AI check
    is only queued for an admin review (approved in the admin console)."""
    debate = await load_debate(db, debate_id)
    _require_manage(debate, user)
    if debate.status != "completed":
        raise HTTPException(status_code=409, detail="Only completed debates can be published")
    if debate.moderation_status == "rejected":
        raise HTTPException(
            status_code=409, detail="This debate was not approved for the public gallery"
        )
    if debate.moderation_status == "flagged":
        debate.moderation_json = {**(debate.moderation_json or {}), "publish_requested": True}
        await db.commit()
        return PublishOut(is_public=False, slug=None, share_url=None, moderation_status="flagged")
    if not await publish_async(db, debate):
        raise HTTPException(status_code=500, detail="Could not allocate a share link")
    debate.category = body.category or debate.category
    await db.commit()
    return PublishOut(
        is_public=True,
        slug=debate.slug,
        share_url=share_url(debate),
        moderation_status=debate.moderation_status,
    )


@router.delete("/{debate_id}/publish", response_model=PublishOut)
async def unpublish_debate(
    debate_id: str,
    request: Request,
    user: User | None = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PublishOut:
    debate = await load_debate(db, debate_id)
    _require_manage(debate, user)
    debate.is_public = False
    # Withdraws a pending review request as well.
    debate.moderation_json = {**(debate.moderation_json or {}), "publish_requested": False}
    await db.commit()
    return PublishOut(
        is_public=False,
        slug=debate.slug,
        share_url=None,
        moderation_status=debate.moderation_status,
    )


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
    _require_manage(debate, user)
    state = dict(debate.media_json or {})
    renders = dict(state.get("renders") or {})
    renders[body.kind] = int(renders.get(body.kind) or 0) + 1
    debate.media_json = {**state, "renders": renders}
    await db.commit()
    return RendersOut(renders={k: int(v) for k, v in renders.items()})
