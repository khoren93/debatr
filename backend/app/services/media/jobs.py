"""RQ job: voice every turn of a finished debate, mix the full track and write timeline.json.

Runs on the `media` queue. Per-turn audio is cached by a content hash, so re-running the
job (new voices for one speaker, a retry after an error) only re-synthesizes what changed.
"""

import hashlib
import json
import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.redis import get_sync_redis, tts_key_key
from app.core.sync_db import get_sync_session
from app.models.models import Debate, Turn
from app.schemas.media import MediaOptions
from app.schemas.timeline import (
    Timeline,
    TimelineHighlight,
    TimelineSegment,
    TimelineSpeaker,
    TimelineStats,
    TimelineVerdict,
    TimelineWord,
)
from app.services.credits import charge_media_sync
from app.services.media import ffmpeg
from app.services.media.alignment import WordTiming, clamp_words, merge_chunks
from app.services.media.highlights import (
    build_highlights_messages,
    extract_winner,
    fallback_highlights,
    match_speaker,
    parse_highlights,
    snap_highlight,
)
from app.services.media.languages import language_code
from app.services.media.llm import complete, extract_json
from app.services.media.paths import MediaPaths
from app.services.media.script import clean_markdown, even_words, split_for_tts, strip_audio_tags
from app.services.media.state import set_media_state
from app.services.media.timeline import build_speakers
from app.services.media.tts import SpeakerRef, SynthRequest, TTSProvider, get_provider
from app.services.media.tts.elevenlabs import TAG_MODELS, estimate_usd
from app.services.scheduler import speaker_role_for

logger = logging.getLogger(__name__)

LEVELS_HZ = 20


@dataclass(frozen=True)
class TurnTask:
    seq_index: int
    speaker: TimelineSpeaker
    round_id: str
    turn_type: str
    text: str  # cleaned, may keep [audio tags]
    previous_text: str | None
    next_text: str | None
    voice_id: str


@dataclass
class TurnAudio:
    seq_index: int
    wav: Path
    duration_ms: int
    words: list[TimelineWord]
    levels: list[float]
    char_cost: int
    note: str | None
    cached: bool


def _turn_hash(provider: str, model_id: str, voice_id: str, text: str) -> str:
    payload = "|".join([provider, model_id, voice_id, text, str(settings.MEDIA_LOUDNESS_LUFS)])
    return hashlib.sha256(payload.encode()).hexdigest()


def _user_tts_key(debate_id: str) -> str | None:
    try:
        value = get_sync_redis().get(tts_key_key(debate_id))
    except Exception:
        logger.warning("Failed to read TTS key for debate %s", debate_id)
        return None
    if value is None:
        return None
    return value.decode() if isinstance(value, bytes) else str(value)


def _is_usable(turn: Turn) -> bool:
    text = (turn.text or "").strip()
    return bool(text) and not turn.error and not text.startswith("[Error")


def _speaker_for(turn: Turn, speakers: dict[str, TimelineSpeaker]) -> TimelineSpeaker:
    if turn.speaker_id in speakers:
        return speakers[turn.speaker_id]
    if turn.turn_type == "verdict":
        return speakers["judge"]
    role = speaker_role_for(turn.turn_type)
    by_name = next((s for s in speakers.values() if s.name == turn.speaker_name), None)
    if by_name:
        return by_name
    return (
        next(s for s in speakers.values() if s.role == role)
        if any(s.role == role for s in speakers.values())
        else next(iter(speakers.values()))
    )


