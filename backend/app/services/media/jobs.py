"""RQ job: voice every turn of a finished debate, mix the full track and write timeline.json.

Runs on the `media` queue. Per-turn audio is cached by a content hash, so re-running the
job (new voices for one speaker, a retry after an error) only re-synthesizes what changed.
"""

import hashlib
import json
import logging
import time
import uuid
from concurrent.futures import as_completed
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.redis import get_sync_redis, media_beat_key, tts_key_key
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
from app.schemas.visuals import ImageScene, SketchScene, TimelineVisual
from app.services import free_quota, runtime_settings
from app.services.credits import charge_images_sync, charge_media_sync, has_balance, prices_of
from app.services.formats import format_of
from app.services.free_router import resolved_participants
from app.services.heartbeat import beating
from app.services.media import ffmpeg
from app.services.media.alignment import WordTiming, clamp_words, merge_chunks
from app.services.media.highlights import (
    HighlightPick,
    build_highlights_messages,
    extract_winner,
    fallback_highlights,
    match_speaker,
    parse_highlights,
    snap_highlight,
)
from app.services.media.images import ImageStudio
from app.services.media.languages import language_code
from app.services.media.llm import complete, extract_json
from app.services.media.paths import MediaPaths
from app.services.media.script import clean_markdown, even_words, split_for_tts, strip_audio_tags
from app.services.media.sketch import illustrate
from app.services.media.state import free_build, set_media_state
from app.services.media.timeline import build_speakers
from app.services.media.tts import SpeakerRef, SynthRequest, TTSProvider, get_provider
from app.services.media.tts.elevenlabs import TAG_MODELS, estimate_usd
from app.services.media.visuals import (
    PROMPT_VERSION,
    TurnBrief,
    align_scenes,
    build_briefs,
    diversify,
    make_room,
    scoreboard_visual,
)
from app.services.scheduler import speaker_role_for
from app.services.studio import (
    budget_of,
    check_of,
    disputes_by_key,
    hints_of,
    plan_scenes,
    text_hash,
    usable_plan,
)
from app.services.usage import ContextThreadPool, KeyOwner, attributed
from app.services.usage import record as record_usage

logger = logging.getLogger(__name__)

LEVELS_HZ = 20
# The host's model picks the Short moments. Reasoning models think within `max_tokens`, so it
# leaves room beyond the ~300 tokens of the answer; a free host waits this long for a slot.
HIGHLIGHTS_MAX_TOKENS = 4000
HIGHLIGHTS_SLOT_WAIT = 90.0


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


def _book_tts(
    options: MediaOptions,
    task: TurnTask,
    key: KeyOwner,
    *,
    chars: int,
    started: float,
    error: Exception | None = None,
) -> None:
    """One voiced turn in `provider_usage`. ElevenLabs bills characters on a subscription, so
    the cost is an estimate from its price table; Edge voices are free."""
    eleven = options.provider == "elevenlabs"
    record_usage(
        "tts",
        provider=options.provider,
        model=options.model_id if eleven else "edge-tts",
        key=key,
        chars=chars,
        cost_usd=(estimate_usd(options.model_id, chars) or 0.0) if eleven else 0.0,
        ok=error is None,
        error_kind="other" if error is not None else None,
        duration_ms=int((time.monotonic() - started) * 1000),
        meta={"seq_index": task.seq_index, "estimated": eleven}
        | ({"error": str(error)[:300]} if error is not None else {}),
    )


def _synthesize_turn(
    provider: TTSProvider,
    paths: MediaPaths,
    task: TurnTask,
    options: MediaOptions,
    force: bool,
    code: str,
    key: KeyOwner = "system",
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
    started = time.monotonic()
    try:
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
                WordTiming(str(w["w"]), int(w["s"]), int(w["e"]))
                for w in even_words(chunk, duration)
            ]
            parts.append((clamp_words(words, duration), duration))
            chunk_wavs.append(chunk_wav)
            char_cost += result.char_cost
            if result.note and result.note not in notes:
                notes.append(result.note)
    except Exception as e:
        # Chunks voiced before the failure were billed all the same.
        _book_tts(options, task, key, chars=char_cost, started=started, error=e)
        raise
    _book_tts(options, task, key, chars=char_cost, started=started)

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


