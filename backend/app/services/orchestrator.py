"""RQ jobs that drive a debate: start -> turn* -> verdict -> finish.

Runs in the worker process only. Uses a blocking SQLAlchemy engine because RQ
jobs are synchronous; LLM streaming happens inside a short-lived asyncio loop.
When a debate reaches a terminal state the owner's credits are charged and, if the
configuration asks for it, the audio build is queued automatically. A completed debate is
checked for the gallery and published when its owner asked for that (`services/moderation`).
A turn without an answer stops the debate (`status=error`); the owner may resume it from that
turn (`services/resume`).
"""

import asyncio
import logging
import math
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.redis import (
    debate_beat_key,
    get_sync_redis,
    provider_key_key,
    stop_flag_key,
    tts_key_key,
)
from app.core.sync_db import get_sync_session
from app.models.models import Debate, Turn, utcnow
from app.services import indexnow, queue_manager, runtime_settings
from app.services import usage as usage_log
from app.services.credits import charge_debate_sync, charge_images_sync, debate_prices
from app.services.events import publish_event
from app.services.formats import Format, format_of
from app.services.free_quota import is_free_model, wait_for_slot
from app.services.free_router import (
    FREE_ROUTER_ID,
    fallback_models,
    is_classifier,
    is_free_router,
    participant_row,
    pinned_model,
    routed_model,
    worth_pinning,
)
from app.services.heartbeat import beating
from app.services.markers import extract_markers, has_markers
from app.services.media.tts.elevenlabs import system_key_status
from app.services.moderation import (
    apply_check,
    check_debate,
    fallback_result,
    publish_sync,
    should_auto_publish,
)
from app.services.openrouter_client import OpenRouterClient, OpenRouterError
from app.services.scheduler import ScheduledTurn, speaker_role_for
from app.services.studio import (
    claims_prompt,
    claims_summary,
    design_turn,
    initial_visuals,
    live_pictures_cost,
    resolve_disputes,
    turn_visuals_out,
    verdict_evidence,
    visual_claims,
    visuals_enabled,
)
from app.services.verdict import debaters_from_config, fallback_verdict, structure_verdict

logger = logging.getLogger(__name__)

VERDICT_SPEAKER_NAME = "⚖️ Verdict"
STOP_CHECK_EVERY_N_CHUNKS = 10
# Pauses before trying a failed answer again: rate limits, provider 5xx and dropped connections
# usually pass, and a failed turn stops the whole debate. Only before any text was streamed.
RETRY_PAUSES = (3.0, 10.0)
RETRY_STATUSES = {408, 425, 429, 500, 502, 503, 504}
ROUTER_TRIES = 3  # Free Router answers too short for a turn are asked again, this many in all
SERVICE_SLOT_WAIT = 60.0  # seconds the free verdict model waits for a free-model slot

get_session = get_sync_session


# --- helpers ---------------------------------------------------------------


@dataclass
class GenerationResult:
    text: str = ""
    usage: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    stopped: bool = False
    timed_out: bool = False  # no complete answer within LLM_TURN_TIMEOUT
    retryable: bool = False  # a passing failure (rate limit, 5xx, connection, empty answer)
    rerouted: bool = False  # the router picked a classifier: dropped before any text, ask again
    model: str | None = None  # as named by the response (a router names the model it picked)
    error_kind: str | None = None  # usage.classify_error's word for a failure
    duration_ms: int | None = None  # request to end of stream
    ttft_ms: int | None = None  # request to the first text


def _normalize_usage(raw: dict[str, Any] | None) -> dict[str, Any]:
    if not raw:
        return {}
    return {
        "prompt_tokens": int(raw.get("prompt_tokens") or 0),
        "completion_tokens": int(raw.get("completion_tokens") or 0),
        "total_tokens": int(raw.get("total_tokens") or 0),
        "cost": float(raw.get("cost") or 0.0),
    }


def _serialize_turn(turn: Turn, fmt: Format) -> dict[str, Any]:
    visuals = turn_visuals_out(turn)
    return {
        "seq_index": turn.seq_index,
        "round_id": turn.round_id,
        "round_label": fmt.round_label(turn.round_id, turn.turn_type),
        "turn_type": turn.turn_type,
        "speaker_role": speaker_role_for(turn.turn_type),
        "speaker_id": turn.speaker_id,
        "speaker_name": turn.speaker_name,
        "text": turn.text,
        "error": turn.error,
        "model_used": turn.model_used,
        "usage": turn.usage_json or {},
        "created_at": turn.created_at.isoformat() if turn.created_at else None,
        "visuals": visuals.model_dump(mode="json") if visuals else None,
    }


