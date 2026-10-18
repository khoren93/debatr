"""The studio: visual scenes of every turn, designed while the debate runs.

Right after a turn is saved the worker asks the visual director for its scenes (debaters may
have requested some with `[visual: …]`), keeps the ones the show uses (`diversify` across the
turns so far), draws the sketches and, when the debate has `fact_check` on, checks the scenes
stating facts on the web. Every step is published as an SSE `turn_visuals` event, so the live
page shows the scenes next to the text. Later speakers see their opponents' scenes and may
challenge one (`[dispute N: …]`); the judge gets the fact-checks and the challenges. The media
build takes the stored plans instead of designing again (`media/jobs.py`).

`turns.visuals_json`:
    status       designing | checking | ready | error
    version      PROMPT_VERSION of the plan; text_hash of the spoken text; images: bool
    budget       scenes the turn deserves
    scenes       the director's candidates (spare included), each with its `key`
    picked       keys of the scenes the show uses, in speech order
    hints        [{"text", "after"}] the speaker's [visual: …] requests
    disputes     [{"key", "reason"}] scenes of earlier turns this turn challenged
    checking     keys sent to the fact-checker; checks: {key: SceneCheck}
    usd          {"design": system-key cost, "check": fact-check cost (billed)}
"""

import hashlib
import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.models import Debate, Turn
from app.schemas.schemas import TurnDisputeOut, TurnSceneOut, TurnVisualsOut
from app.schemas.visuals import (
    ImageScene,
    RebuttalScene,
    SceneCheck,
    SceneDispute,
    SketchScene,
    assign_keys,
)
from app.services.credits import has_balance
from app.services.events import publish_event
from app.services.factcheck import check_scene
from app.services.markers import DisputeMark, Hint
from app.services.media.images import ImageStudio
from app.services.media.llm import complete, extract_json
from app.services.media.paths import MediaPaths
from app.services.media.script import clean_markdown, strip_audio_tags
from app.services.media.sketch import illustrate
from app.services.media.visuals import (
    PROMPT_VERSION,
    TurnBrief,
    build_director_messages,
    diversify,
    is_checkable,
    is_disputable,
    parse_scenes,
    scene_budget,
    scene_summary,
)
from app.services.usage import ContextThreadPool

logger = logging.getLogger(__name__)

MAX_CLAIMS_IN_PROMPT = 6
DESIGN_WORKERS = 4

# --- configuration -----------------------------------------------------------------------


def _plan(conf: dict[str, Any]) -> dict[str, Any]:
    return conf.get("media_plan") or {}


def visuals_enabled(conf: dict[str, Any]) -> bool:
    """Scenes are designed live when the wizard's media plan has visual scenes on."""
    plan = _plan(conf)
    return bool(plan) and bool(plan.get("visuals", True))


def images_mode(conf: dict[str, Any]) -> str:
    """off | stock | ai — pictures come with the audio build, so they need the audio output."""
    plan = _plan(conf)
    if not visuals_enabled(conf) or "audio" not in (plan.get("outputs") or ["audio"]):
        return "off"
    mode = str(plan.get("images") or "off")
    return mode if mode in ("stock", "ai") else "off"


def images_wanted(conf: dict[str, Any]) -> bool:
    return images_mode(conf) != "off"


def fact_check_enabled(conf: dict[str, Any]) -> bool:
    return visuals_enabled(conf) and bool(conf.get("fact_check"))


# --- stored plans ------------------------------------------------------------------------


def spoken_text(text: str) -> str:
    """What the speaker says aloud (the same text the media build voices and aligns)."""
    return strip_audio_tags(clean_markdown(text or ""))


def text_hash(text: str) -> str:
    return hashlib.sha256(spoken_text(text).encode()).hexdigest()[:16]


def is_usable(turn: Turn) -> bool:
    text = (turn.text or "").strip()
    return bool(text) and not turn.error and not text.startswith("[Error")


def role_of(turn: Turn) -> str:
    if turn.turn_type == "verdict":
        return "judge"
    return "moderator" if turn.turn_type.startswith("moderator") else "debater"


def stored_scenes(visuals: dict[str, Any] | None) -> list[Any]:
    """The director's candidates of a turn (keys kept)."""
    raw = (visuals or {}).get("scenes")
    return parse_scenes(raw, 99) if isinstance(raw, list) else []


