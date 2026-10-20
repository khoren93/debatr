"""Debate configs, references and summaries. Pure helpers shared by the CLI and the MCP server.

`build_config` produces the `DebateConfig` JSON of `POST /api/debates` (see the API docs);
`digest` turns a `DebateDetail` into the compact, stable shape printed by `--json` and returned
to agents.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlsplit

FREE_MODEL = "openrouter/free"  # OpenRouter's router over the free models
HOST_NAME = "The Host"
DEBATER_NAMES = ("Nova", "Atlas", "Quill", "Sage", "Echo", "Juno", "Rook", "Vega")
LENGTHS = ("very_short", "short", "medium", "long")
STYLES = ("markdown", "spoken")
VOICE_ENGINES = ("edge", "elevenlabs")
# Show formats (`GET /api/formats`): a debate, or a rap battle of an MC and two rappers voiced by
# ElevenLabs (one music track; each rapper takes a flow instead of a voice).
FORMATS = ("debate", "rap_battle")
MAX_PARTICIPANTS = 8
MAX_ROUNDS = 10
BATTLE_MAX_ROUNDS = 3
MC_NAME = "The MC"
MC_PERSONA = "You are a high-energy battle rap MC."
RAPPER_PERSONA = "You are a sharp, witty battle rapper."
# The server's limit: the topic is drawn on the video (older servers took up to 500).
TOPIC_MAX_LENGTH = 150
HOST_PERSONA = (
    "You are an impartial debate moderator. Introduce the topic, keep speakers on time, "
    "summarize each round."
)
TURN_TYPES = {
    "moderator_intro": "Intro",
    "moderator_transition": "Transition",
    "moderator_comment": "Moderator",
    "opening": "Opening",
    "rebuttal": "Rebuttal",
    "closing": "Closing",
    "argument": "Argument",
    "verse": "Verse",
    "verdict": "Verdict",
}
_SLUG_RE = re.compile(r"^[a-z0-9]{4,32}$")


def default_stance(index: int) -> str:
    """The wizard's default personas: first for, second against, the rest their own angle."""
    base = "You are a skilled debater."
    if index == 0:
        return f"{base} Argue in favor of the topic."
    if index == 1:
        return f"{base} Argue against the topic."
    return f"{base} Provide a unique perspective (Position {index + 1})."


@dataclass
class Debater:
    model: str = FREE_MODEL
    name: str | None = None
    stance: str | None = None


def _check_model(model: str) -> str:
    model = model.strip()
    if not model or len(model) > 200 or any(ch.isspace() for ch in model):
        raise ValueError(f"Not a model id: {model!r} (see `debatr models`)")
    return model