def _turns(db: Session, debate_id: uuid.UUID) -> list[Turn]:
    return list(
        db.scalars(select(Turn).where(Turn.debate_id == debate_id).order_by(Turn.seq_index)).all()
    )


def _history(db: Session, debate_id: uuid.UUID) -> list[dict[str, Any]]:
    turns = _turns(db, debate_id)
    return [
        {"speaker_name": t.speaker_name, "text": t.text, "turn_type": t.turn_type}
        for t in turns
        if t.text and t.text.strip()
    ]


def _compute_totals(db: Session, debate: Debate) -> dict[str, Any]:
    """Token/cost totals over all turns plus the fact-checks (`analysis_cost`): what the owner is
    charged for. `service_cost` (verdict structuring, the gallery check) is kept apart: those
    calls serve the site, not the user, so a debate on free models stays free."""
    turns = db.scalars(select(Turn).where(Turn.debate_id == debate.id)).all()
    previous = debate.totals_json or {}
    analysis_cost = float(previous.get("analysis_cost") or 0.0)
    service_cost = float(previous.get("service_cost") or 0.0)
    # Turns a resume dropped (services/resume) were paid for as well.
    discarded_cost = float(previous.get("discarded_cost") or 0.0)
    totals: dict[str, Any] = {
        "tokens_in": 0,
        "tokens_out": 0,
        "cost": analysis_cost + discarded_cost,
        "turns_count": len(turns),
        "analysis_cost": analysis_cost,
    }
    if discarded_cost:
        totals["discarded_cost"] = discarded_cost
    if service_cost:
        totals["service_cost"] = service_cost
    for t in turns:
        usage = t.usage_json or {}
        totals["tokens_in"] += int(usage.get("prompt_tokens") or 0)
        totals["tokens_out"] += int(usage.get("completion_tokens") or 0)
        totals["cost"] += float(usage.get("cost") or 0.0)
    totals["cost"] = round(totals["cost"], 6)
    claims = claims_summary(sorted(turns, key=lambda t: t.seq_index))
    if claims:
        totals["claims"] = claims  # fact-check verdicts per debater (model leaderboard)
    return totals


def _charge(db: Session, debate: Debate) -> None:
    """Charge the owner's credits for a finished run (never lets a billing error kill the job):
    the models (and fact-checks) and the AI pictures of the live scenes."""
    try:
        tx = charge_debate_sync(db, debate)
        if tx is not None:
            logger.info("Charged %s credits for debate %s", -tx.amount_usd, debate.id)
        usd, count = live_pictures_cost(_turns(db, debate.id))
        if count:
            markup = debate_prices(debate).markup
            tx = charge_images_sync(
                db, debate, usd=usd, count=count, build_ref="live", markup=markup
            )
            if tx is not None:
                logger.info("Charged %s credits for pictures of %s", -tx.amount_usd, debate.id)
    except Exception:
        logger.exception("Failed to charge credits for debate %s", debate.id)
        db.rollback()


def _cleanup_keys(debate_id: str, *, keep_tts_key: bool = False) -> None:
    """Drop the run's secrets. The TTS key survives a completed run for the auto audio build."""
    keys = [provider_key_key(debate_id), stop_flag_key(debate_id)]
    if not keep_tts_key:
        keys.append(tts_key_key(debate_id))
    try:
        get_sync_redis().delete(*keys)
    except Exception:
        logger.warning("Failed to clean up Redis keys for debate %s", debate_id)


def _provider_key(debate_id: str) -> str | None:
    try:
        value = get_sync_redis().get(provider_key_key(debate_id))
    except Exception:
        logger.warning("Failed to read provider key for debate %s", debate_id)
        return None
    if value is None:
        return None
    return value.decode() if isinstance(value, bytes) else str(value)


def _stop_requested(debate_id: str) -> bool:
    try:
        return bool(get_sync_redis().exists(stop_flag_key(debate_id)))
    except Exception:
        return False