def highlights_key(model: str, topic: str, language: str, segments: list[TimelineSegment]) -> str:
    """What the picks depend on: the model and the transcript, not the spoken durations (new
    voices change those, not the moments)."""
    lines = [model, topic, language]
    lines += [f"{s.seq_index}|{s.speaker_name}|{s.turn_type}|{s.text}" for s in segments]
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()


def _cached_picks(path: Path, key: str) -> tuple[str | None, list[HighlightPick]] | None:
    try:
        data = json.loads(path.read_text())
        if data.get("key") != key:
            return None
        return data.get("winner_name"), [HighlightPick(**p) for p in data["picks"]]
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return None


def _host_picks(
    model: str,
    paths: MediaPaths,
    *,
    topic: str,
    language: str,
    segments: list[TimelineSegment],
    speakers: list[TimelineSpeaker],
) -> tuple[str | None, list[HighlightPick]]:
    """The host model's picks, asked once per transcript: a rebuild reads them from
    `highlights.json`, so a paid host costs one call per debate run, not one per audio build.
    Raises when the model is turned off, no free-model slot comes or the answer fails."""
    key = highlights_key(model, topic, language, segments)
    cached = _cached_picks(paths.highlights, key)
    if cached is not None:
        return cached
    if model in runtime_settings.current_sync().disabled_models:
        raise RuntimeError(f"{model} is turned off")
    if free_quota.is_free_model(model) and not free_quota.wait_for_slot(
        time.monotonic() + HIGHLIGHTS_SLOT_WAIT
    ):
        raise RuntimeError("no free-model slot")
    messages = build_highlights_messages(
        topic=topic, language=language, segments=segments, speakers=speakers
    )
    text, _usage = complete(model, messages, purpose="highlights", max_tokens=HIGHLIGHTS_MAX_TOKENS)
    winner_name, picks = parse_highlights(extract_json(text))
    if picks:  # a bad answer (a router's odd pick) is asked again by the next build
        body = {"key": key, "model": model, "winner_name": winner_name}
        paths.highlights.write_text(json.dumps(body | {"picks": [asdict(p) for p in picks]}))
    return winner_name, picks


def _pick_highlights(
    *,
    model: str,
    paths: MediaPaths,
    topic: str,
    language: str,
    segments: list[TimelineSegment],
    speakers: list[TimelineSpeaker],
    total_ms: int,
) -> tuple[list[TimelineHighlight], str | None]:
    """Moments picked by the host's model (the one that ran the debate) with a deterministic
    fallback. Returns (highlights, winner_name)."""
    if not settings.OPENROUTER_API_KEY:
        return fallback_highlights(segments, total_ms), None
    try:
        winner_name, picks = _host_picks(
            model, paths, topic=topic, language=language, segments=segments, speakers=speakers
        )
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


@dataclass
class VisualsResult:
    visuals: list[TimelineVisual]
    usd: float | None  # system-key cost: director, sketches, picture checks (not billed)
    images: ImageStudio | None  # what AI pictures cost (billed after the build)


def _store_plan(turn: Turn, brief: TurnBrief, scenes: list[Any]) -> None:
    """Keep a plan made by the media build on the turn (the live page shows it too). Checks of
    scenes that survived a re-plan are kept; hints and disputes always are."""
    vj = dict(turn.visuals_json or {})
    keys = {s.key for s in scenes}
    vj.update(
        {
            "status": "ready",
            "version": PROMPT_VERSION,
            "text_hash": text_hash(turn.text),
            "images": brief.images,
            "budget": budget_of(brief),
            "scenes": [s.model_dump(mode="json") for s in scenes],
            "checks": {k: v for k, v in (vj.get("checks") or {}).items() if k in keys},
            "checking": [k for k in vj.get("checking") or [] if k in keys],
        }
    )
    turn.visuals_json = vj