def usable_plan(visuals: dict[str, Any] | None, text: str) -> list[Any] | None:
    """A stored plan the media build may reuse: same prompt version and spoken text."""
    vj = visuals or {}
    if vj.get("version") != PROMPT_VERSION or vj.get("text_hash") != text_hash(text):
        return None
    if vj.get("status") not in ("checking", "ready"):
        return None
    return stored_scenes(vj)


def _shown(scene: Any) -> bool:
    """Sketches and pictures are shown only once drawn / found."""
    if isinstance(scene, SketchScene):
        return scene.drawing is not None
    if isinstance(scene, ImageScene):
        return bool(scene.src)
    return True


def picked_scenes(visuals: dict[str, Any] | None) -> list[Any]:
    """The scenes the show uses for a turn, in speech order."""
    vj = visuals or {}
    keys = set(vj.get("picked") or [])
    return [s for s in stored_scenes(vj) if s.key in keys and _shown(s)]


def check_of(visuals: dict[str, Any] | None, key: str) -> SceneCheck | None:
    raw = ((visuals or {}).get("checks") or {}).get(key)
    if not isinstance(raw, dict):
        return None
    try:
        return SceneCheck.model_validate(raw)
    except ValueError:
        return None


def hints_of(visuals: dict[str, Any] | None) -> tuple[tuple[str, str], ...]:
    out: list[tuple[str, str]] = []
    for item in (visuals or {}).get("hints") or []:
        if isinstance(item, dict) and item.get("text"):
            out.append((str(item["text"]), str(item.get("after") or "")))
    return tuple(out)


def initial_visuals(hints: list[Hint], disputes: list[dict[str, str]]) -> dict[str, Any]:
    """visuals_json of a freshly saved turn: what the speaker asked for and challenged."""
    out: dict[str, Any] = {}
    if hints:
        out["hints"] = [{"text": h.text, "after": h.after} for h in hints]
    if disputes:
        out["disputes"] = disputes
    return out


# --- briefs ------------------------------------------------------------------------------


def debater_names(conf: dict[str, Any]) -> tuple[str, ...]:
    return tuple(
        str(p.get("display_name") or f"Debater {i}")
        for i, p in enumerate(conf.get("participants") or [])
        if p.get("role") == "debater"
    )


def brief_for(turn: Turn, earlier: list[Turn], conf: dict[str, Any]) -> TurnBrief:
    """What the director needs about a turn; the opponent is the last other debater who spoke."""
    role = role_of(turn)
    rival: Turn | None = None
    if role == "debater":
        rival = next(
            (
                t
                for t in reversed(earlier)
                if is_usable(t) and role_of(t) == "debater" and t.speaker_id != turn.speaker_id
            ),
            None,
        )
    return TurnBrief(
        seq_index=turn.seq_index,
        speaker_id=turn.speaker_id,
        speaker_name=turn.speaker_name,
        role=role,
        turn_type=turn.turn_type,
        text=spoken_text(turn.text),
        previous_text=spoken_text(rival.text) if rival else None,
        opponent=rival.speaker_name if rival else None,
        debaters=debater_names(conf),
        hints=hints_of(turn.visuals_json),
        images=images_wanted(conf),
    )


def budget_of(brief: TurnBrief) -> int:
    return scene_budget(brief.text, brief.role, len(brief.hints))


def plan_scenes(
    brief: TurnBrief, *, topic: str, language: str, model: str, budget: int
) -> tuple[list[Any], float]:
    """Ask the director for a turn's candidates (spare included). Returns (scenes, usd)."""
    messages = build_director_messages(brief, topic=topic, language=language, budget=budget)
    text, usage = complete(model, messages, purpose="director", max_tokens=1600)
    try:
        payload = extract_json(text)
    except ValueError:
        payload = None
    scenes = parse_scenes(
        payload,
        budget + 1,
        speech=f"{brief.text} {brief.hint_text}".strip(),
        speaker=brief.speaker_name,
        opponent=brief.opponent,
        debaters=brief.debaters,
        images=brief.images,
    )
    return assign_keys(brief.seq_index, scenes), float((usage or {}).get("cost") or 0.0)


