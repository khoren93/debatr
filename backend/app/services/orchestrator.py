"""RQ jobs that drive a debate: start -> turn* -> verdict -> finish.

Runs in the worker process only. Uses a blocking SQLAlchemy engine because RQ
jobs are synchronous; LLM streaming happens inside a short-lived asyncio loop.
When a debate reaches a terminal state the owner's credits are charged and, if the
configuration asks for it, the audio build is queued automatically. A completed debate is
checked for the gallery and published when its owner asked for that (`services/moderation`).
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.redis import get_sync_redis, provider_key_key, stop_flag_key, tts_key_key
from app.core.sync_db import get_sync_session
from app.models.models import Debate, Turn, utcnow
from app.services import queue_manager
from app.services.credits import charge_debate_sync
from app.services.events import publish_event
from app.services.media.tts.elevenlabs import system_key_status
from app.services.moderation import apply_check, check_debate, publish_sync, should_auto_publish
from app.services.openrouter_client import OpenRouterClient, OpenRouterError
from app.services.prompt_builder import (
    build_debater_messages,
    build_moderator_messages,
    build_verdict_messages,
)
from app.services.scheduler import ScheduledTurn, build_schedule, speaker_role_for
from app.services.verdict import structure_verdict

logger = logging.getLogger(__name__)

VERDICT_SPEAKER_NAME = "⚖️ Verdict"
STOP_CHECK_EVERY_N_CHUNKS = 10

get_session = get_sync_session


# --- helpers ---------------------------------------------------------------


@dataclass
class GenerationResult:
    text: str = ""
    usage: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    stopped: bool = False


def _normalize_usage(raw: dict[str, Any] | None) -> dict[str, Any]:
    if not raw:
        return {}
    return {
        "prompt_tokens": int(raw.get("prompt_tokens") or 0),
        "completion_tokens": int(raw.get("completion_tokens") or 0),
        "total_tokens": int(raw.get("total_tokens") or 0),
        "cost": float(raw.get("cost") or 0.0),
    }


def _serialize_turn(turn: Turn) -> dict[str, Any]:
    return {
        "seq_index": turn.seq_index,
        "round_id": turn.round_id,
        "turn_type": turn.turn_type,
        "speaker_role": speaker_role_for(turn.turn_type),
        "speaker_id": turn.speaker_id,
        "speaker_name": turn.speaker_name,
        "text": turn.text,
        "error": turn.error,
        "model_used": turn.model_used,
        "usage": turn.usage_json or {},
        "created_at": turn.created_at.isoformat() if turn.created_at else None,
    }


def _history(db: Session, debate_id: uuid.UUID) -> list[dict[str, Any]]:
    turns = db.scalars(
        select(Turn).where(Turn.debate_id == debate_id).order_by(Turn.seq_index)
    ).all()
    return [
        {"speaker_name": t.speaker_name, "text": t.text, "turn_type": t.turn_type}
        for t in turns
        if t.text and t.text.strip()
    ]


def _compute_totals(db: Session, debate: Debate) -> dict[str, Any]:
    """Token/cost totals over all turns plus the (cheap) verdict analysis call."""
    turns = db.scalars(select(Turn).where(Turn.debate_id == debate.id)).all()
    analysis_cost = float((debate.totals_json or {}).get("analysis_cost") or 0.0)
    totals: dict[str, Any] = {
        "tokens_in": 0,
        "tokens_out": 0,
        "cost": analysis_cost,
        "turns_count": len(turns),
        "analysis_cost": analysis_cost,
    }
    for t in turns:
        usage = t.usage_json or {}
        totals["tokens_in"] += int(usage.get("prompt_tokens") or 0)
        totals["tokens_out"] += int(usage.get("completion_tokens") or 0)
        totals["cost"] += float(usage.get("cost") or 0.0)
    totals["cost"] = round(totals["cost"], 6)
    return totals


def _charge(db: Session, debate: Debate) -> None:
    """Charge the owner's credits for a finished run (never lets a billing error kill the job)."""
    try:
        tx = charge_debate_sync(db, debate)
        if tx is not None:
            logger.info("Charged %s credits for debate %s", -tx.amount_usd, debate.id)
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