def _update_scenes(turn: Turn, picked: list[Any]) -> None:
    """Store what the build chose and filled in (drawings, pictures) on the turn."""
    vj = dict(turn.visuals_json or {})
    filled = {s.key: s.model_dump(mode="json") for s in picked}
    vj["scenes"] = [filled.get(str(raw.get("key")), raw) for raw in vj.get("scenes") or []]
    vj["picked"] = [s.key for s in picked]
    turn.visuals_json = vj


def _fill_scenes(
    db: Session,
    debate: Debate,
    picked: dict[int, list[Any]],
    studio: ImageStudio | None,
    *,
    sketch_model: str,
) -> float:
    """Draw the picked sketches that have no drawing yet and find the pictures (at most
    MEDIA_MAX_IMAGES). Scenes that end up empty are dropped. Returns the usd spent."""
    todo_sketches = [
        (seq, s)
        for seq in picked
        for s in picked[seq]
        if isinstance(s, SketchScene) and not s.drawing
    ]
    wanted = "ai" if studio is not None and studio.allow_ai else "photo"
    todo_images = [
        (seq, s)
        for seq in sorted(picked)
        for s in picked[seq]
        if isinstance(s, ImageScene) and not (s.src and s.kind == wanted)  # found live
    ]
    if todo_sketches or todo_images:
        set_media_state(db, debate, step="visuals", message="Drawing sketches, finding pictures…")
    filled: dict[str, Any] = {}
    usd = 0.0
    with ContextThreadPool(max_workers=max(1, settings.MEDIA_VISUALS_CONCURRENCY)) as pool:
        sketch_jobs = {
            s.key: pool.submit(illustrate, s.subject, model=sketch_model) for _, s in todo_sketches
        }
        image_jobs = {}
        if studio is not None:
            for _, scene in todo_images[: settings.MEDIA_MAX_IMAGES]:
                image_jobs[scene.key] = pool.submit(studio.resolve, scene)
        for key, future in sketch_jobs.items():
            try:
                drawing, cost = future.result()
                usd += cost
                if drawing is not None:
                    filled[key] = drawing
            except Exception as e:
                logger.warning("Sketch %s failed: %s", key, e)
        for key, future in image_jobs.items():
            try:
                resolved = future.result()
                if resolved is not None:
                    filled[key] = resolved
            except Exception as e:
                logger.warning("Picture %s failed: %s", key, e)

    for seq, scenes in picked.items():
        kept: list[Any] = []
        for scene in scenes:
            if isinstance(scene, SketchScene):
                drawing = scene.drawing or filled.get(scene.key)
                if drawing is None:
                    continue
                scene = scene.model_copy(update={"drawing": drawing})
            elif isinstance(scene, ImageScene):
                scene = filled.get(scene.key) or scene
                if not scene.src:
                    continue
            kept.append(scene)
        picked[seq] = kept
    return usd + (studio.check_usd if studio else 0.0)


