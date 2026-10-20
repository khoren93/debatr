"""Debates in the admin console (`/api/admin/debates*`, `/api/admin/moderation`): list, card,
moderation queue and the changes an admin makes to a debate.

Reads need `debates.read` (money columns also `money`) and run in a read-only transaction;
opening someone's private debate is written to the audit log (once an hour per admin and
debate). Changes name a reason and are audited in the same transaction: stop, resume (system key
only), a free audio rebuild, recount, delete (sudo) need `debates`; publish / unpublish /
approve / reject and moving a debate to another topic (or merging topics) need
`moderation`; a refund needs `money` and goes through the ledger with
`provider_ref = admin:refund:<debate>:<idempotency key>`. The card's player reads the media folder
through `/debates/{id}/files/…` (`debates.read`).
"""

import contextlib
import logging
import shutil
import time
import uuid
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from redis.exceptions import RedisError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette.concurrency import run_in_threadpool

from app.admin.access import AdminContext, read_only_db, require_admin, sudo_required
from app.core.config import settings
from app.core.db import AsyncSessionLocal, get_db
from app.core.media_static import MediaStaticFiles
from app.core.redis import get_async_redis, stop_flag_key, tts_key_key
from app.models.models import CreditTransaction, Debate
from app.schemas.admin import (
    ActionOut,
    AdminDebateCard,
    AdminDebateList,
    CoverRegenerateRequest,
    CoverSelectRequest,
    DebateFilters,
    DebateListQuery,
    MediaRebuildRequest,
    ModerationQueue,
    MotionMoveRequest,
    ReasonRequest,
    RefundOut,
    RefundRequest,
)
from app.schemas.media import MediaOptions
from app.services import indexnow, motions, runtime_settings
from app.services.admin import audit
from app.services.admin import debates as admin_debates
from app.services.credits import apply_transaction, lever_prices, lock_balance, to_usd
from app.services.debate_control import ACTIVE_STATUSES, mark_stopped, signal_stopped
from app.services.engagement import recount
from app.services.media import cover as covers
from app.services.media.paths import MediaPaths
from app.services.media.tts.elevenlabs import system_key_status
from app.services.moderation import mark_admin_decision, publish_async, wants_public
from app.services.queue_manager import (
    enqueue_cover_build,
    enqueue_debate_start,
    enqueue_media_build,
)
from app.services.resume import reset_for_resume, resume_point

logger = logging.getLogger(__name__)
router = APIRouter()

VIEW_MEMORY_SECONDS = 3600
FINISHED = ("completed", "error", "stopped")


def _uuid(raw: str) -> uuid.UUID:
    try:
        return uuid.UUID(raw)
    except ValueError:
        raise HTTPException(status_code=404, detail="No such debate") from None


async def _debate(
    db: AsyncSession, debate_id: str, *, lock: bool = False, turns: bool = False
) -> Debate:
    query = select(Debate).where(Debate.id == _uuid(debate_id))
    if lock:
        query = query.with_for_update()
    if turns:
        query = query.options(selectinload(Debate.turns))
    debate = await db.scalar(query)
    if debate is None:
        raise HTTPException(status_code=404, detail="No such debate")
    return debate


def _sudo(ctx: AdminContext) -> None:
    if not ctx.session.is_sudo(time.time()):
        raise sudo_required()


async def _record(
    db: AsyncSession,
    ctx: AdminContext,
    request: Request,
    action: str,
    debate: Debate,
    reason: str | None,
    **changes: object,
) -> None:
    await audit.record(
        db,
        action,
        request=request,
        actor=ctx.user,
        target_type="debate",
        target_id=debate.id,
        reason=reason,
        before={"title": debate.title, "owner": str(debate.user_id) if debate.user_id else None},
        after=dict(changes) or None,
        commit=False,
    )


# --- reading ------------------------------------------------------------------------------------


@router.get("/debates", response_model=AdminDebateList)
async def list_debates(
    query: Annotated[DebateListQuery, Query()],
    ctx: AdminContext = Depends(require_admin("debates.read")),
    db: AsyncSession = Depends(read_only_db),
) -> AdminDebateList:
    filters = DebateFilters.model_validate(
        query.model_dump(include=set(DebateFilters.model_fields))
    )
    total, rows = await admin_debates.list_debates(
        db,
        filters,
        sort=query.sort,
        descending=query.order == "desc",
        limit=query.limit,
        offset=query.offset,
        with_money=ctx.can("money"),
    )
    return AdminDebateList.model_validate(
        {"total": total, "limit": query.limit, "offset": query.offset, "rows": rows}
    )