def pick_for(turn: Turn, scenes: list[Any], budget: int, earlier: list[Turn]) -> list[Any]:
    """The candidates the show uses: `diversify` over the turns so far, this one last."""
    history = [
        (t.seq_index, stored_scenes(t.visuals_json), int((t.visuals_json or {}).get("budget") or 0))
        for t in earlier
        if (t.visuals_json or {}).get("status") in ("checking", "ready")
    ]
    return diversify([*history, (turn.seq_index, scenes, budget)])[turn.seq_index]


# --- live design -------------------------------------------------------------------------


def _publish(debate: Debate, turn: Turn) -> None:
    out = turn_visuals_out(turn)
    if out is not None:
        publish_event(
            str(debate.id),
            "turn_visuals",
            {"seq_index": turn.seq_index, "visuals": out.model_dump(mode="json")},
        )


def _save(db: Session, debate: Debate, turn: Turn, visuals: dict[str, Any]) -> None:
    turn.visuals_json = dict(visuals)  # a new dict, so SQLAlchemy sees the change
    db.commit()
    _publish(debate, turn)


def _add_check_cost(debate: Debate, usd: float) -> None:
    if usd:
        totals = dict(debate.totals_json or {})
        totals["analysis_cost"] = float(totals.get("analysis_cost") or 0.0) + usd
        debate.totals_json = totals


def design_turn(db: Session, debate: Debate, turn: Turn, *, api_key: str | None) -> None:
    """Design, draw and fact-check the scenes of a saved turn. Never raises: a failure only
    loses the turn's live scenes (the media build designs them again)."""
    conf: dict[str, Any] = debate.config_json or {}
    if not visuals_enabled(conf) or not is_usable(turn) or not settings.OPENROUTER_API_KEY:
        return
    try:
        _design(db, debate, turn, conf, api_key)
    except Exception:
        logger.exception("Live scenes failed for turn %s of %s", turn.seq_index, debate.id)
        db.rollback()
        try:
            _save(db, debate, turn, {**(turn.visuals_json or {}), "status": "error"})
        except Exception:
            db.rollback()