def build_config(
    topic: str,
    debaters: list[Debater],
    *,
    host_model: str | None = FREE_MODEL,
    rounds: int = 2,
    length: str = "short",
    language: str = "English",
    intensity: int = 5,
    style: str | None = None,
    context: str | None = None,
    scenes: bool = False,
    fact_check: bool = False,
    audio: bool = False,
    voices: str | None = None,
    public: bool = False,
    draft: bool = False,
    openrouter_key: str | None = None,
    elevenlabs_key: str | None = None,
    format: str = "debate",
    flows: list[str] | None = None,
) -> dict[str, Any]:
    """The request body of `POST /api/debates`. `host_model=None` runs without a host (the
    judge's verdict then uses the server's default model). `voices`: edge by default, premium
    (elevenlabs) for a rap battle, the only voices it takes. `flows`: a rap battle's rappers, in
    order (see `debatr formats`). Raises ValueError with a message for the user when an option
    is out of range."""
    if format not in FORMATS:
        raise ValueError(f"Format must be one of: {', '.join(FORMATS)}")
    battle = format == "rap_battle"
    voices = voices or ("elevenlabs" if battle else "edge")
    if battle:
        if not host_model:
            raise ValueError("A rap battle needs its MC: drop --no-host")
        if len(debaters) != 2:
            raise ValueError("A rap battle takes exactly two rappers (-d twice)")
        if rounds > BATTLE_MAX_ROUNDS:
            raise ValueError(f"A rap battle runs 1 to {BATTLE_MAX_ROUNDS} rounds")
        if scenes or fact_check:
            raise ValueError("A rap battle has no scenes or fact-checks")
        if audio and voices != "elevenlabs":
            raise ValueError("A rap battle is voiced with premium voices only (elevenlabs)")
    flows = [f.strip() for f in flows or [] if f.strip()]
    if flows and not battle:
        raise ValueError("Flows are for rap battles (--format rap_battle)")
    if flows and not audio:
        raise ValueError("Flows shape the battle's music: add --audio")
    if len(flows) > 2:
        raise ValueError("A rap battle has two rappers: at most two flows")
    topic = " ".join(topic.split())
    if not topic:
        raise ValueError("The topic is empty")
    if len(topic) > TOPIC_MAX_LENGTH:
        raise ValueError(f"The topic is longer than {TOPIC_MAX_LENGTH} characters")
    if not debaters:
        raise ValueError("A debate needs at least one debater")
    seats = MAX_PARTICIPANTS - (1 if host_model else 0)
    if len(debaters) > seats:
        raise ValueError(f"At most {seats} debaters{' with a host' if host_model else ''}")
    if not 1 <= rounds <= MAX_ROUNDS:
        raise ValueError(f"Rounds must be between 1 and {MAX_ROUNDS}")
    if not 1 <= intensity <= 10:
        raise ValueError("Intensity must be between 1 and 10")
    if length not in LENGTHS:
        raise ValueError(f"Length must be one of: {', '.join(LENGTHS)}")
    if style is not None and style not in STYLES:
        raise ValueError(f"Style must be one of: {', '.join(STYLES)}")
    if voices not in VOICE_ENGINES:
        raise ValueError(f"Voices must be one of: {', '.join(VOICE_ENGINES)}")
    language = language.strip() or "English"
    if len(language) > 50:
        raise ValueError("The language name is too long")
    if context and len(context) > 4000:
        raise ValueError("The context is longer than 4000 characters")

    host_name = MC_NAME if battle else HOST_NAME
    participants: list[dict[str, Any]] = []
    if host_model:
        participants.append(
            {
                "role": "moderator",
                "model_id": _check_model(host_model),
                "display_name": host_name,
                "persona_custom": MC_PERSONA if battle else HOST_PERSONA,
            }
        )
    taken = {host_name.lower()} if host_model else set()
    spare = [
        n for n in DEBATER_NAMES if n.lower() not in {(d.name or "").lower() for d in debaters}
    ]
    for i, debater in enumerate(debaters):
        name = " ".join((debater.name or "").split()) or (
            spare.pop(0) if spare else f"Debater {i + 1}"
        )
        if len(name) > 100:
            raise ValueError(f"The name {name[:20]!r}… is longer than 100 characters")
        if name.lower() in taken:
            raise ValueError(f"Two speakers are called {name!r}: names must be unique")
        taken.add(name.lower())
        # A battle seats the sides itself (the first raps for the topic): a persona only.
        stance = (debater.stance or "").strip() or (RAPPER_PERSONA if battle else default_stance(i))
        if len(stance) > 4000:
            raise ValueError(f"The stance of {name} is longer than 4000 characters")
        participants.append(
            {
                "role": "debater",
                "model_id": _check_model(debater.model),
                "display_name": name,
                "persona_custom": stance,
            }
        )

    visuals = scenes or fact_check
    config: dict[str, Any] = {
        # Older servers know no formats: a debate goes without the field.
        **({"format": format} if format != "debate" else {}),
        "topic": topic,
        "language": language,
        "participants": participants,
        "debate_preset_id": "custom",
        "num_rounds": rounds,
        "length_preset": length,
        "intensity": intensity,
        # Spoken prose reads well aloud; Markdown reads well in a terminal.
        "output_style": style or ("spoken" if audio else "markdown"),
        "auto_publish": public,
        "fact_check": fact_check,
        "draft": draft,
    }
    if context and context.strip():
        config["description"] = context.strip()
    if visuals or audio:
        config["media_plan"] = {
            "provider": voices,
            "voices": {},  # the server picks a voice per speaker for the language
            "outputs": ["audio", "video", "short"] if audio else [],
            "visuals": visuals,
            "images": "off",
        }
        if flows:
            # Speaker ids follow the participant list (the MC is participant_0).
            first = len(participants) - len(debaters)
            config["media_plan"]["flows"] = {
                f"participant_{first + i}": flow for i, flow in enumerate(flows)
            }
    if openrouter_key:
        config["user_provider_key"] = openrouter_key.strip()
    if elevenlabs_key and audio and voices == "elevenlabs":
        config["user_tts_key"] = elevenlabs_key.strip()
    return config