async def _note_private_view(request: Request, ctx: AdminContext, debate: Debate) -> None:
    """Someone else's private debate was opened: one audit row per admin, debate and hour."""
    if not admin_debates.is_private(debate) or debate.user_id == ctx.user.id:
        return
    try:
        fresh = await get_async_redis().set(
            admin_debates.recently_viewed_key(ctx.user.id, debate.id),
            "1",
            ex=VIEW_MEMORY_SECONDS,
            nx=True,
        )
    except RedisError:
        fresh = True
    if not fresh:
        return
    async with AsyncSessionLocal() as db:
        await audit.record(
            db,
            "debate.viewed",
            request=request,
            actor=ctx.user,
            target_type="debate",
            target_id=debate.id,
            before={"title": debate.title, "owner": str(debate.user_id)},
        )


@router.get("/debates/{debate_id}", response_model=AdminDebateCard)
async def debate_card(
    debate_id: str,
    request: Request,
    ctx: AdminContext = Depends(require_admin("debates.read")),
    db: AsyncSession = Depends(read_only_db),
) -> AdminDebateCard:
    with_money = ctx.can("money")
    found = await admin_debates.debate_row(db, _uuid(debate_id), with_money=with_money)
    if found is None:
        raise HTTPException(status_code=404, detail="No such debate")
    debate, row = found
    card = await admin_debates.debate_card(
        db, get_async_redis(), debate, row, with_money=with_money
    )
    await _note_private_view(request, ctx, debate)
    return AdminDebateCard.model_validate(card)


@router.get("/debates/{debate_id}/files/{path:path}")
async def debate_file(
    debate_id: str,
    path: str,
    request: Request,
    _: AdminContext = Depends(require_admin("debates.read")),
) -> Response:
    """A file of the debate's media folder (timeline, audio, scene pictures) for the card's
    player: the site's `/api/media/files` is closed on the admin host. Rooted at the debate's
    own folder, so a path cannot reach another debate's files; Range requests work."""
    files = MediaStaticFiles(directory=MediaPaths(str(_uuid(debate_id))).dir, check_dir=False)
    return await files.get_response(path, request.scope)


@router.get("/moderation", response_model=ModerationQueue)
async def moderation_queue(
    _ctx: AdminContext = Depends(require_admin("moderation")),
    db: AsyncSession = Depends(read_only_db),
) -> ModerationQueue:
    return ModerationQueue.model_validate(await admin_debates.moderation_queue(db))


# --- runs -----------------------------------------------------------------------------------------


@router.post("/debates/{debate_id}/stop", response_model=ActionOut)
async def stop(
    debate_id: str,
    body: ReasonRequest,
    request: Request,
    ctx: AdminContext = Depends(require_admin("debates")),
    db: AsyncSession = Depends(get_db),
) -> ActionOut:
    debate = await _debate(db, debate_id, lock=True)
    if debate.status not in ACTIVE_STATUSES:
        raise HTTPException(status_code=409, detail=f"The debate is {debate.status}, not running")
    before = debate.status
    mark_stopped(debate)
    await _record(db, ctx, request, "debate.stopped", debate, body.reason, was=before)
    await db.commit()
    await signal_stopped(str(debate.id))
    return ActionOut(status="stopped", message="Stopped; a running turn ends early")


@router.post("/debates/{debate_id}/resume", response_model=ActionOut)
async def resume(
    debate_id: str,
    body: ReasonRequest,
    request: Request,
    ctx: AdminContext = Depends(require_admin("debates")),
    db: AsyncSession = Depends(get_db),
) -> ActionOut:
    """Run a failed debate again from its failed turn on the system key. The owner is charged
    for what the run adds, as if they resumed it (refund it afterwards when it was our fault)."""
    debate = await _debate(db, debate_id, lock=True, turns=True)
    own_key = bool(((debate.config_json or {}).get("billing") or {}).get("own_key"))
    if not admin_debates.can_resume(debate, own_key):
        detail = (
            "It ran on the owner's OpenRouter key: only they can resume it"
            if own_key
            else "Only a failed debate without an audio build in progress can be resumed"
        )
        raise HTTPException(status_code=409, detail=detail)
    from_seq = resume_point(debate.turns)
    await reset_for_resume(db, debate, from_seq)
    await _record(db, ctx, request, "debate.resumed", debate, body.reason, from_turn=from_seq)
    await db.commit()
    try:
        await run_in_threadpool(enqueue_debate_start, str(debate.id), from_seq)
    except RedisError:
        logger.exception("Failed to enqueue the resumed debate %s", debate.id)
        debate.status = "error"
        debate.error_message = "Job queue unavailable"
        await db.commit()
        raise HTTPException(status_code=503, detail="The job queue is unavailable") from None
    return ActionOut(status="queued", message=f"Resumed from turn {from_seq + 1}")