def _fail_debate(db: Session, debate: Debate, message: str) -> None:
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
) -> GenerationResult:
    """Stream one LLM response, forwarding deltas to subscribers."""

    async def run() -> GenerationResult:
        client = OpenRouterClient()
        result = GenerationResult()
        chunks = 0
        try:
            async for chunk in client.stream_chat_completion(model_id, messages, api_key=api_key):
                if chunk.usage:
                    result.usage = _normalize_usage(chunk.usage)
                if not chunk.delta:
                    continue
                result.text += chunk.delta
                publish_event(
                    debate_id,
                    "turn_delta",
                    {"seq_index": seq_index, "delta": chunk.delta, "speaker_name": speaker_name},
                )
                chunks += 1
                if chunks % STOP_CHECK_EVERY_N_CHUNKS == 0 and _stop_requested(debate_id):
                    result.stopped = True
                    break
        except OpenRouterError as e:
            result.error = str(e)
        except Exception as e:
            logger.exception("Unexpected generation error for debate %s", debate_id)
            result.error = f"Unexpected error: {e}"
        return result

    return asyncio.run(run())


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
        usage_json=result.usage,
    )
    db.add(turn)
    db.commit()
    db.refresh(turn)
    payload = _serialize_turn(turn)
    publish_event(str(debate.id), "turn_error" if result.error else "turn_completed", payload)
    if result.error:
        logger.warning("Turn %s of debate %s failed: %s", seq_index, debate.id, result.error)
    return turn


def _store_verdict(db: Session, debate: Debate, verdict_text: str, api_key: str | None) -> None:
    """Structure the judge's text (winner, headline, feedback) for the UI and the video."""
    conf: dict[str, Any] = debate.config_json or {}
    verdict, moderation, usage = structure_verdict(
        conf, verdict_text, model=settings.MEDIA_HIGHLIGHTS_MODEL, api_key=api_key
    )
    debate.verdict_json = verdict
    if moderation is not None:
        apply_check(debate, moderation)
    _add_analysis_cost(debate, usage)
    db.commit()
    publish_event(
        str(debate.id), "verdict_ready", {"debate_id": str(debate.id), "verdict": verdict}
    )


def _add_analysis_cost(debate: Debate, usage: dict[str, Any] | None) -> None:
    cost = float((usage or {}).get("cost") or 0.0)
    if cost:
        totals = debate.totals_json or {}
        totals_cost = float(totals.get("analysis_cost") or 0.0) + cost
        debate.totals_json = {**totals, "analysis_cost": totals_cost}


def _ensure_moderated(db: Session, debate: Debate, api_key: str | None) -> None:
    """Run the stand-alone gallery check when the verdict step gave no answer. Never raises."""
    if debate.moderation_status != "none":
        return
    try:
        verdict = next((t for t in debate.turns if t.turn_type == "verdict"), None)
        result, usage = check_debate(
            debate.config_json or {},
            model=settings.MEDIA_HIGHLIGHTS_MODEL,
            api_key=api_key,
            verdict_text=verdict.text if verdict and not verdict.error else "",
        )
        apply_check(debate, result)
        _add_analysis_cost(debate, usage)
        db.commit()
    except Exception:
        logger.exception("Moderation check failed for debate %s", debate.id)
        db.rollback()