def fail_debate(db: Session, debate: Debate, message: str) -> None:
    logger.error("Debate %s failed: %s", debate.id, message)
    debate.status = "error"
    debate.error_message = message[:2000]
    debate.ended_at = utcnow()
    debate.totals_json = _compute_totals(db, debate)
    db.commit()
    _charge(db, debate)
    _cleanup_keys(str(debate.id))
    publish_event(str(debate.id), "debate_error", {"debate_id": str(debate.id), "message": message})


def _finalize_stopped(db: Session, debate: Debate) -> None:
    debate.status = "stopped"
    debate.ended_at = debate.ended_at or utcnow()
    debate.totals_json = _compute_totals(db, debate)
    db.commit()
    _charge(db, debate)
    _cleanup_keys(str(debate.id))


def _generate(
    debate_id: str,
    seq_index: int,
    speaker_name: str,
    model_id: str,
    messages: list[dict[str, Any]],
    api_key: str | None,
    deadline: float,
    purpose: str = "turn",
) -> GenerationResult:
    """Stream one LLM response, forwarding deltas to subscribers, until `deadline`
    (`time.monotonic()`; see LLM_TURN_TIMEOUT). Every try is booked in `provider_usage`."""
    if api_key is None and is_free_model(model_id) and not wait_for_slot(deadline):
        return GenerationResult(
            error="Free models are busy (OpenRouter's per-minute limit); resume in a minute",
            error_kind="free_quota",
        )
    # Models the admin console turned off: the router's pick of one is dropped like a classifier.
    turned_off = (
        set(runtime_settings.current_sync().disabled_models) if is_free_router(model_id) else set()
    )

    async def run() -> GenerationResult:
        client = OpenRouterClient()
        result = GenerationResult()
        chunks = 0
        started = time.monotonic()
        stream = client.stream_chat_completion(model_id, messages, api_key=api_key)
        try:
            async with asyncio.timeout(max(0.0, deadline - time.monotonic())):
                async for chunk in stream:
                    if chunk.usage:
                        result.usage = _normalize_usage(chunk.usage)
                    if chunk.model:
                        result.model = chunk.model
                        if is_free_router(model_id) and (
                            is_classifier(chunk.model) or chunk.model in turned_off
                        ):
                            # Labels text instead of arguing ("User Safety: safe"), or is turned
                            # off: drop it before a word is published, the router picks again.
                            why = "is turned off" if chunk.model in turned_off else "cannot debate"
                            result.error = f"The Free Router picked {chunk.model}, which {why}"
                            result.retryable = result.rerouted = True
                            result.error_kind = "classifier"
                            break
                    if not chunk.delta:
                        continue
                    if result.ttft_ms is None:
                        result.ttft_ms = int((time.monotonic() - started) * 1000)
                    result.text += chunk.delta
                    publish_event(
                        debate_id,
                        "turn_delta",
                        {
                            "seq_index": seq_index,
                            "delta": chunk.delta,
                            "speaker_name": speaker_name,
                        },
                    )
                    chunks += 1
                    if chunks % STOP_CHECK_EVERY_N_CHUNKS == 0 and _stop_requested(debate_id):
                        result.stopped = True
                        break
        except TimeoutError:
            logger.warning("%s gave no complete answer in time (debate %s)", model_id, debate_id)
            result.error = f"No complete answer within {settings.LLM_TURN_TIMEOUT:.0f} seconds"
            result.timed_out = True
            result.error_kind = "timeout"
        except OpenRouterError as e:
            result.error = str(e)
            result.retryable = e.status_code is None or e.status_code in RETRY_STATUSES
            result.error_kind = usage_log.classify_error(e.status_code)
        except Exception as e:
            logger.exception("Unexpected generation error for debate %s", debate_id)
            result.error = f"Unexpected error: {e}"
            result.error_kind = "other"
        if not result.error and not result.stopped and not result.text.strip():
            result.error = "The model returned an empty answer"
            result.retryable = True
            result.error_kind = "empty"
        result.duration_ms = int((time.monotonic() - started) * 1000)
        return result

    result = asyncio.run(run())
    _book(debate_id, seq_index, purpose, model_id, api_key, result)
    return result