def _plan_visuals(
    db: Session,
    debate: Debate,
    paths: MediaPaths,
    segments: list[TimelineSegment],
    speakers_by_id: dict[str, TimelineSpeaker],
    turns: list[Turn],
    *,
    topic: str,
    language: str,
    options: MediaOptions,
    allow_ai_images: bool,
    force: bool,
) -> VisualsResult:
    """Scenes of every turn: the plans stored during the debate (`services/studio`), the
    director for turns without one (in parallel), then sketches and pictures, aligned to the
    words. A failing turn only loses its scenes."""
    if not settings.OPENROUTER_API_KEY:
        return VisualsResult([], None, None)
    model = settings.MEDIA_VISUALS_MODEL or settings.VERDICT_MODEL
    images = options.images != "off"
    roles = {s.id: s.role for s in speakers_by_id.values()}
    turns_by_seq = {t.seq_index: t for t in turns}
    briefs: list[TurnBrief] = []
    for b in build_briefs(segments, roles):
        turn = turns_by_seq.get(b.seq_index)
        brief = replace(b, hints=hints_of(turn.visuals_json) if turn else (), images=images)
        if budget_of(brief) > 0:
            briefs.append(brief)

    planned: dict[int, list[Any]] = {}
    to_plan: list[TurnBrief] = []
    for b in briefs:
        turn = turns_by_seq.get(b.seq_index)
        stored = None if force or turn is None else usable_plan(turn.visuals_json, turn.text)
        if stored is None:
            to_plan.append(b)
        else:
            planned[b.seq_index] = [s for s in stored if images or not isinstance(s, ImageScene)]

    total = len(to_plan)
    set_media_state(
        db, debate, step="visuals", current=0, total=total, message="Designing visual scenes…"
    )
    cost = 0.0
    with ContextThreadPool(max_workers=max(1, settings.MEDIA_VISUALS_CONCURRENCY)) as pool:
        futures = {
            pool.submit(
                plan_scenes, b, topic=topic, language=language, model=model, budget=budget_of(b)
            ): b
            for b in to_plan
        }
        for done, future in enumerate(as_completed(futures), start=1):
            brief = futures[future]
            try:
                scenes, usd = future.result()
                planned[brief.seq_index] = scenes
                cost += usd
                if brief.seq_index in turns_by_seq:
                    _store_plan(turns_by_seq[brief.seq_index], brief, scenes)
            except Exception as e:
                logger.warning("Visual director failed for turn %s: %s", brief.seq_index, e)
            set_media_state(
                db,
                debate,
                step="visuals",
                current=done,
                total=total,
                message=f"Designed scenes for {done} of {total} turns",
            )

    picked = diversify(
        [
            (b.seq_index, planned[b.seq_index], budget_of(b))
            for b in briefs
            if b.seq_index in planned
        ]
    )
    studio = ImageStudio(paths, mode=options.images, allow_ai=allow_ai_images) if images else None
    cost += _fill_scenes(
        db, debate, picked, studio, sketch_model=settings.MEDIA_SKETCH_MODEL or model
    )
    for seq, scenes in picked.items():
        if seq in turns_by_seq:
            _update_scenes(turns_by_seq[seq], scenes)
    db.commit()

    by_seq = {s.seq_index: s for s in segments}
    disputes = disputes_by_key(turns)
    visuals: list[TimelineVisual] = []
    for seq in sorted(picked):
        turn = turns_by_seq.get(seq)
        for v in align_scenes(picked[seq], by_seq[seq]):
            v.check = check_of(turn.visuals_json, v.key) if turn else None
            v.disputes = disputes.get(v.key, [])
            visuals.append(v)
    return VisualsResult(visuals, round(cost, 6), studio)


def _add_scoreboard(
    visuals: list[TimelineVisual],
    segments: list[TimelineSegment],
    speakers: list[TimelineSpeaker],
    verdict: TimelineVerdict,
    verdict_json: dict[str, Any] | None,
) -> list[TimelineVisual]:
    """The judge's scoreboard on the verdict turn. A draw is shown only when the structured
    verdict says so (a regex fallback without a winner is not a reliable draw)."""
    structured = verdict_json or {}
    is_draw = structured.get("source") == "llm" and bool(structured.get("is_draw"))
    segment = next((s for s in segments if s.seq_index == verdict.seq_index), None)
    debater_ids = [s.id for s in speakers if s.role == "debater"]
    if segment is None or len(debater_ids) < 2 or not (verdict.winner_id or is_draw):
        return visuals
    board = scoreboard_visual(
        segment,
        debater_ids,
        winner_id=verdict.winner_id,
        winner_name=verdict.winner_name,
        headline=str(structured.get("headline") or ""),
    )
    return make_room(visuals, board)