def _rebuild_options(debate: Debate) -> MediaOptions:
    """The last build's options, or the plan the debate was created with."""
    state = debate.media_json or {}
    if state.get("options"):
        return MediaOptions.model_validate(state["options"])
    plan: dict[str, Any] = (debate.config_json or {}).get("media_plan") or {}
    options: dict[str, Any] = {
        "provider": plan.get("provider") or "edge",
        "voices": plan.get("voices") or {},
        "visuals": bool(plan.get("visuals", True)),
        "images": plan.get("images") or "off",
    }
    if plan.get("model_id"):
        options["model_id"] = plan["model_id"]
    return MediaOptions.model_validate(options)


@router.post("/debates/{debate_id}/media", response_model=ActionOut)
async def rebuild_media(
    debate_id: str,
    body: MediaRebuildRequest,
    request: Request,
    ctx: AdminContext = Depends(require_admin("debates")),
    db: AsyncSession = Depends(get_db),
) -> ActionOut:
    """Build the audio again with the same options on the system keys, free for the owner."""
    debate = await _debate(db, debate_id, lock=True)
    if debate.status not in FINISHED:
        raise HTTPException(status_code=409, detail="The debate has not finished yet")
    if debate.media_status in ("queued", "running"):
        raise HTTPException(status_code=409, detail="An audio build is already in progress")
    options = _rebuild_options(debate)
    if options.provider == "elevenlabs":
        ok, why = await run_in_threadpool(system_key_status)
        if not ok:
            raise HTTPException(status_code=409, detail=f"Premium voices are unavailable: {why}")
    state = dict(debate.media_json or {})
    state.update(
        {
            "options": options.model_dump(),
            "force": body.force,
            "own_tts_key": False,
            "auto": False,
            "free": True,
            "step": "queued",
            "current": 0,
            "total": 0,
            "message": "Queued",
            "error": None,
            "started_at": None,
            "finished_at": None,
        }
    )
    debate.media_json = state
    debate.media_status = "queued"
    await _record(
        db,
        ctx,
        request,
        "debate.media_rebuilt",
        debate,
        body.reason,
        provider=options.provider,
        images=options.images,
        force=body.force,
    )
    await db.commit()
    try:
        redis = get_async_redis()
        await redis.delete(tts_key_key(str(debate.id)))
        await run_in_threadpool(enqueue_media_build, str(debate.id))
    except RedisError:
        logger.exception("Failed to enqueue the media build of %s", debate.id)
        debate.media_status = "error"
        debate.media_json = {**state, "error": "Job queue unavailable"}
        await db.commit()
        raise HTTPException(status_code=503, detail="The job queue is unavailable") from None
    return ActionOut(status="queued", message="Audio build queued (free for the owner)")


@router.post("/debates/{debate_id}/cover", response_model=ActionOut)
async def regenerate_cover(
    debate_id: str,
    body: CoverRegenerateRequest,
    request: Request,
    ctx: AdminContext = Depends(require_admin("debates")),
    db: AsyncSession = Depends(get_db),
) -> ActionOut:
    """Draw a new AI cover version on the system key, free for the owner (a lever set to "off"
    does not stop the console)."""
    debate = await _debate(db, debate_id, lock=True)
    if debate.status not in ("completed", "stopped"):
        raise HTTPException(status_code=409, detail="The debate has not finished yet")
    if debate.cover_status in covers.ACTIVE:
        raise HTTPException(status_code=409, detail="A cover is already being drawn")
    prices = lever_prices(await runtime_settings.current())
    debate.cover_json = covers.queued_state(
        debate.cover_json,
        source="admin",
        own_key=False,
        free=True,
        prices=prices.as_dict(),
        hook=(body.hook or "").strip() or None,
    )
    debate.cover_status = "queued"
    await _record(db, ctx, request, "debate.cover_generated", debate, body.reason, hook=body.hook)
    await db.commit()
    try:
        await run_in_threadpool(enqueue_cover_build, str(debate.id))
    except RedisError:
        logger.exception("Failed to enqueue the cover of %s", debate.id)
        debate.cover_status = "error"
        debate.cover_json = {**(debate.cover_json or {}), "error": "Job queue unavailable"}
        await db.commit()
        raise HTTPException(status_code=503, detail="The job queue is unavailable") from None
    return ActionOut(status="queued", message="Cover queued (free for the owner)")