def _design(
    db: Session, debate: Debate, turn: Turn, conf: dict[str, Any], api_key: str | None
) -> None:
    earlier = [
        t
        for t in db.scalars(
            select(Turn).where(Turn.debate_id == debate.id).order_by(Turn.seq_index)
        ).all()
        if t.seq_index < turn.seq_index
    ]
    brief = brief_for(turn, earlier, conf)
    budget = budget_of(brief)
    visuals: dict[str, Any] = {
        **(turn.visuals_json or {}),
        "version": PROMPT_VERSION,
        "text_hash": text_hash(turn.text),
        "images": brief.images,
        "budget": budget,
        "scenes": [],
        "picked": [],
        "checking": [],
        "checks": {},
    }
    if budget == 0:
        _save(db, debate, turn, {**visuals, "status": "ready"})
        return
    _save(db, debate, turn, {**visuals, "status": "designing"})

    topic = str(conf.get("topic") or "")
    language = str(conf.get("language") or "English")
    model = settings.MEDIA_VISUALS_MODEL or settings.MEDIA_HIGHLIGHTS_MODEL
    scenes, design_usd = plan_scenes(
        brief, topic=topic, language=language, model=model, budget=budget
    )
    picked = pick_for(turn, scenes, budget, earlier)
    checks = (
        [s for s in picked if is_checkable(s)][: settings.FACT_CHECK_MAX_PER_TURN]
        if fact_check_enabled(conf) and role_of(turn) == "debater"
        else []
    )
    sketches = [s for s in picked if isinstance(s, SketchScene)]
    pictures = [s for s in picked if isinstance(s, ImageScene)]
    studio: ImageStudio | None = None
    if pictures:
        shown = sum(
            isinstance(s, ImageScene) for t in earlier for s in picked_scenes(t.visuals_json)
        )
        pictures = pictures[: max(0, settings.MEDIA_MAX_IMAGES - shown)]
        mode = images_mode(conf)
        studio = ImageStudio(
            MediaPaths(str(debate.id)), mode=mode, allow_ai=mode == "ai" and has_balance(debate)
        )
    visuals.update(
        {
            "scenes": [s.model_dump(mode="json") for s in scenes],
            "picked": [s.key for s in picked],
            "checking": [s.key for s in checks],
            "usd": {"design": round(design_usd, 6), "check": 0.0},
        }
    )
    pending = bool(checks or sketches or pictures)
    _save(db, debate, turn, {**visuals, "status": "checking" if pending else "ready"})
    if not pending:
        return

    sketch_model = settings.MEDIA_SKETCH_MODEL or model
    results: dict[str, Any] = {}
    check_usd = 0.0
    with ContextThreadPool(max_workers=DESIGN_WORKERS) as pool:
        drawn = {s.key: pool.submit(illustrate, s.subject, model=sketch_model) for s in sketches}
        found = {s.key: pool.submit(studio.resolve, s) for s in pictures if studio is not None}
        checked = {
            s.key: pool.submit(
                check_scene,
                s,
                speech=f"{brief.text} {brief.hint_text}".strip(),
                topic=topic,
                language=language,
                speaker=turn.speaker_name,
                model=settings.FACT_CHECK_MODEL,
                api_key=api_key,
            )
            for s in checks
        }
        for key, future in drawn.items():
            try:
                drawing, usd = future.result()
                design_usd += usd
                if drawing is not None:
                    results[key] = drawing.model_dump(mode="json")
            except Exception as e:
                logger.warning("Sketch %s failed: %s", key, e)
        resolved: dict[str, dict[str, Any]] = {}
        for key, future in found.items():
            try:
                picture = future.result()
                if picture is not None:
                    resolved[key] = picture.model_dump(mode="json")
            except Exception as e:
                logger.warning("Picture %s failed: %s", key, e)
        check_results: dict[str, Any] = {}
        for key, future in checked.items():
            try:
                result, usd = future.result()
                check_usd += usd
                if result is not None:
                    check_results[key] = result.model_dump(mode="json")
            except Exception as e:
                logger.warning("Fact-check %s failed: %s", key, e)

    for i, scene in enumerate(visuals["scenes"]):
        if scene.get("key") in results:
            scene["drawing"] = results[scene["key"]]
        if scene.get("key") in resolved:
            visuals["scenes"][i] = resolved[scene["key"]]
    visuals["checks"] = check_results
    if studio is not None:
        design_usd += studio.check_usd
    visuals["usd"] = {
        "design": round(design_usd, 6),
        "check": round(check_usd, 6),
        "images": round(studio.ai_usd, 6) if studio else 0.0,
        "images_count": studio.ai_count if studio else 0,
    }
    _add_check_cost(debate, check_usd)
    _save(db, debate, turn, {**visuals, "status": "ready"})


# --- claims, disputes and the judge ------------------------------------------------------


@dataclass(frozen=True)
class Claim:
    """An opponent's scene a speaker may challenge (`[dispute N: …]`)."""

    number: int
    key: str
    seq_index: int
    speaker_name: str
    summary: str
    check: SceneCheck | None


def visual_claims(turns: list[Turn], speaker_id: str, speaker_name: str) -> list[Claim]:
    """Opponents' scenes worth challenging, the most recent MAX_CLAIMS_IN_PROMPT, numbered.
    A rebuttal scene counts only when it is about this speaker's own point."""
    found: list[tuple[str, Turn, Any]] = []
    for turn in turns:
        if role_of(turn) != "debater" or turn.speaker_id == speaker_id:
            continue
        for scene in picked_scenes(turn.visuals_json):
            if not is_disputable(scene):
                continue
            if isinstance(scene, RebuttalScene) and scene.claim_author != speaker_name:
                continue
            found.append((scene.key, turn, scene))
    found = found[-MAX_CLAIMS_IN_PROMPT:]
    return [
        Claim(
            number=i,
            key=key,
            seq_index=turn.seq_index,
            speaker_name=turn.speaker_name,
            summary=scene_summary(scene),
            check=check_of(turn.visuals_json, key),
        )
        for i, (key, turn, scene) in enumerate(found, start=1)
    ]


def resolve_disputes(marks: list[DisputeMark], claims: list[Claim]) -> list[dict[str, str]]:
    """Map `[dispute N: …]` to the scene keys offered in the prompt (unknown numbers dropped)."""
    by_number = {c.number: c for c in claims}
    out: list[dict[str, str]] = []
    for mark in marks:
        claim = by_number.get(mark.number)
        if claim is not None and all(d["key"] != claim.key for d in out):
            out.append({"key": claim.key, "reason": mark.reason[:300]})
    return out