def _book(
    debate_id: str,
    seq_index: int,
    purpose: str,
    model_id: str,
    api_key: str | None,
    result: GenerationResult,
) -> None:
    """One try of a turn in `provider_usage` (retries and dropped answers cost money too)."""
    answered = result.model if is_free_router(model_id) and result.model else model_id
    meta = {
        "seq_index": seq_index,
        "ttft_ms": result.ttft_ms,
        "stopped": result.stopped or None,
        "reported_model": result.model if result.model and result.model != answered else None,
    }
    usage_log.record(
        purpose,
        model=answered,
        key=usage_log.key_owner(api_key),
        usage=result.usage,
        ok=result.error is None,
        error_kind=result.error_kind,
        duration_ms=result.duration_ms,
        debate_id=debate_id,
        meta={k: v for k, v in meta.items() if v is not None},
    )


def turn_usage(result: GenerationResult) -> dict[str, Any]:
    """`turns.usage_json`: tokens and cost plus the timing of the answer that was kept."""
    timing = {
        "duration_ms": result.duration_ms,
        "ttft_ms": result.ttft_ms,
        "error_kind": result.error_kind,
    }
    return {**result.usage, **{k: v for k, v in timing.items() if v is not None}}


def _failure(speaker: str, model_id: str, error: str | None) -> str:
    """`error_message` of a debate stopped by a failed turn."""
    return f"{speaker} ({model_id}) could not answer: {error or 'no answer'}"


def _with_retries(
    debate_id: str, generate: Callable[[str], GenerationResult], model: str, deadline: float
) -> GenerationResult:
    """`generate(model)`, tried again after RETRY_PAUSES while it fails in a passing way."""
    result = generate(model)
    for pause in RETRY_PAUSES:
        if not result.retryable or result.text or result.stopped:
            break
        wait = 0.0 if result.rerouted else pause  # a classifier pick is not a busy provider
        if time.monotonic() + wait > deadline or _stop_requested(debate_id):
            break
        logger.warning("%s failed (%s), trying again in %.0f s", model, result.error, wait)
        if wait:
            time.sleep(wait)
        result = generate(model)
    return result


def _ask_router(
    debate_id: str, generate: Callable[[str], GenerationResult], deadline: float
) -> GenerationResult:
    """A Free Router answer, asked again while it is too short for a turn (a model that only
    greets, refuses or labels the text); the last one stands if none is better."""
    result = _with_retries(debate_id, generate, FREE_ROUTER_ID, deadline)
    for _ in range(ROUTER_TRIES - 1):
        if result.error or result.stopped or worth_pinning(result.model or "", result.text):
            break
        if time.monotonic() + 10 > deadline or _stop_requested(debate_id):
            break
        words = len(result.text.split())
        logger.warning("Free Router's %s wrote %d words, asking again", result.model, words)
        result = _with_retries(debate_id, generate, FREE_ROUTER_ID, deadline)
    return result


def _answer_without_router(
    debate_id: str,
    generate: Callable[[str], GenerationResult],
    deadline: float,
    failed: GenerationResult,
) -> GenerationResult:
    """The router picked a classifier on every try: a free model that argued well lately
    answers instead (`free_router.fallback_models`); the router's failure stands if none can."""
    for candidate in fallback_models(exclude=[failed.model or ""]):
        if time.monotonic() + 10 > deadline or _stop_requested(debate_id):
            break
        logger.warning(
            "Free Router kept picking %s for debate %s; %s answers instead",
            failed.model,
            debate_id,
            candidate,
        )
        result = generate(candidate)
        if result.text and not result.error:
            result.model = result.model or candidate
            return result
    return failed


def _announcing(
    debate_id: str, started: dict[str, Any], run: Callable[[str], GenerationResult]
) -> Callable[[str], GenerationResult]:
    """`run` for each try of one turn. A try after one that streamed text announces the turn
    again, so live viewers drop the discarded text (the page and the CLI restart the turn on
    `turn_started`)."""
    last: list[GenerationResult] = []

    def attempt(model: str) -> GenerationResult:
        if last and last[-1].text:
            publish_event(debate_id, "turn_started", started)
        last[:] = [run(model)]
        return last[0]

    return attempt