@router.post("/debates/{debate_id}/cover/select", response_model=ActionOut)
async def select_cover(
    debate_id: str,
    body: CoverSelectRequest,
    request: Request,
    ctx: AdminContext = Depends(require_admin("moderation")),
    db: AsyncSession = Depends(get_db),
) -> ActionOut:
    """Show another cover version, or none (`version: null`: the markup cover, e.g. a picture
    that should not be in the gallery)."""
    debate = await _debate(db, debate_id, lock=True)
    before = (debate.cover_json or {}).get("current")
    try:
        debate.cover_json = covers.select_version(dict(debate.cover_json or {}), body.version)
    except KeyError:
        raise HTTPException(status_code=404, detail="No such cover version") from None
    await _record(
        db,
        ctx,
        request,
        "debate.cover_selected",
        debate,
        body.reason,
        before=before,
        version=body.version,
    )
    await db.commit()
    return ActionOut(
        status="ok", message="Cover changed" if body.version else "The markup cover is shown"
    )


@router.post("/debates/{debate_id}/recount", response_model=ActionOut)
async def recount_reactions(
    debate_id: str,
    body: ReasonRequest,
    request: Request,
    ctx: AdminContext = Depends(require_admin("debates")),
    db: AsyncSession = Depends(get_db),
) -> ActionOut:
    debate = await _debate(db, debate_id)
    before = {"likes": debate.likes_count, "votes": debate.votes_count}
    await recount(db, debate.id, commit=False)
    await db.refresh(debate)
    after = {"likes": debate.likes_count, "votes": debate.votes_count}
    await _record(db, ctx, request, "debate.recounted", debate, body.reason, was=before, now=after)
    await db.commit()
    return ActionOut(
        status="ok",
        message=f"{after['likes']} likes, {after['votes']} votes "
        f"(were {before['likes']} and {before['votes']})",
    )


@router.post("/debates/{debate_id}/delete", response_model=ActionOut)
async def delete(
    debate_id: str,
    body: ReasonRequest,
    request: Request,
    ctx: AdminContext = Depends(require_admin("debates")),
    db: AsyncSession = Depends(get_db),
) -> ActionOut:
    """Delete the debate with its turns, likes, votes and files (sudo). Its ledger rows stay."""
    _sudo(ctx)
    debate = await _debate(db, debate_id, lock=True)
    active = debate.status in ACTIVE_STATUSES
    await audit.record(
        db,
        "debate.deleted",
        request=request,
        actor=ctx.user,
        target_type="debate",
        target_id=debate.id,
        reason=body.reason,
        before={
            "title": debate.title,
            "owner": str(debate.user_id) if debate.user_id else None,
            "status": debate.status,
            "public": debate.is_public,
            "slug": debate.slug,
            "created_at": debate.created_at,
        },
        commit=False,
    )
    gone = indexnow.debate_refs(debate) if debate.is_public else []
    await db.delete(debate)
    await db.commit()
    await indexnow.announce(gone)
    if active:
        with contextlib.suppress(RedisError):
            await get_async_redis().set(stop_flag_key(debate_id), "1", ex=3600)
    await run_in_threadpool(shutil.rmtree, MediaPaths(debate_id).dir, True)
    return ActionOut(status="deleted", message="Debate deleted")


# --- gallery and moderation -----------------------------------------------------------------------


@router.post("/debates/{debate_id}/approve", response_model=ActionOut)
async def approve(
    debate_id: str,
    body: ReasonRequest,
    request: Request,
    ctx: AdminContext = Depends(require_admin("moderation")),
    db: AsyncSession = Depends(get_db),
) -> ActionOut:
    """Approve for the gallery; published at once when the owner wants it public."""
    debate = await _debate(db, debate_id, lock=True)
    before = debate.moderation_status
    mark_admin_decision(debate, approved=True)
    debate.moderation_json = {**(debate.moderation_json or {}), "admin_reason": body.reason}
    published = False
    if debate.status == "completed" and wants_public(debate):
        published = await publish_async(db, debate)
    await _record(
        db,
        ctx,
        request,
        "moderation.approved",
        debate,
        body.reason,
        was=before,
        published=published,
    )
    await db.commit()
    if published:
        await indexnow.announce(indexnow.debate_refs(debate))
    return ActionOut(
        status="approved",
        message="Approved and published" if published else "Approved (the owner keeps it private)",
    )