def _build(
    db: Session, debate: Debate, options: MediaOptions, force: bool
) -> tuple[int, ImageStudio | None]:
    """Voice, mix and write the timeline. Returns the characters actually synthesized
    (cached turns excluded), which is what premium voices are billed on, and the picture
    studio (what AI pictures cost)."""
    debate_id = str(debate.id)
    conf: dict[str, Any] = debate.config_json or {}
    # The video shows the models that actually spoke (a Free Router's pinned model).
    participants = resolved_participants(conf.get("participants", []), debate.participants)
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
    tts_key: KeyOwner = "user" if user_key else "system"
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
    with ContextThreadPool(max_workers=max(1, settings.TTS_CONCURRENCY)) as pool:
        futures = [
            pool.submit(_synthesize_turn, provider, paths, task, options, force, code, tts_key)
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

    fmt = format_of(conf)
    segments: list[TimelineSegment] = []
    for task, audio, offset in zip(tasks, ordered, offsets, strict=True):
        segments.append(
            TimelineSegment(
                seq_index=task.seq_index,
                speaker_id=task.speaker.id,
                speaker_name=task.speaker.name,
                round_id=task.round_id,
                round_label=fmt.round_label(task.round_id, task.turn_type),
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

    visuals: list[TimelineVisual] = []
    visuals_usd: float | None = None
    image_studio: ImageStudio | None = None
    if options.visuals:
        try:
            result = _plan_visuals(
                db,
                debate,
                paths,
                segments,
                speakers_by_id,
                turns,
                topic=str(conf.get("topic") or ""),
                language=language,
                options=options,
                allow_ai_images=options.images == "ai"
                and (free_build(debate) or has_balance(debate)),
                force=force,
            )
            visuals, visuals_usd, image_studio = result.visuals, result.usd, result.images
        except Exception:
            logger.exception("Visual scenes failed for %s, continuing without them", debate_id)
            db.rollback()
            visuals = []

    set_media_state(db, debate, step="highlights", message="Picking highlights for shorts…")
    highlights, winner_name = _pick_highlights(
        model=judge_model,
        paths=paths,
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
        if options.visuals:
            visuals = _add_scoreboard(visuals, segments, speakers, verdict, debate.verdict_json)

    chars = sum(len(strip_audio_tags(task.text)) for task in tasks)
    char_cost = sum(a.char_cost for a in ordered if not a.cached)
    stats = TimelineStats(
        chars=chars,
        tts_ms=tts_ms,
        estimated_usd=estimate_usd(options.model_id, char_cost)
        if provider.name == "elevenlabs"
        else None,
        cached_turns=sum(1 for a in ordered if a.cached),
        visuals_usd=visuals_usd,
        images_usd=round(image_studio.ai_usd, 6) if image_studio else None,
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
        visuals=visuals,
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
    return char_cost, image_studio


def _charge_build(
    db: Session,
    debate: Debate,
    state: dict[str, Any],
    options: MediaOptions,
    billed_chars: int,
    images: ImageStudio | None,
    build_ref: str,
) -> None:
    """Charge the owner for premium voices and AI pictures of a finished build, at the prices
    it was queued with (`media_json.prices`)."""
    debate_id = str(debate.id)
    prices = prices_of(state)
    tx = charge_media_sync(
        db,
        debate,
        chars=billed_chars,
        provider=options.provider,
        own_key=bool(state.get("own_tts_key")),
        build_ref=build_ref,
        price_per_1k=prices.voices_per_1k,
    )
    if tx is not None:
        logger.info("Charged %s credits for voices of %s", -tx.amount_usd, debate_id)
    if images is not None and images.ai_count:
        tx = charge_images_sync(
            db,
            debate,
            usd=images.ai_usd,
            count=images.ai_count,
            build_ref=build_ref,
            markup=prices.markup,
        )
        if tx is not None:
            logger.info("Charged %s credits for pictures of %s", -tx.amount_usd, debate_id)


@beating(media_beat_key)
@attributed
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
            billed_chars, images = _build(db, debate, options, force)
            build_ref = str((debate.media_json or {}).get("finished_at") or int(time.time()))
            try:
                if state.get("free"):
                    # Queued by an admin from the console: the owner pays nothing.
                    logger.info("Free media build of %s: nothing charged", debate_id)
                else:
                    _charge_build(db, debate, state, options, billed_chars, images, build_ref)
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