def _generate_as(
    debate: Debate,
    index: int,
    speaker: dict[str, Any],
    generate: Callable[[str], GenerationResult],
    deadline: float = math.inf,
) -> tuple[GenerationResult, str]:
    """Generate a participant's turn; returns the result and the model that answered it.

    Passing failures are tried again (`_with_retries`). A Free Router participant speaks with
    the free model its first answer was routed to (`services/free_router`); when that model
    fails before writing anything, the router answers the turn instead and the pin stays. The
    router is asked again when it picks a classifier or writes too little (`_ask_router`)."""
    requested = str(speaker.get("model_id") or settings.DEFAULT_MODEL_ID)
    if not is_free_router(requested):
        return _with_retries(str(debate.id), generate, requested, deadline), requested
    row = participant_row(debate.participants, index, speaker.get("role"))
    pinned = pinned_model(requested, row)
    # A pinned model the admin console turned off: the router answers, the pin stays.
    if pinned and pinned not in runtime_settings.current_sync().disabled_models:
        result = generate(pinned)
        if result.text or result.stopped or result.timed_out or not result.error:
            return result, pinned
        logger.warning(
            "Pinned %s failed for debate %s (%s), asking the router",
            pinned,
            debate.id,
            result.error,
        )
    result = _ask_router(str(debate.id), generate, deadline)
    if result.error_kind == "classifier" and not result.text and not result.stopped:
        result = _answer_without_router(str(debate.id), generate, deadline, result)
    answered = routed_model(result.model)
    if (
        answered
        and row is not None
        and not pinned
        and not result.error
        and worth_pinning(answered, result.text)
    ):
        row.model_id = answered  # committed with the turn
        logger.info("Debate %s: participant %s pinned to %s", debate.id, index, answered)
    return result, answered or requested


def _save_turn(
    db: Session,
    debate: Debate,
    *,
    seq_index: int,
    round_id: str,
    turn_type: str,
    speaker_id: str,
    speaker_name: str,
    model_id: str,
    result: GenerationResult,
    visuals: dict[str, Any] | None = None,
) -> Turn:
    turn = Turn(
        debate_id=debate.id,
        seq_index=seq_index,
        round_id=round_id,
        turn_type=turn_type,
        speaker_id=speaker_id,
        speaker_name=speaker_name,
        text=result.text,
        error=result.error,
        word_count=len(result.text.split()),
        model_used=model_id,
        usage_json=turn_usage(result),
        visuals_json=visuals or {},
    )
    db.add(turn)
    db.commit()
    db.refresh(turn)
    payload = _serialize_turn(turn, format_of(debate.config_json or {}))
    publish_event(str(debate.id), "turn_error" if result.error else "turn_completed", payload)
    if result.error:
        logger.warning("Turn %s of debate %s failed: %s", seq_index, debate.id, result.error)
    return turn


def _verdict_model(debate: Debate) -> str:
    """Who structures the verdict and answers the gallery check: the console's free model when
    every participant argued on a free model, so a free debate costs nothing, else VERDICT_MODEL.
    Never one of the debate's own models: its author picked those."""
    free = runtime_settings.current_sync().free_verdict_model
    participants = (debate.config_json or {}).get("participants") or []
    models = [str(p.get("model_id") or "") for p in participants]
    if free and models and all(is_free_model(m) for m in models):
        return free
    return settings.VERDICT_MODEL


def _service_slot(model: str, api_key: str | None) -> bool:
    """A free model on the system key waits for a slot of the shared free-model quota, as turns
    do (own keys have their account's own limit)."""
    if api_key is not None or not is_free_model(model):
        return True
    return wait_for_slot(time.monotonic() + SERVICE_SLOT_WAIT)


def _store_verdict(db: Session, debate: Debate, verdict_text: str, api_key: str | None) -> None:
    """Structure the judge's text (winner, headline, feedback) for the UI and the video."""
    conf: dict[str, Any] = debate.config_json or {}
    model = _verdict_model(debate)
    if _service_slot(model, api_key):
        verdict, moderation, usage = structure_verdict(
            conf, verdict_text, model=model, api_key=api_key
        )
    else:  # no slot: the regex verdict, and the stand-alone check tries once more
        verdict, moderation, usage = (
            fallback_verdict(verdict_text, debaters_from_config(conf)),
            None,
            {},
        )
    debate.verdict_json = verdict
    if moderation is not None:
        apply_check(debate, moderation)
    _add_service_cost(debate, usage)
    db.commit()
    publish_event(
        str(debate.id), "verdict_ready", {"debate_id": str(debate.id), "verdict": verdict}
    )