@router.post("/debates/{debate_id}/reject", response_model=ActionOut)
async def reject(
    debate_id: str,
    body: ReasonRequest,
    request: Request,
    ctx: AdminContext = Depends(require_admin("moderation")),
    db: AsyncSession = Depends(get_db),
) -> ActionOut:
    """Keep it out of the gallery: unpublished now, and the owner cannot publish it."""
    debate = await _debate(db, debate_id, lock=True)
    before = {"moderation": debate.moderation_status, "public": debate.is_public}
    mark_admin_decision(debate, approved=False)
    debate.moderation_json = {**(debate.moderation_json or {}), "admin_reason": body.reason}
    await _record(db, ctx, request, "moderation.rejected", debate, body.reason, was=before)
    await db.commit()
    if before["public"]:
        await indexnow.announce(indexnow.debate_refs(debate))
    return ActionOut(status="rejected", message="Rejected; it stays out of the gallery")


@router.post("/debates/{debate_id}/publish", response_model=ActionOut)
async def publish(
    debate_id: str,
    body: ReasonRequest,
    request: Request,
    ctx: AdminContext = Depends(require_admin("moderation")),
    db: AsyncSession = Depends(get_db),
) -> ActionOut:
    """Put a completed debate in the gallery, only when its owner asked for that (approving a
    flagged one is done with Approve)."""
    debate = await _debate(db, debate_id, lock=True)
    if debate.is_public:
        raise HTTPException(status_code=409, detail="It is already public")
    if debate.status != "completed":
        raise HTTPException(status_code=409, detail="Only completed debates can be published")
    if debate.moderation_status in ("flagged", "rejected"):
        raise HTTPException(
            status_code=409, detail=f"It is {debate.moderation_status}: decide on it first"
        )
    if not wants_public(debate):
        raise HTTPException(status_code=409, detail="The owner keeps this debate private")
    if not await publish_async(db, debate):
        raise HTTPException(status_code=500, detail="Could not allocate a share link")
    await _record(db, ctx, request, "debate.published", debate, body.reason, slug=debate.slug)
    await db.commit()
    await indexnow.announce(indexnow.debate_refs(debate))
    return ActionOut(status="public", message="Published to the gallery")


@router.post("/debates/{debate_id}/unpublish", response_model=ActionOut)
async def unpublish(
    debate_id: str,
    body: ReasonRequest,
    request: Request,
    ctx: AdminContext = Depends(require_admin("moderation")),
    db: AsyncSession = Depends(get_db),
) -> ActionOut:
    """Take it out of the gallery (the owner may publish it again unless it is rejected)."""
    debate = await _debate(db, debate_id, lock=True)
    if not debate.is_public:
        raise HTTPException(status_code=409, detail="It is not public")
    debate.is_public = False
    await _record(db, ctx, request, "debate.unpublished", debate, body.reason)
    await db.commit()
    await indexnow.announce(indexnow.debate_refs(debate))
    return ActionOut(status="private", message="Taken out of the gallery")