def disputes_by_key(turns: list[Turn]) -> dict[str, list[SceneDispute]]:
    """Every challenge made in the debate, by the key of the challenged scene."""
    out: dict[str, list[SceneDispute]] = {}
    for turn in turns:
        for item in (turn.visuals_json or {}).get("disputes") or []:
            if not isinstance(item, dict) or not item.get("key"):
                continue
            out.setdefault(str(item["key"]), []).append(
                SceneDispute(
                    by_id=turn.speaker_id,
                    by_name=turn.speaker_name,
                    seq_index=turn.seq_index,
                    reason=str(item.get("reason") or ""),
                )
            )
    return out


def verdict_evidence(turns: list[Turn]) -> str:
    """Fact-checks and challenges for the judge's prompt ("" when there are none)."""
    checks: list[str] = []
    summaries: dict[str, tuple[str, str]] = {}
    for turn in turns:
        if role_of(turn) != "debater":
            continue
        for scene in picked_scenes(turn.visuals_json):
            summaries[scene.key] = (turn.speaker_name, scene_summary(scene))
            check = check_of(turn.visuals_json, scene.key)
            if check is not None:
                note = f": {check.note}" if check.note else ""
                checks.append(
                    f"- {turn.speaker_name} showed {scene_summary(scene)} — {check.verdict}{note}"
                )
    challenges: list[str] = []
    for key, disputes in disputes_by_key(turns).items():
        owner, summary = summaries.get(key, ("", ""))
        for d in disputes:
            target = f"{owner}'s {summary}" if owner else "an on-screen claim"
            reason = f": {d.reason}" if d.reason else ""
            challenges.append(f"- {d.by_name} challenged {target}{reason}")
    if not checks and not challenges:
        return ""
    parts: list[str] = []
    if checks:
        parts.append(
            "Web fact-check of the figures and quotes the debaters put on screen:\n"
            + "\n".join(checks)
        )
    if challenges:
        parts.append("Challenges between the debaters:\n" + "\n".join(challenges))
    return "\n\n".join(parts)


def live_pictures_cost(turns: list[Turn]) -> tuple[float, int]:
    """AI pictures generated while the debate ran: (provider usd, count), charged at the end."""
    usd, count = 0.0, 0
    for turn in turns:
        spent = (turn.visuals_json or {}).get("usd") or {}
        usd += float(spent.get("images") or 0.0)
        count += int(spent.get("images_count") or 0)
    return round(usd, 6), count


def claims_summary(turns: list[Turn]) -> dict[str, dict[str, int]]:
    """Fact-check verdicts per debater (participant id) for the leaderboard."""
    out: dict[str, dict[str, int]] = {}
    for turn in turns:
        if role_of(turn) != "debater":
            continue
        vj = turn.visuals_json or {}
        for key in vj.get("picked") or []:
            check = check_of(vj, key)
            if check is None:
                continue
            counts = out.setdefault(
                turn.speaker_id, {"checked": 0, "verified": 0, "disputed": 0, "unverified": 0}
            )
            counts["checked"] += 1
            counts[check.verdict] += 1
    return out


# --- API output --------------------------------------------------------------------------


def turn_visuals_out(turn: Turn) -> TurnVisualsOut | None:
    vj = turn.visuals_json or {}
    status = str(vj.get("status") or "")
    disputes = [
        TurnDisputeOut(key=str(d["key"]), reason=str(d.get("reason") or ""))
        for d in vj.get("disputes") or []
        if isinstance(d, dict) and d.get("key")
    ]
    if not status and not disputes:
        return None
    checking = set(vj.get("checking") or [])
    return TurnVisualsOut(
        status=status or "none",
        scenes=[
            TurnSceneOut(key=s.key, scene=s, checkable=s.key in checking, check=check_of(vj, s.key))
            for s in picked_scenes(vj)
        ],
        disputes=disputes,
    )


def claims_prompt(claims: list[Claim]) -> str:
    """Numbered lines for the debater prompt (`build_debater_messages(visual_claims=…)`)."""
    lines: list[str] = []
    for c in claims:
        check = ""
        if c.check is not None:
            note = f" ({c.check.note})" if c.check.note else ""
            check = f" — fact-check: {c.check.verdict}{note}"
        lines.append(f"[{c.number}] {c.speaker_name}: {c.summary}{check}")
    return "\n".join(lines)