def _auto_publish(db: Session, debate: Debate) -> None:
    """Publish a finished debate when its owner asked for the gallery (the caller commits)."""
    try:
        if should_auto_publish(debate) and publish_sync(db, debate):
            logger.info("Debate %s published to the gallery", debate.id)
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
    if provider == "elevenlabs" and not own_tts_key and not system_key_status()[0]:
        logger.warning("Premium voices unavailable for %s, falling back to Edge", debate.id)
        provider, voices = "edge", {}  # voice ids are provider-specific
    state = dict(debate.media_json or {})
    state.update(
        {
            "options": {
                "provider": provider,
                "model_id": str(plan.get("model_id") or settings.TTS_DEFAULT_MODEL_ID),
                "voices": voices,
            },
            "force": False,
            "own_tts_key": own_tts_key,
            "auto": True,
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


def start_debate_job(debate_id: str) -> None:
    with get_session() as db:
        debate = db.get(Debate, uuid.UUID(debate_id))
        if not debate:
            logger.warning("Debate %s not found", debate_id)
            return
        if debate.status != "queued":
            logger.info("Debate %s is %s, not starting", debate_id, debate.status)
            return

        debate.status = "running"
        debate.started_at = utcnow()
        db.commit()
        publish_event(debate_id, "debate_started", {"debate_id": debate_id, "status": "running"})
        queue_manager.enqueue_turn(debate_id, 0)


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
            schedule = build_schedule(participants, int(conf.get("num_rounds") or 1))

            if seq_index >= len(schedule):
                queue_manager.enqueue_verdict(debate_id, seq_index)
                return

            turn: ScheduledTurn = schedule[seq_index]
            speaker = participants[turn.speaker_index]
            speaker_name = speaker.get("display_name") or (
                "Moderator" if turn.is_moderator else f"Debater {turn.speaker_index}"
            )
            model_id = speaker.get("model_id") or settings.DEFAULT_MODEL_ID
            history = _history(db, debate.id)
            build = build_moderator_messages if turn.is_moderator else build_debater_messages
            messages = build(conf, speaker, turn, history)

            publish_event(
                debate_id,
                "turn_started",
                {
                    "seq_index": seq_index,
                    "speaker_name": speaker_name,
                    "speaker_role": speaker_role_for(turn.turn_type),
                    "turn_type": turn.turn_type,
                    "round_id": turn.round_id,
                },
            )

            result = _generate(
                debate_id, seq_index, speaker_name, model_id, messages, _provider_key(debate_id)
            )
            _save_turn(
                db,
                debate,
                seq_index=seq_index,
                round_id=turn.round_id,
                turn_type=turn.turn_type,
                speaker_id=f"participant_{turn.speaker_index}",
                speaker_name=speaker_name,
                model_id=model_id,
                result=result,
            )

            if result.stopped or _stop_requested(debate_id):
                _finalize_stopped(db, debate)
                return
            queue_manager.enqueue_turn(debate_id, seq_index + 1)

        except Exception as e:
            logger.exception("Turn %s of debate %s crashed", seq_index, debate_id)
            db.rollback()
            _fail_debate(db, debate, f"Turn {seq_index} failed: {e}")


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
            moderator = next((p for p in participants if p.get("role") == "moderator"), None)
            model_id = (moderator or {}).get("model_id") or settings.DEFAULT_MODEL_ID
            api_key = _provider_key(debate_id)

            publish_event(
                debate_id,
                "turn_started",
                {
                    "seq_index": seq_index,
                    "speaker_name": VERDICT_SPEAKER_NAME,
                    "speaker_role": "moderator",
                    "turn_type": "verdict",
                    "round_id": "verdict",
                },
            )
            messages = build_verdict_messages(conf, _history(db, debate.id))
            result = _generate(
                debate_id, seq_index, VERDICT_SPEAKER_NAME, model_id, messages, api_key
            )
            _save_turn(
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
            if not result.error and result.text.strip():
                try:
                    _store_verdict(db, debate, result.text, api_key)
                except Exception:
                    logger.exception("Verdict structuring crashed for debate %s", debate_id)
                    db.rollback()
            queue_manager.enqueue_finish(debate_id)
        except Exception as e:
            logger.exception("Verdict for debate %s crashed", debate_id)
            db.rollback()
            _fail_debate(db, debate, f"Verdict failed: {e}")


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