@router.post("/debates/{debate_id}/motion", response_model=ActionOut)
async def move_motion(
    debate_id: str,
    body: MotionMoveRequest,
    request: Request,
    ctx: AdminContext = Depends(require_admin("moderation")),
    db: AsyncSession = Depends(get_db),
) -> ActionOut:
    """Fix how versions are grouped: move this debate into another topic, give it a topic of its
    own (no target), or merge its whole topic into another one (`whole`; its text and slug then
    lead there too)."""
    debate = await _debate(db, debate_id, lock=True)
    source = await motions.resolve(db, debate.motion_id) if debate.motion_id else None
    before = await motions.motion_summary(db, source)
    target: uuid.UUID | None = None
    if body.target and body.target.strip():
        target = await motions.find_target(db, body.target)
        if target is None:
            raise HTTPException(status_code=404, detail="No topic or debate behind that link")
        if target == source:
            raise HTTPException(status_code=409, detail="It is already in that topic")
    elif body.whole:
        raise HTTPException(status_code=400, detail="Name the topic to merge into")
    elif before is not None and before["debates"] <= 1:
        raise HTTPException(status_code=409, detail="It already has a topic of its own")

    moved = 1
    if body.whole and source is not None and target is not None:
        moved = await motions.merge_motions(db, source, target)
        debate.motion_id = target
        message = f"Topic merged: {moved} {'debate' if moved == 1 else 'debates'} moved"
    elif target is not None:
        debate.motion_id = target
        message = "Moved to the other topic"
    else:
        debate.motion_id = await motions.new_motion(db)
        message = "Split off into a topic of its own"
    after = await motions.motion_summary(db, debate.motion_id)
    await _record(
        db,
        ctx,
        request,
        "debate.motion_changed",
        debate,
        body.reason,
        motion_from=before["slug"] if before else None,
        motion_to=after["slug"] if after else None,
        whole=body.whole,
        moved=moved,
    )
    await db.commit()
    if debate.is_public:
        # Both topic pages changed (a merged one now leads to its target).
        await indexnow.announce(
            [*indexnow.debate_refs(debate), *indexnow.refs_of(None, "", source)]
        )
    return ActionOut(status="moved", message=message)


# --- money ----------------------------------------------------------------------------------------


async def _refund_done(db: AsyncSession, ref: str, debate: Debate) -> RefundOut | None:
    tx = await db.scalar(select(CreditTransaction).where(CreditTransaction.provider_ref == ref))
    if tx is None:
        return None
    if tx.debate_id != debate.id:
        raise HTTPException(status_code=409, detail="This request was used for another debate")
    return RefundOut(
        transaction_id=str(tx.id),
        amount=float(tx.amount_usd),
        balance_after=float(tx.balance_after_usd),
        duplicate=True,
    )


@router.post("/debates/{debate_id}/refund", response_model=RefundOut)
async def refund(
    debate_id: str,
    body: RefundRequest,
    request: Request,
    ctx: AdminContext = Depends(require_admin("money")),
    db: AsyncSession = Depends(get_db),
) -> RefundOut:
    """Give the owner back what the debate cost them (all of it, or part), as a `refund` ledger
    row tied to the debate. Never more than its net charge; sudo above ADMIN_SUDO_USD."""
    debate = await _debate(db, debate_id)
    if debate.user_id is None:
        raise HTTPException(status_code=409, detail="The debate has no owner to refund")
    if body.amount is not None and to_usd(body.amount) <= 0:
        raise HTTPException(status_code=422, detail="Refund a positive amount")
    ref = f"admin:refund:{debate.id}:{body.idempotency_key}"
    done = await _refund_done(db, ref, debate)
    if done is not None:
        return done
    balance = await lock_balance(db, debate.user_id)  # serializes refunds of this owner
    if balance is None:
        raise HTTPException(status_code=409, detail="The owner's account is gone")
    net = await db.scalar(
        select(func.coalesce(func.sum(CreditTransaction.amount_usd), 0)).where(
            CreditTransaction.debate_id == debate.id
        )
    )
    left = to_usd(admin_debates.refundable(-float(net or 0)))
    amount = to_usd(body.amount) if body.amount is not None else left
    if amount <= 0:
        raise HTTPException(status_code=409, detail="Nothing left to refund for this debate")
    if amount > left:
        raise HTTPException(
            status_code=422, detail=f"At most ${left.normalize():f} is left to refund"
        )
    if amount > to_usd(Decimal(str(settings.ADMIN_SUDO_USD))):
        _sudo(ctx)
    await _record(
        db,
        ctx,
        request,
        "debate.refunded",
        debate,
        body.reason,
        amount_usd=str(amount),
        balance_before=str(balance),
        provider_ref=ref,
    )
    try:
        tx = await apply_transaction(
            db,
            debate.user_id,
            amount,
            "refund",
            description=f"Refund: {(debate.title or 'Debate')[:280]}",
            debate_id=debate.id,
            provider="admin",
            provider_ref=ref,
            meta={"reason": body.reason, "source": "console", "admin": ctx.user.email},
        )
    except IntegrityError:
        await db.rollback()
        done = await _refund_done(db, ref, debate)
        if done is None:
            raise
        return done
    if tx is None:
        await db.rollback()
        raise HTTPException(status_code=409, detail="The owner's account is gone")
    return RefundOut(
        transaction_id=str(tx.id),
        amount=float(tx.amount_usd),
        balance_after=float(tx.balance_after_usd),
        duplicate=False,
    )