def _add_service_cost(debate: Debate, usage: dict[str, Any] | None) -> None:
    """Verdict structuring and the gallery check: our cost, never the owner's (`service_cost`
    stays out of `cost`, which `credits.debate_charge_usd` bills)."""
    cost = float((usage or {}).get("cost") or 0.0)
    if cost:
        totals = debate.totals_json or {}
        totals_cost = round(float(totals.get("service_cost") or 0.0) + cost, 6)
        debate.totals_json = {**totals, "service_cost": totals_cost}


def _ensure_moderated(db: Session, debate: Debate, api_key: str | None) -> None:
    """Run the stand-alone gallery check when the verdict step gave no answer. Never raises."""
    if debate.moderation_status != "none":
        return
    try:
        verdict = next((t for t in debate.turns if t.turn_type == "verdict"), None)
        model = _verdict_model(debate)
        if _service_slot(model, api_key):
            result, usage = check_debate(
                debate.config_json or {},
                model=model,
                api_key=api_key,
                verdict_text=verdict.text if verdict and not verdict.error else "",
            )
        else:  # fails closed: a human looks at it
            result, usage = fallback_result(), {}
        apply_check(debate, result)
        _add_service_cost(debate, usage)
        db.commit()
    except Exception:
        logger.exception("Moderation check failed for debate %s", debate.id)
        db.rollback()


def _auto_publish(db: Session, debate: Debate) -> None:
    """Publish a finished debate when its owner asked for the gallery (the caller commits)."""
    try:
        if should_auto_publish(debate) and publish_sync(db, debate):
            logger.info("Debate %s published to the gallery", debate.id)
            indexnow.announce_sync(indexnow.debate_refs(debate))
        elif debate.moderation_status == "flagged":
            reason = (debate.moderation_json or {}).get("reason")
            logger.info("Debate %s waits for review: %s", debate.id, reason)
    except Exception:
        logger.exception("Auto-publish failed for debate %s", debate.id)


def _has_tts_key(debate_id: str) -> bool:
    try:
        return bool(get_sync_redis().exists(tts_key_key(debate_id)))
    except Exception:
        logger.warning("Failed to check the TTS key for debate %s", debate_id)
        return False


def _drop_tts_key(debate_id: str) -> None:
    try:
        get_sync_redis().delete(tts_key_key(debate_id))
    except Exception:
        logger.warning("Failed to delete the TTS key for debate %s", debate_id)