# --- references -------------------------------------------------------------------------


@dataclass(frozen=True)
class DebateRef:
    kind: Literal["id", "slug"]
    value: str


def parse_debate_ref(ref: str) -> DebateRef:
    """A debate id, a share slug or a link to either (`…/debate/<id>`, `…/d/<slug>`, or the
    canonical `…/d/<slug>/<topic-words>`)."""
    value = ref.strip()
    if "/" in value:
        parts = [
            p for p in urlsplit(value if "://" in value else f"x://{value}").path.split("/") if p
        ]
        if len(parts) >= 3 and parts[-3] in ("d", "embed"):
            parts = parts[:-1]
        if len(parts) >= 2 and parts[-2] in ("debate", "debates"):
            value = parts[-1]
        elif len(parts) >= 2 and parts[-2] in ("d", "embed"):
            return _slug(parts[-1], ref)
        else:
            raise ValueError(f"Not a debate link: {ref}")
    try:
        return DebateRef("id", str(uuid.UUID(value)))
    except ValueError:
        return _slug(value, ref)


def _slug(value: str, ref: str) -> DebateRef:
    if not _SLUG_RE.match(value):
        raise ValueError(f"Not a debate id, share link or slug: {ref}")
    return DebateRef("slug", value)


# --- summaries -----------------------------------------------------------------------------


def side_tags(participants: list[dict[str, Any]]) -> dict[str, str]:
    """participant id -> HOST / PRO / CON / SIDE 3… (as on the web)."""
    tags: dict[str, str] = {}
    index = 0  # among the debaters
    for i, p in enumerate(participants):
        pid = p.get("id") or f"participant_{i}"
        if p.get("role") == "moderator":
            tags[pid] = "HOST"
            continue
        tags[pid] = "PRO" if index == 0 else "CON" if index == 1 else f"SIDE {index + 1}"
        index += 1
    return tags


def round_heading(round_id: str, turn_type: str) -> str:
    """ "Round 2 · Rebuttal", "Verdict"."""
    if round_id == "verdict" or turn_type == "verdict":
        return "Verdict"
    match = re.match(r"^round_(\d+)$", round_id or "")
    label = f"Round {match.group(1)}" if match else round_id
    kind = TURN_TYPES.get(turn_type)
    return label if not kind or turn_type.startswith("moderator") else f"{label} · {kind}"


def total_turns(detail: dict[str, Any]) -> int:
    """Scheduled turns plus the verdict."""
    participants = detail.get("participants") or []
    hosts = sum(1 for p in participants if p.get("role") == "moderator")
    debaters = len(participants) - hosts
    settings = detail.get("settings") or {}
    rounds = int(settings.get("num_rounds") or 1)
    if settings.get("format") == "rap_battle":  # the MC speaks once, before the verses
        return min(hosts, 1) + rounds * debaters + 1
    return rounds * (min(hosts, 1) + debaters) + 1


def format_name(detail: dict[str, Any]) -> str:
    """'Debate', 'Rap battle' (servers before formats: a debate)."""
    return (
        str((detail.get("settings") or {}).get("format") or "debate").replace("_", " ").capitalize()
    )


def round_scores(detail: dict[str, Any]) -> list[dict[str, Any]]:
    """The judge's score per round (rap battles): [{round, scores: [{speaker, speaker_id,
    score}]}], speakers in line-up order."""
    names = {
        p.get("id") or f"participant_{i}": p.get("name")
        for i, p in enumerate(detail.get("participants") or [])
    }
    out: list[dict[str, Any]] = []
    for item in (detail.get("verdict") or {}).get("rounds") or []:
        scores = item.get("scores") or {}
        out.append(
            {
                "round": item.get("round"),
                "scores": [
                    {"speaker": names.get(sid, sid), "speaker_id": sid, "score": scores[sid]}
                    for sid in names
                    if sid in scores
                ],
            }
        )
    return out


def verdict_of(detail: dict[str, Any]) -> dict[str, Any] | None:
    verdict = detail.get("verdict")
    if not verdict:
        return None
    rounds = round_scores(detail)
    return {
        **({"rounds": rounds} if rounds else {}),
        "winner": verdict.get("winner_name"),
        "winner_id": verdict.get("winner_id"),
        "is_draw": bool(verdict.get("is_draw")),
        "headline": verdict.get("headline") or "",
        "feedback": [
            {"speaker": f.get("name"), "speaker_id": f.get("speaker_id"), "text": f.get("text")}
            for f in verdict.get("feedback") or []
        ],
    }