def _synthesize_turn(
    provider: TTSProvider,
    paths: MediaPaths,
    task: TurnTask,
    options: MediaOptions,
    force: bool,
    code: str,
) -> TurnAudio:
    wav = paths.turn_wav(task.seq_index)
    meta_path = paths.turn_meta(task.seq_index)
    digest = _turn_hash(options.provider, options.model_id, task.voice_id, task.text)

    if not force and wav.exists() and meta_path.exists():
        meta = json.loads(meta_path.read_text())
        if meta.get("hash") == digest:
            return TurnAudio(
                seq_index=task.seq_index,
                wav=wav,
                duration_ms=int(meta["duration_ms"]),
                words=[TimelineWord.model_validate(w) for w in meta.get("words", [])],
                levels=[float(v) for v in meta.get("levels", [])],
                char_cost=int(meta.get("char_cost") or 0),
                note=meta.get("note"),
                cached=True,
            )

    chunks = split_for_tts(task.text, settings.TTS_MAX_CHARS_PER_REQUEST) or [task.text]
    parts: list[tuple[list[WordTiming], int]] = []
    chunk_wavs: list[Path] = []
    char_cost = 0
    notes: list[str] = []
    for i, chunk in enumerate(chunks):
        previous = chunks[i - 1] if i > 0 else task.previous_text
        following = chunks[i + 1] if i + 1 < len(chunks) else task.next_text
        result = provider.synthesize(
            SynthRequest(
                text=chunk,
                voice_id=task.voice_id,
                model_id=options.model_id,
                language_code=code,
                previous_text=previous,
                next_text=following,
            )
        )
        raw = paths.turn_raw(task.seq_index, i, result.ext)
        raw.write_bytes(result.audio)
        chunk_wav = paths.turn_chunk_wav(task.seq_index, i)
        ffmpeg.normalize_turn(raw, chunk_wav)
        raw.unlink(missing_ok=True)
        duration = ffmpeg.probe_duration_ms(chunk_wav)
        words = result.words or [
            WordTiming(str(w["w"]), int(w["s"]), int(w["e"])) for w in even_words(chunk, duration)
        ]
        parts.append((clamp_words(words, duration), duration))
        chunk_wavs.append(chunk_wav)
        char_cost += result.char_cost
        if result.note and result.note not in notes:
            notes.append(result.note)

    if len(chunk_wavs) == 1:
        chunk_wavs[0].replace(wav)
    else:
        ffmpeg.concat_wavs(chunk_wavs, wav)
        for cw in chunk_wavs:
            cw.unlink(missing_ok=True)

    duration_ms = ffmpeg.probe_duration_ms(wav)
    merged = clamp_words(merge_chunks(parts), duration_ms)
    words_out = [TimelineWord(w=w.w, s=w.s_ms, e=w.e_ms) for w in merged]
    levels = ffmpeg.envelope(wav, window_ms=1000 // LEVELS_HZ)
    note = "; ".join(notes) or None
    meta_path.write_text(
        json.dumps(
            {
                "hash": digest,
                "duration_ms": duration_ms,
                "words": [w.model_dump() for w in words_out],
                "levels": levels,
                "char_cost": char_cost,
                "note": note,
                "chunks": len(chunks),
            }
        )
    )
    return TurnAudio(
        task.seq_index, wav, duration_ms, words_out, levels, char_cost, note, cached=False
    )


def _pick_highlights(
    *,
    topic: str,
    language: str,
    segments: list[TimelineSegment],
    speakers: list[TimelineSpeaker],
    total_ms: int,
) -> tuple[list[TimelineHighlight], str | None]:
    """LLM-selected moments with a deterministic fallback. Returns (highlights, winner_name)."""
    if not settings.OPENROUTER_API_KEY:
        return fallback_highlights(segments, total_ms), None
    try:
        messages = build_highlights_messages(
            topic=topic, language=language, segments=segments, speakers=speakers
        )
        text, _usage = complete(settings.MEDIA_HIGHLIGHTS_MODEL, messages, max_tokens=900)
        winner_name, picks = parse_highlights(extract_json(text))
        highlights = [
            hl
            for i, pick in enumerate(picks)
            if (hl := snap_highlight(segments, pick, i, total_ms)) is not None
        ]
        for i, hl in enumerate(highlights):
            hl.index = i
        if highlights:
            return highlights, winner_name
        return fallback_highlights(segments, total_ms), winner_name
    except Exception as e:
        logger.warning("Highlight selection failed, using fallback: %s", e)
        return fallback_highlights(segments, total_ms), None


def _build(db: Session, debate: Debate, options: MediaOptions, force: bool) -> int:
    """Voice, mix and write the timeline. Returns the characters actually synthesized
    (cached turns excluded), which is what premium voices are billed on."""
    debate_id = str(debate.id)
    conf: dict[str, Any] = debate.config_json or {}
    participants: list[dict[str, Any]] = conf.get("participants", [])
    code = language_code(conf.get("language"))
    language = str(conf.get("language") or "English")
    paths = MediaPaths(debate_id)
    paths.turns_dir.mkdir(parents=True, exist_ok=True)

    turns = [
        t
        for t in db.scalars(
            select(Turn).where(Turn.debate_id == debate.id).order_by(Turn.seq_index)
        ).all()
        if _is_usable(t)
    ]
    if not turns:
        raise RuntimeError("The debate has no spoken turns")

    moderator = next((p for p in participants if p.get("role") == "moderator"), None)
    judge_model = str((moderator or {}).get("model_id") or settings.DEFAULT_MODEL_ID)
    speakers = build_speakers(participants, code, judge_model)
    speakers_by_id = {s.id: s for s in speakers}

    user_key = _user_tts_key(debate_id)
    own_key = bool((debate.media_json or {}).get("own_tts_key"))
    # Never fall back to the paid system key for a build that was promised as "own key".
    if options.provider == "elevenlabs" and own_key and not user_key:
        raise RuntimeError("Your ElevenLabs key expired, generate the audio again with it")
    provider = get_provider(options.provider, api_key=user_key)
    if not provider.available():
        raise RuntimeError(f"TTS provider '{options.provider}' is not configured")

    # Fill in voices the client did not choose.
    refs: list[SpeakerRef] = []
    debater_index = 0
    for s in speakers:
        refs.append(SpeakerRef(s.id, s.role, debater_index if s.role == "debater" else 0))
        if s.role == "debater":
            debater_index += 1
    if any(s.id not in options.voices for s in speakers):
        defaults = provider.default_voices(code, refs)
        options = options.model_copy(update={"voices": {**defaults, **options.voices}})
    for s in speakers:
        s.voice_id = options.voices.get(s.id)

    allow_tags = provider.name == "elevenlabs" and options.model_id in TAG_MODELS
    cleaned: list[tuple[Turn, TimelineSpeaker, str]] = []
    for t in turns:
        text = clean_markdown(t.text)
        if not allow_tags:
            text = strip_audio_tags(text)
        if text:
            cleaned.append((t, _speaker_for(t, speakers_by_id), text))
    tasks: list[TurnTask] = []
    for i, (t, speaker, text) in enumerate(cleaned):
        voice_id = options.voices.get(speaker.id)
        if not voice_id:
            raise RuntimeError(f"No voice selected for {speaker.name}")
        tasks.append(
            TurnTask(
                seq_index=t.seq_index,
                speaker=speaker,
                round_id=t.round_id,
                turn_type=t.turn_type,
                text=text,
                previous_text=cleaned[i - 1][2] if i > 0 else None,
                next_text=cleaned[i + 1][2] if i + 1 < len(cleaned) else None,
                voice_id=voice_id,
            )
        )

    total = len(tasks)
    set_media_state(
        db,
        debate,
        step="tts",
        current=0,
        total=total,
        message=f"Synthesizing {total} turns with {provider.name}…",
        extra={"options": options.model_dump()},
    )
    results: dict[int, TurnAudio] = {}
    done = 0
    tts_started = time.monotonic()
    with ThreadPoolExecutor(max_workers=max(1, settings.TTS_CONCURRENCY)) as pool:
        futures = [
            pool.submit(_synthesize_turn, provider, paths, task, options, force, code)
            for task in tasks
        ]
        try:
            for future in as_completed(futures):
                audio = future.result()
                results[audio.seq_index] = audio
                done += 1
                set_media_state(
                    db,
                    debate,
                    step="tts",
                    current=done,
                    total=total,
                    message=f"Voiced {done} of {total} turns",
                )
        except BaseException:
            pool.shutdown(wait=False, cancel_futures=True)
            raise

    ordered = [results[task.seq_index] for task in tasks]
    tts_ms = round((time.monotonic() - tts_started) * 1000)
    set_media_state(db, debate, step="mix", message="Mixing the full track…")
    ffmpeg.concat_with_gaps(
        [a.wav for a in ordered], settings.MEDIA_GAP_MS, paths.full_wav, paths.full_mp3
    )
    offsets = ffmpeg.concat_offsets([a.duration_ms for a in ordered], settings.MEDIA_GAP_MS)
    total_ms = ffmpeg.probe_duration_ms(paths.full_wav)

    segments: list[TimelineSegment] = []
    for task, audio, offset in zip(tasks, ordered, offsets, strict=True):
        segments.append(
            TimelineSegment(
                seq_index=task.seq_index,
                speaker_id=task.speaker.id,
                speaker_name=task.speaker.name,
                round_id=task.round_id,
                turn_type=task.turn_type,
                start_ms=offset,
                end_ms=offset + audio.duration_ms,
                audio=paths.rel(audio.wav),
                text=strip_audio_tags(task.text),
                words=audio.words,
                levels=audio.levels,
                levels_hz=LEVELS_HZ,
                note=audio.note,
            )
        )

    set_media_state(db, debate, step="highlights", message="Picking highlights for shorts…")
    highlights, winner_name = _pick_highlights(
        topic=str(conf.get("topic") or ""),
        language=language,
        segments=segments,
        speakers=speakers,
        total_ms=total_ms,
    )
    verdict_turn = next((t for t in turns if t.turn_type == "verdict"), None)
    verdict: TimelineVerdict | None = None
    if verdict_turn is not None:
        # The structured verdict (worker, see services.verdict) is the most reliable source.
        structured_id = (debate.verdict_json or {}).get("winner_id")
        winner = (
            speakers_by_id.get(str(structured_id))
            if structured_id
            else extract_winner(verdict_turn.text, speakers) or match_speaker(winner_name, speakers)
        )
        verdict = TimelineVerdict(
            seq_index=verdict_turn.seq_index,
            winner_id=winner.id if winner else None,
            winner_name=winner.name if winner else None,
        )

    chars = sum(len(strip_audio_tags(task.text)) for task in tasks)
    char_cost = sum(a.char_cost for a in ordered if not a.cached)
    stats = TimelineStats(
        chars=chars,
        tts_ms=tts_ms,
        estimated_usd=estimate_usd(options.model_id, char_cost)
        if provider.name == "elevenlabs"
        else None,
        cached_turns=sum(1 for a in ordered if a.cached),
    )
    timeline = Timeline(
        debate_id=debate_id,
        title=str(debate.title or conf.get("topic") or "Debate"),
        topic=str(conf.get("topic") or ""),
        language=language,
        language_code=code,
        created_at=debate.created_at,
        provider=provider.name,
        model_id=options.model_id,
        speakers=speakers,
        segments=segments,
        gap_ms=settings.MEDIA_GAP_MS,
        total_ms=total_ms,
        verdict=verdict,
        highlights=highlights,
        stats=stats,
    )
    paths.timeline.write_text(timeline.model_dump_json(indent=2))

    set_media_state(
        db,
        debate,
        status="ready",
        step="done",
        current=total,
        total=total,
        message="Ready",
        finished=True,
        extra={
            "force": False,
            "stats": {**stats.model_dump(), "total_ms": total_ms},
            "assets": {"timeline": "timeline.json", "full_mp3": "full.mp3", "full_wav": "full.wav"},
        },
    )
    return char_cost


def build_media_job(debate_id: str) -> None:
    with get_sync_session() as db:
        debate = db.get(Debate, uuid.UUID(debate_id))
        if not debate:
            logger.warning("Media build: debate %s not found", debate_id)
            return
        if debate.media_status != "queued":
            logger.info("Media build: debate %s is %s, skipping", debate_id, debate.media_status)
            return
        state = dict(debate.media_json or {})
        options = MediaOptions.model_validate(state.get("options") or {})
        force = bool(state.get("force"))
        set_media_state(
            db,
            debate,
            status="running",
            step="prepare",
            message="Preparing the script…",
            started=True,
        )
        try:
            billed_chars = _build(db, debate, options, force)
            try:
                tx = charge_media_sync(
                    db,
                    debate,
                    chars=billed_chars,
                    provider=options.provider,
                    own_key=bool(state.get("own_tts_key")),
                    build_ref=str((debate.media_json or {}).get("finished_at") or int(time.time())),
                )
                if tx is not None:
                    logger.info("Charged %s credits for voices of %s", -tx.amount_usd, debate_id)
            except Exception:
                logger.exception("Failed to charge credits for media of %s", debate_id)
                db.rollback()
        except Exception as e:
            logger.exception("Media build for debate %s failed", debate_id)
            db.rollback()
            debate = db.get(Debate, uuid.UUID(debate_id))
            if debate:
                set_media_state(
                    db,
                    debate,
                    status="error",
                    step="error",
                    message="Build failed",
                    error=str(e)[:500],
                    finished=True,
                )