def _auto_media(db: Session, debate: Debate) -> None:
    """Queue the audio build when the wizard asked for audio/video outputs.

    A user ElevenLabs key sent with the debate is already in Redis (`tts_key_key`); the media
    job picks it up from there and the voices are not charged to credits."""
    conf: dict[str, Any] = debate.config_json or {}
    plan: dict[str, Any] = conf.get("media_plan") or {}
    outputs = plan.get("outputs") or []
    provider = str(plan.get("provider") or "edge")
    if "audio" not in outputs or provider != "elevenlabs":
        _drop_tts_key(str(debate.id))
        if "audio" not in outputs:
            return
    voices: dict[str, str] = dict(plan.get("voices") or {})
    own_tts_key = provider == "elevenlabs" and _has_tts_key(str(debate.id))
    fmt = format_of(conf)
    if provider == "elevenlabs" and not own_tts_key and not system_key_status()[0]:
        if fmt.voices == "elevenlabs":
            # No Edge fallback for a format voiced with premium voices only: the owner builds the
            # audio from the debate page once the key works again.
            logger.warning("Premium voices unavailable for %s (%s): no audio", debate.id, fmt.id)
            return
        logger.warning("Premium voices unavailable for %s, falling back to Edge", debate.id)
        provider, voices = "edge", {}  # voice ids are provider-specific
    state = dict(debate.media_json or {})
    state.update(
        {
            "options": {
                "provider": provider,
                "model_id": str(plan.get("model_id") or settings.TTS_DEFAULT_MODEL_ID),
                "voices": voices,
                "visuals": fmt.visuals and bool(plan.get("visuals", True)),
                "images": str(plan.get("images") or "off") if fmt.visuals else "off",
                "flows": dict(plan.get("flows") or {}),
            },
            "force": False,
            "own_tts_key": own_tts_key,
            "prices": debate_prices(debate).as_dict(),  # what the run was quoted with
            "auto": True,
            "free": False,
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
    db.commit()
    try:
        queue_manager.enqueue_media_build(str(debate.id))
    except Exception:
        logger.exception("Failed to queue the audio build for debate %s", debate.id)
        debate.media_status = "error"
        debate.media_json = {**state, "error": "Job queue unavailable"}
        db.commit()


# --- jobs ------------------------------------------------------------------


@beating(debate_beat_key)
@usage_log.attributed
def start_debate_job(debate_id: str, from_seq: int = 0) -> None:
    """Start a queued run: a new debate from its first turn, a resumed one from `from_seq`."""
    with get_session() as db:
        debate = db.get(Debate, uuid.UUID(debate_id))
        if not debate:
            logger.warning("Debate %s not found", debate_id)
            return
        if debate.status != "queued":
            logger.info("Debate %s is %s, not starting", debate_id, debate.status)
            return

        debate.status = "running"
        debate.started_at = debate.started_at or utcnow()
        db.commit()
        publish_event(debate_id, "debate_started", {"debate_id": debate_id, "status": "running"})
        queue_manager.enqueue_turn(debate_id, from_seq)


@beating(debate_beat_key)
@usage_log.attributed
def process_turn_job(debate_id: str, seq_index: int) -> None:
    with get_session() as db:
        debate = db.get(Debate, uuid.UUID(debate_id))
        if not debate:
            return
        if debate.status == "stopped":
            _finalize_stopped(db, debate)
            return
        if debate.status != "running":
            return

        try:
            conf: dict[str, Any] = debate.config_json or {}
            participants: list[dict[str, Any]] = conf.get("participants", [])
            fmt = format_of(conf)
            schedule = fmt.schedule(conf)

            if seq_index >= len(schedule):
                queue_manager.enqueue_verdict(debate_id, seq_index)
                return

            turn: ScheduledTurn = schedule[seq_index]
            speaker = participants[turn.speaker_index]
            speaker_name = speaker.get("display_name") or (
                "Moderator" if turn.is_moderator else f"Debater {turn.speaker_index}"
            )
            history = _history(db, debate.id)
            speaker_id = f"participant_{turn.speaker_index}"
            claims = (
                visual_claims(_turns(db, debate.id), speaker_id, speaker_name)
                if visuals_enabled(conf) and not turn.is_moderator
                else []
            )
            if turn.is_moderator:
                messages = fmt.host_messages(conf, speaker, turn, history)
            else:
                messages = fmt.debater_messages(
                    conf, speaker, turn, history, visual_claims=claims_prompt(claims)
                )

            started = {
                "seq_index": seq_index,
                "speaker_name": speaker_name,
                "speaker_role": speaker_role_for(turn.turn_type),
                "turn_type": turn.turn_type,
                "round_id": turn.round_id,
                "round_label": fmt.round_label(turn.round_id, turn.turn_type),
            }
            publish_event(debate_id, "turn_started", started)

            api_key = _provider_key(debate_id)
            deadline = time.monotonic() + settings.LLM_TURN_TIMEOUT
            result, model_id = _generate_as(
                debate,
                turn.speaker_index,
                speaker,
                _announcing(
                    debate_id,
                    started,
                    lambda model: _generate(
                        debate_id, seq_index, speaker_name, model, messages, api_key, deadline
                    ),
                ),
                deadline,
            )
            visuals: dict[str, Any] = {}
            if has_markers(result.text):
                # [visual: …] / [dispute N: …] are for the studio, not the transcript or voice.
                result.text, hints, marks = extract_markers(result.text)
                visuals = initial_visuals(hints, resolve_disputes(marks, claims))
            if not result.error and not turn.is_moderator:
                result.text = fmt.finish_text(conf, turn, result.text)
            saved = _save_turn(
                db,
                debate,
                seq_index=seq_index,
                round_id=turn.round_id,
                turn_type=turn.turn_type,
                speaker_id=speaker_id,
                speaker_name=speaker_name,
                model_id=model_id,
                result=result,
                visuals=visuals,
            )

            if result.stopped or _stop_requested(debate_id):
                _finalize_stopped(db, debate)
                return
            if result.error:
                # The others would argue against a silent speaker: stop, the owner may resume.
                fail_debate(db, debate, _failure(speaker_name, model_id, result.error))
                return
            design_turn(db, debate, saved, api_key=api_key)
            if _stop_requested(debate_id):
                _finalize_stopped(db, debate)
                return
            queue_manager.enqueue_turn(debate_id, seq_index + 1)

        except Exception as e:
            logger.exception("Turn %s of debate %s crashed", seq_index, debate_id)
            db.rollback()
            fail_debate(db, debate, f"Turn {seq_index} failed: {e}")


@beating(debate_beat_key)
@usage_log.attributed
def conduct_verdict_job(debate_id: str, seq_index: int) -> None:
    with get_session() as db:
        debate = db.get(Debate, uuid.UUID(debate_id))
        if not debate:
            return
        if debate.status == "stopped":
            _finalize_stopped(db, debate)
            return
        if debate.status != "running":
            return

        try:
            conf: dict[str, Any] = debate.config_json or {}
            participants: list[dict[str, Any]] = conf.get("participants", [])
            fmt = format_of(conf)
            moderator_index = next(
                (i for i, p in enumerate(participants) if p.get("role") == "moderator"), -1
            )
            moderator = participants[moderator_index] if moderator_index >= 0 else {}
            api_key = _provider_key(debate_id)

            started = {
                "seq_index": seq_index,
                "speaker_name": VERDICT_SPEAKER_NAME,
                "speaker_role": "moderator",
                "turn_type": "verdict",
                "round_id": "verdict",
                "round_label": fmt.round_label("verdict", "verdict"),
            }
            publish_event(debate_id, "turn_started", started)
            evidence = verdict_evidence(_turns(db, debate.id))
            messages = fmt.verdict_messages(conf, _history(db, debate.id), evidence)
            deadline = time.monotonic() + settings.LLM_TURN_TIMEOUT
            result, model_id = _generate_as(
                debate,
                moderator_index,
                moderator,
                _announcing(
                    debate_id,
                    started,
                    lambda model: _generate(
                        debate_id,
                        seq_index,
                        VERDICT_SPEAKER_NAME,
                        model,
                        messages,
                        api_key,
                        deadline,
                        purpose="verdict",
                    ),
                ),
                deadline,
            )
            saved = _save_turn(
                db,
                debate,
                seq_index=seq_index,
                round_id="verdict",
                turn_type="verdict",
                speaker_id="judge",
                speaker_name=VERDICT_SPEAKER_NAME,
                model_id=model_id,
                result=result,
            )
            if result.stopped or _stop_requested(debate_id):
                _finalize_stopped(db, debate)
                return
            if result.error:
                fail_debate(db, debate, _failure("The judge", model_id, result.error))
                return
            try:
                _store_verdict(db, debate, result.text, api_key)
            except Exception:
                logger.exception("Verdict structuring crashed for debate %s", debate_id)
                db.rollback()
            design_turn(db, debate, saved, api_key=api_key)
            queue_manager.enqueue_finish(debate_id)
        except Exception as e:
            logger.exception("Verdict for debate %s crashed", debate_id)
            db.rollback()
            fail_debate(db, debate, f"Verdict failed: {e}")


@beating(debate_beat_key)
@usage_log.attributed
def finish_debate_job(debate_id: str) -> None:
    with get_session() as db:
        debate = db.get(Debate, uuid.UUID(debate_id))
        if not debate:
            return
        if debate.status == "stopped":
            _finalize_stopped(db, debate)
            return
        if debate.status != "running":
            return

        # Before "completed" so nobody sees a finished debate that is not checked yet, and
        # before the totals so a stand-alone check is part of the charged analysis cost.
        _ensure_moderated(db, debate, _provider_key(debate_id))
        debate.status = "completed"
        debate.ended_at = utcnow()
        debate.totals_json = _compute_totals(db, debate)
        _auto_publish(db, debate)
        db.commit()
        _charge(db, debate)
        _cleanup_keys(debate_id, keep_tts_key=True)
        publish_event(
            debate_id,
            "debate_completed",
            {"debate_id": debate_id, "status": "completed", "totals": debate.totals_json},
        )
        _auto_media(db, debate)