def _speaker_line(turn: dict[str, Any], tags: dict[str, str]) -> str:
    tag = "JUDGE" if turn.get("turn_type") == "verdict" else tags.get(turn.get("speaker_id") or "")
    bits = [turn.get("speaker_name") or "Speaker"]
    if tag:
        bits.append(tag)
    bits.append(round_heading(turn.get("round_id") or "", turn.get("turn_type") or ""))
    return " · ".join(bits)


def transcript_markdown(detail: dict[str, Any], *, header: bool = True) -> str:
    """The debate as Markdown (the web app's transcript export, plus sides and the verdict)."""
    participants = detail.get("participants") or []
    tags = side_tags(participants)
    lines: list[str] = []
    if header:
        settings = detail.get("settings") or {}
        lines += [f"# {detail.get('title') or settings.get('topic') or 'Debate'}", ""]
        if settings.get("description"):
            lines += [str(settings["description"]), ""]
        if settings.get("format", "debate") != "debate":
            lines.append(f"- Format: {format_name(detail)}")
        lines += [
            f"- Status: {detail.get('status')}",
            f"- Language: {settings.get('language', 'English')}",
            f"- Rounds: {settings.get('num_rounds', 1)}",
            "",
            "## Speakers",
            "",
        ]
        for i, p in enumerate(participants):
            pid = p.get("id") or f"participant_{i}"
            lines.append(f"- **{p.get('name')}** ({tags.get(pid, '')}): `{p.get('model')}`")
        lines += ["", "---", ""]
    for turn in detail.get("turns") or []:
        lines += [f"### {_speaker_line(turn, tags)}", ""]
        error = turn.get("error")
        lines += [f"_Error: {error}_" if error else (turn.get("text") or "").strip(), ""]
    verdict = verdict_of(detail)
    if verdict and (verdict["headline"] or verdict["winner"]):
        lines += ["---", "", "## Result", ""]
        lines.append("**Draw**" if verdict["is_draw"] else f"**Winner: {verdict['winner']}**")
        if verdict["headline"]:
            lines += ["", verdict["headline"]]
        for r in verdict.get("rounds") or []:
            scores = ", ".join(f"{s['speaker']} {s['score']}" for s in r["scores"])
            lines += ["", f"- Round {r['round']}: {scores}"]
        for f in verdict["feedback"]:
            lines += ["", f"- **{f['speaker']}**: {f['text']}"]
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def digest(
    detail: dict[str, Any],
    url: str,
    *,
    turns: Literal["list", "markdown", "none"] = "list",
) -> dict[str, Any]:
    """Compact summary of a debate for `--json` and agents."""
    participants = detail.get("participants") or []
    tags = side_tags(participants)
    settings = detail.get("settings") or {}
    out: dict[str, Any] = {
        "id": detail.get("id"),
        "url": url,
        "status": detail.get("status"),
        "format": settings.get("format") or "debate",
        "topic": settings.get("topic") or detail.get("title"),
        "language": settings.get("language"),
        "rounds": settings.get("num_rounds"),
        "participants": [
            {
                "id": p.get("id") or f"participant_{i}",
                "name": p.get("name"),
                "side": tags.get(p.get("id") or f"participant_{i}"),
                "model": p.get("model"),
            }
            for i, p in enumerate(participants)
        ],
        "progress": {
            "turns_done": len(detail.get("turns") or []),
            "turns_total": total_turns(detail),
        },
        "verdict": verdict_of(detail),
        "error": detail.get("error_message"),
        "provider_cost_usd": round(float((detail.get("totals") or {}).get("cost") or 0), 6),
        "is_public": bool(detail.get("is_public")),
    }
    if turns == "list":
        out["turns"] = [
            {
                "seq": t.get("seq_index"),
                "round": t.get("round_id"),
                "type": t.get("turn_type"),
                "speaker": t.get("speaker_name"),
                "speaker_id": t.get("speaker_id"),
                "model": t.get("model_used"),
                "text": t.get("text") or "",
                "error": t.get("error"),
            }
            for t in detail.get("turns") or []
        ]
    elif turns == "markdown":
        out["transcript"] = transcript_markdown(detail, header=False)
    return out
