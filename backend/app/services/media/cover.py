"""AI covers: a clickbait thumbnail for a finished debate (link previews, gallery, YouTube).

An art director (COVER_DIRECTOR_MODEL) reads the episode — format, topic, the debaters with
their colours and logos, every turn but the verdict, so it cannot give the winner away — and
answers a brief: a hook of at most 4 words, the idea, the setting, one character per debater and
a centrepiece. Code turns the brief into the image prompt by a fixed template (exact text, the
site's palette, no other text, no real faces, nothing that hints at a winner), the image model
(COVER_IMAGE_MODEL) draws a 16:9 picture with the debaters' logos as reference pictures
(cover_logos), and a vision model (COVER_CHECK_MODEL) checks the spelling, stray text and the
rules; a rejected picture is drawn once more, then the build fails.

The director and the picture run on the debate's key: an own OpenRouter key pays OpenRouter
itself, otherwise the owner pays the provider cost x markup from the balance once the cover is
ready (`credits.charge_cover_sync`); the check is ours. A cover is a version (`cover_json`,
at most MAX_VERSIONS): the owner picks the current one, null shows the markup cover. Files live
in `MEDIA_ROOT/{debate}/covers/` (paths.MediaPaths.covers_dir). The pure parts (brief, parsing,
prompt, check, versions, who gets one automatically) are unit-tested; nothing here runs in tests.
"""

import base64
import json
import logging
import re
import secrets
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.redis import cover_beat_key, get_sync_redis, provider_key_key
from app.core.sync_db import get_sync_session
from app.models.models import Debate, Turn, utcnow
from app.services import usage as usage_log
from app.services.credits import charge_cover_sync, prices_of
from app.services.events import publish_event
from app.services.free_quota import is_free_model
from app.services.heartbeat import beating
from app.services.media import ffmpeg
from app.services.media.cover_logos import Logo, fetch_logo
from app.services.media.llm import complete, complete_message, extract_json, generate_image
from app.services.media.paths import MediaPaths
from app.services.media.timeline import PALETTE, short_model_name

logger = logging.getLogger(__name__)

PROMPT_VERSION = 1
MAX_VERSIONS = 5
HOOK_MAX_CHARS = 22
HOOK_MAX_WORDS = 4
BRIEF_TEXT_CHARS = 6000  # the episode's turns the director reads, in all
TURN_MIN_CHARS = 300
IMAGE_TRIES = 2  # a picture the check rejects is drawn once more
IMAGE_TIMEOUT = 300.0
CoverMode = Literal["off", "paid", "all_public"]
COVER_MODES: tuple[CoverMode, ...] = ("off", "paid", "all_public")
ACTIVE = ("queued", "running")

# Words for the speaker colours (timeline.PALETTE), for the prompt.
COLOR_WORDS: dict[str, str] = {
    "#6C9CFF": "cool blue",
    "#FF7A66": "warm coral",
    "#A78BFA": "violet",
    "#34D399": "mint green",
    "#F472B6": "pink",
    "#60A5FA": "sky blue",
    "#FB7185": "rose",
    "#FBBF24": "amber",
}


@dataclass(frozen=True)
class Show:
    verb: str
    badge: str
    about: str
    light: str


SHOWS: dict[str, Show] = {
    "debate": Show(
        verb="debate each other on stage",
        badge="AI DEBATE",
        about="Format: debate (a host opens, the AI debaters argue their sides, a judge rules).",
        light="dramatic TV debate-stage lighting with spotlights, haze and light beams",
    ),
    "rap_battle": Show(
        verb="rap-battle each other",
        badge="RAP BATTLE",
        about="Format: rap battle (an MC opens, two AI rappers trade verses, a judge scores each "
        "round).",
        light="dramatic concert lighting with spotlights, haze and sparks",
    ),
}


class CoverError(Exception):
    """A build that cannot finish; the message is for the owner."""


# --- the cast ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Rival:
    name: str
    model: str
    side: str | None
    color: str
    logo: Logo | None = None

    @property
    def color_words(self) -> str:
        return COLOR_WORDS.get(self.color.upper(), "its own colour")


def rivals_of(debate: Debate, *, logos: bool = True) -> list[Rival]:
    """The debaters in speaking order: names as on the site, the model that argued (a pinned
    Free Router model), their speaker colour and the site's logo of that model."""
    configured: list[dict[str, Any]] = (debate.config_json or {}).get("participants") or []
    out: list[Rival] = []
    for i, p in enumerate(debate.participants):
        if p.role == "moderator":
            continue
        conf = configured[i] if i < len(configured) else {}
        side = conf.get("side") if conf.get("side") in ("for", "against") else None
        model = p.model_id or ""
        out.append(
            Rival(
                name=(p.persona_name or short_model_name(model) or "Debater").strip(),
                model=model,
                side=side,
                color=PALETTE[len(out) % len(PALETTE)],
                logo=fetch_logo(model) if logos else None,
            )
        )
    return out


def show_of(conf: dict[str, Any]) -> Show:
    return SHOWS.get(str(conf.get("format") or "debate"), SHOWS["debate"])


# --- the director --------------------------------------------------------------------------------

DIRECTOR_SYSTEM = """You are the art director of Debatr, a YouTube channel where AI models debate \
each other and battle in rap. You design one episode's thumbnail, which is also its link preview.

What wins clicks:
- One idea readable in a second at phone size: the rivals, one striking prop or visual metaphor, \
a huge hook of 2-4 words.
- Conflict and curiosity: a provocative question, dare or jab taken from this episode's best \
lines. Never a summary, never the topic restated.
- Big emotion: exaggerated, cartoonish expressions and poses (mid-punchline, pointing, leaning \
in, shock, smug grin).
- Specific to this episode: its topic, its images and punchlines. No generic "AI vs AI" art.

Hard rules:
- Never hint at who won: no trophies, crowns, belts, scores, nobody looks defeated. Every rival \
looks like they are about to win.
- The rivals are personified AI models, not people: stylized characters (robots, mascots, \
creatures) whose whole design grows out of their logo and colour. No real or realistic human \
faces, no celebrities. Rivals with the same logo must be clearly different characters through \
colour, build and attitude.
- The only words in the image are the hook, the rivals' names, "VS" and the show badge: props, \
screens and signs carry no text, letters or numbers.
- The hook is in the episode's language, ALL CAPS, at most 4 words and 22 characters, and makes \
sense without the video.
- Nothing hateful, violent, sexual or defaming a brand: playful trash talk only.

Answer with JSON only, no prose:
{"hook": "...", "concept": "the idea of the thumbnail in one sentence (in English)",
 "setting": "where it happens, light and atmosphere, one sentence (in English)",
 "rivals": ["one entry per rival, in the given order: the rival as a character: build, outfit, \
pose, expression; one or two sentences (in English)"],
 "centerpiece": "the prop or metaphor between or around them, without any text; one sentence \
(in English)"}"""

SIDES = {"for": ", argues for the topic", "against": ", argues against it"}


def _clip(text: str, limit: int) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else f"{flat[: limit - 1].rstrip()}…"


def episode_brief(conf: dict[str, Any], rivals: list[Rival], turns: list[Turn]) -> str:
    """What the director reads: format, topic, cast and the turns, never the verdict (the judge
    is left out, so the cover cannot give the winner away). Long episodes are cut per turn."""
    show = show_of(conf)
    lines = [
        show.about,
        f"Topic: {conf.get('topic') or ''}",
        f"Language: {conf.get('language') or 'English'}",
        f"Rivals ({len(rivals)}, in this order):",
    ]
    for r in rivals:
        logo = f"logo: {r.logo.description}" if r.logo else "no logo: invent a glowing emblem"
        lines.append(
            f"- {r.name} (model {r.model}{SIDES.get(r.side or '', '')}), "
            f"colour {r.color} ({r.color_words}), {logo}"
        )
    spoken = [
        t for t in turns if t.turn_type != "verdict" and not t.error and (t.text or "").strip()
    ]
    per_turn = max(TURN_MIN_CHARS, BRIEF_TEXT_CHARS // max(1, len(spoken)))
    lines.append("\nThe episode:")
    for turn in spoken:
        lines.append(f"[{turn.speaker_name}, {turn.round_id}]\n{_clip(turn.text, per_turn)}")
    return "\n".join(lines)


@dataclass(frozen=True)
class Brief:
    hook: str
    concept: str
    setting: str
    rivals: list[str]
    centerpiece: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "hook": self.hook,
            "concept": self.concept,
            "setting": self.setting,
            "rivals": list(self.rivals),
            "centerpiece": self.centerpiece,
        }


def fit_hook(text: str) -> str:
    """ALL CAPS, at most HOOK_MAX_WORDS words and HOOK_MAX_CHARS characters (words dropped from
    the end, a single long word cut); "" when nothing is left."""
    words = " ".join(str(text or "").replace('"', "").split()).upper().split()[:HOOK_MAX_WORDS]
    while words and len(" ".join(words)) > HOOK_MAX_CHARS and len(words) > 1:
        words.pop()
    return " ".join(words)[:HOOK_MAX_CHARS].strip()


def parse_brief(text: str, rivals: int) -> Brief:
    """The director's answer, checked: every field there, one character per rival, the hook
    within its limits. Raises ValueError for an answer that cannot be used."""
    try:
        data = extract_json(text)
    except (ValueError, json.JSONDecodeError) as e:
        raise ValueError(f"no JSON in the brief: {e}") from e
    if not isinstance(data, dict):
        raise ValueError("the brief is not an object")
    fields = {k: " ".join(str(data.get(k) or "").split()) for k in ("concept", "setting")}
    fields["centerpiece"] = " ".join(str(data.get("centerpiece") or "").split())
    characters = data.get("rivals")
    if not isinstance(characters, list) or len(characters) != rivals:
        raise ValueError(f"the brief describes {len(characters or [])} rivals, not {rivals}")
    hook = fit_hook(str(data.get("hook") or ""))
    if not hook or not all(fields.values()):
        raise ValueError("the brief misses a field")
    return Brief(
        hook=hook,
        concept=fields["concept"][:600],
        setting=fields["setting"][:400],
        rivals=[" ".join(str(c).split())[:500] for c in characters],
        centerpiece=fields["centerpiece"][:400],
    )


# --- the prompt ----------------------------------------------------------------------------------

PROMPT = """YouTube thumbnail, 16:9 landscape, for an episode of "Debatr", a show where AI models \
{verb}. Idea: {concept}

Composition (it must read at phone size): {layout}; {centerpiece_short}; a huge hook across the \
top. Strong depth, clean silhouettes, nothing small or busy. Keep the hook, the names and the \
badge inside the middle 84% of the height: 8% at the top and at the bottom may be cropped. Keep \
the top-right corner (a fifth of the width, a sixth of the height) free of text: the site puts \
its own badges there.

{rivals}{same_logo}
Centre: {centerpiece}
Setting: {setting}

Text: render exactly these words, spelled exactly, and no other text anywhere:
1. "{hook}" is the headline{script}: gigantic heavy condensed sans-serif, ALL CAPS, white with a \
thick black outline and a lime (#D9FF3D) drop shadow, slightly tilted, across the top third.
2. {names}, {vs}.
3. A small lime (#D9FF3D) pill badge with black text "{badge}" in the top-left corner.

Style: premium cinematic 3D character render, glossy and saturated, like a blockbuster animated \
movie poster; {light}; very high contrast against a near-black (#0A0B0F) background; lime \
#D9FF3D accents.

Avoid: any other text, letters or numbers; watermarks; misspellings; real people or realistic \
human faces; trophies, crowns, belts, scores or anything that suggests a winner; weapons, blood; \
extra logos or brands."""

POSITIONS: dict[int, tuple[str, ...]] = {
    1: ("centre-left",),
    2: ("left", "right"),
    3: ("left", "middle", "right"),
    4: ("far left", "centre-left", "centre-right", "far right"),
}
LAYOUTS: dict[int, str] = {
    1: "the rival stands large and waist-up on the left, facing the viewer",
    2: "the two rivals face off from the left and right thirds, waist-up and large",
    3: "the three rivals stand in a row across the frame, waist-up and large, turned to each other",
    4: "the four rivals stand in a row across the frame, waist-up, shoulder to shoulder",
}

LATIN = re.compile(r"^[\sA-Za-z0-9.,!?'\u2019\-:&]*$")


def references(rivals: list[Rival]) -> list[Logo]:
    """The distinct logos, in order: reference picture n is the n-th of them."""
    seen: dict[str, Logo] = {}
    for r in rivals:
        if r.logo is not None and r.logo.name not in seen:
            seen[r.logo.name] = r.logo
    return list(seen.values())


def build_prompt(brief: Brief, rivals: list[Rival], conf: dict[str, Any]) -> str:
    show = show_of(conf)
    n = max(1, min(len(rivals), 4))
    positions = POSITIONS[n]
    refs = [logo.name for logo in references(rivals)]
    lines: list[str] = []
    for i, (r, character) in enumerate(zip(rivals[:4], brief.rivals, strict=False)):
        where = positions[i].capitalize()
        if r.logo is not None:
            emblem = (
                f"Its emblem is the logo in reference image {refs.index(r.logo.name) + 1} "
                f"({r.logo.description}): reproduce that logo faithfully on the character "
                "(chest, head or microphone), same shape and colours."
            )
        else:
            emblem = (
                f"Its emblem is a glowing abstract symbol in {r.color_words}, invented for it, "
                "without letters."
            )
        lines.append(
            f"{where} rival, {r.name}, lit with {r.color_words} ({r.color}) rim light: "
            f"{character.rstrip('.')}. {emblem}"
        )
    logos = [r.logo.name for r in rivals if r.logo is not None]
    same_logo = (
        "\nSeveral rivals carry the same logo: keep them unmistakably different characters "
        "through colour, build and pose."
        if len(logos) != len(set(logos))
        else ""
    )
    language = str(conf.get("language") or "English")
    script = (
        ""
        if LATIN.match(brief.hook)
        else f", in {language} (copy every character exactly as given, accents and script included)"
    )
    names = ", ".join(
        f'"{r.name.upper()}" in bold under the {positions[i]} rival in {r.color_words}'
        for i, r in enumerate(rivals[:4])
    )
    vs = 'a glowing "VS" between them' if n == 2 else 'glowing "VS" marks between neighbours'
    if n == 1:
        vs = "no VS mark"
    centerpiece = brief.centerpiece.rstrip(".")
    short = centerpiece[0].lower() + centerpiece[1:] if len(centerpiece) < 90 else "the centrepiece"
    return PROMPT.format(
        verb=show.verb,
        concept=brief.concept,
        layout=LAYOUTS[n],
        centerpiece_short=f"{short} in the centre",
        rivals="\n".join(lines),
        same_logo=same_logo,
        centerpiece=brief.centerpiece,
        setting=brief.setting,
        hook=brief.hook,
        script=script,
        names=names,
        vs=vs,
        badge=show.badge,
        light=show.light,
    )


# --- the check -----------------------------------------------------------------------------------


def check_messages(
    image_jpeg: bytes, hook: str, names: list[str], badge: str
) -> list[dict[str, Any]]:
    wanted = ", ".join(f'"{n.upper()}"' for n in names)
    text = (
        "You check a YouTube thumbnail before it is published. It should show the headline "
        f'"{hook}" spelled exactly, character by character, the names {wanted}, "VS" and a badge '
        f'"{badge}". Report a problem only for: the headline or a name misspelled, garbled or '
        "missing; other readable words, letters or numbers (the characters' own logos and "
        "small decorative marks are fine); a realistic human face or a real person; a trophy, "
        "crown, belt, score or anything that says who won; gore, nudity or hate symbols. "
        'Reply with JSON only: {"ok": true or false, "problems": ["<a few words each>"]}'
    )
    url = f"data:image/jpeg;base64,{base64.b64encode(image_jpeg).decode()}"
    return [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": text},
                {"type": "image_url", "image_url": {"url": url}},
            ],
        }
    ]


def parse_check(text: str) -> tuple[bool, list[str]]:
    """(passed, problems). An answer that cannot be read passes: the check guards quality, and
    the prompt already forbids what it looks for."""
    try:
        data = extract_json(text)
    except (ValueError, json.JSONDecodeError):
        return True, ["unreadable check"]
    if not isinstance(data, dict):
        return True, ["unreadable check"]
    problems = [str(p)[:200] for p in data.get("problems") or [] if str(p).strip()]
    return data.get("ok") is not False and not (data.get("ok") is None and problems), problems


# --- versions (pure, on cover_json) --------------------------------------------------------------


def versions(state: dict[str, Any] | None) -> list[dict[str, Any]]:
    return [v for v in (state or {}).get("versions") or [] if isinstance(v, dict) and v.get("id")]


def current_version(state: dict[str, Any] | None) -> dict[str, Any] | None:
    current = (state or {}).get("current")
    return next((v for v in versions(state) if v["id"] == current), None) if current else None


def add_version(
    state: dict[str, Any], version: dict[str, Any], limit: int = MAX_VERSIONS
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """The state with `version` as the current one; the oldest others past `limit` drop out
    (returned, so their files can go)."""
    kept = [*versions(state), version]
    removed: list[dict[str, Any]] = []
    while len(kept) > limit:
        removed.append(kept.pop(0))
    return {**state, "versions": kept, "current": version["id"]}, removed


def select_version(state: dict[str, Any], version_id: str | None) -> dict[str, Any]:
    """Make a version current (None: the markup cover). Raises KeyError for an unknown id."""
    if version_id is not None and all(v["id"] != version_id for v in versions(state)):
        raise KeyError(version_id)
    return {**state, "current": version_id}


def remove_version(state: dict[str, Any], version_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Drop a version; when it was current, the newest one left takes its place."""
    found = next((v for v in versions(state) if v["id"] == version_id), None)
    if found is None:
        raise KeyError(version_id)
    kept = [v for v in versions(state) if v["id"] != version_id]
    current = state.get("current")
    if current == version_id:
        current = kept[-1]["id"] if kept else None
    return {**state, "versions": kept, "current": current}, found


def version_files(version: dict[str, Any]) -> list[str]:
    files = version.get("files") or {}
    return [str(f) for f in files.values() if isinstance(f, str) and f]


# --- who gets one --------------------------------------------------------------------------------


def free_run_of(conf: dict[str, Any]) -> bool:
    """Whether the run was a free one (system key, free models, no balance): stored at start
    (`billing.free_run`); older rows by their key and models."""
    billing = conf.get("billing") or {}
    if "free_run" in billing:
        return bool(billing["free_run"])
    models = [str(p.get("model_id") or "") for p in conf.get("participants") or []]
    return not billing.get("own_key") and bool(models) and all(map(is_free_model, models))


def cover_expected(cover: bool | None, mode: str, *, free_run: bool) -> bool:
    """Whether a new run will get a cover it pays for (the estimate adds its price)."""
    return mode != "off" and cover is not False and not free_run


AutoCover = Literal["own", "paid", "free"]


def auto_cover(
    conf: dict[str, Any],
    *,
    mode: str,
    moderation: str,
    is_public: bool,
    balance: float,
    moderation_source: str | None = None,
) -> AutoCover | None:
    """Whether a debate that just completed gets a cover and who pays: its own OpenRouter key,
    the owner's balance, or nobody (`all_public`: a free public debate, at the operator's
    cost). Not when the config says no, nor for debates the gallery check rejected or flagged
    for what they say; one flagged only because the check could not run (`fallback`, common on
    free models) gets its cover and stays private until a moderator decides, cover included."""
    if mode not in ("paid", "all_public") or conf.get("cover") is False:
        return None
    if moderation == "rejected" or (moderation == "flagged" and moderation_source != "fallback"):
        return None
    if (conf.get("billing") or {}).get("own_key"):
        return "own"
    if not free_run_of(conf):
        return "paid" if balance > 0 else None
    return "free" if mode == "all_public" and is_public else None


def queued_state(
    state: dict[str, Any] | None,
    *,
    source: str,
    own_key: bool,
    free: bool,
    prices: dict[str, float],
    hook: str | None = None,
) -> dict[str, Any]:
    """cover_json of a build about to be queued: what it is for and who pays (`request`)."""
    request = {
        "source": source,  # auto | owner | admin
        "own_key": own_key,
        "free": free,
        "hook": fit_hook(hook) if hook else None,
        "prices": prices,
        "queued_at": utcnow().isoformat(),
    }
    return {**(state or {}), "request": request, "error": None}


def queue_auto_cover(db: Session, debate: Debate, who: AutoCover, prices: dict[str, float]) -> None:
    """Queue the cover of a debate that just completed (orchestrator.finish_debate_job; an own
    key is still in Redis, kept for it). Never raises."""
    try:
        debate.cover_json = queued_state(
            debate.cover_json,
            source="auto",
            own_key=who == "own",
            free=who == "free",
            prices=prices,
        )
        debate.cover_status = "queued"
        db.commit()
        from app.services import queue_manager  # imports nothing of the worker

        queue_manager.enqueue_cover_build(str(debate.id))
    except Exception:
        logger.exception("Failed to queue the cover of %s", debate.id)
        db.rollback()
        debate.cover_status = "error"
        debate.cover_json = {**(debate.cover_json or {}), "error": "Job queue unavailable"}
        db.commit()


# --- the build -----------------------------------------------------------------------------------


@dataclass
class Drawn:
    image: bytes
    brief: Brief
    prompt: str
    billed_usd: float = 0.0  # director + pictures (the owner's part, before the markup)
    check_usd: float = 0.0  # vision checks (ours)
    tries: int = 0
    problems: list[str] = field(default_factory=list)


def _cost(usage: dict[str, Any] | None) -> float:
    try:
        return float((usage or {}).get("cost") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _direct(
    conf: dict[str, Any], rivals: list[Rival], turns: list[Turn], api_key: str | None
) -> tuple[Brief, float]:
    messages = [
        {"role": "system", "content": DIRECTOR_SYSTEM},
        {"role": "user", "content": episode_brief(conf, rivals, turns)},
    ]
    spent = 0.0
    error: Exception | None = None
    for _ in range(2):
        text, _annotations, usage = complete_message(
            settings.COVER_DIRECTOR_MODEL,
            messages,
            purpose="cover_director",
            api_key=api_key,
            max_tokens=1500,
        )
        spent += _cost(usage)
        try:
            return parse_brief(text, len(rivals)), spent
        except ValueError as e:
            error = e
            logger.info("Cover brief unusable (%s), asking again", e)
    raise CoverError(f"The art director gave no usable brief ({error})")


def _check(
    image_jpeg: bytes, hook: str, rivals: list[Rival], badge: str
) -> tuple[bool, list[str], float]:
    model = settings.COVER_CHECK_MODEL or settings.MEDIA_VISUALS_MODEL or settings.VERDICT_MODEL
    try:
        text, usage = complete(
            model,
            check_messages(image_jpeg, hook, [r.name for r in rivals], badge),
            purpose="cover_check",
            max_tokens=300,
        )
    except Exception as e:  # the check guards quality: without it the picture stands
        logger.warning("Cover check failed (%s): keeping the picture", e)
        return True, ["check unavailable"], 0.0
    ok, problems = parse_check(text)
    return ok, problems, _cost(usage)


def draw_cover(debate: Debate, *, hook: str | None, api_key: str | None, work: Path) -> Drawn:
    """Brief, prompt, picture and check (a rejected picture once more). Raises CoverError."""
    conf: dict[str, Any] = debate.config_json or {}
    rivals = rivals_of(debate)
    if not rivals:
        raise CoverError("The debate has no debaters")
    brief, spent = _direct(conf, rivals, list(debate.turns), api_key)
    if hook:
        brief = Brief(
            hook=fit_hook(hook) or brief.hook,
            concept=brief.concept,
            setting=brief.setting,
            rivals=brief.rivals,
            centerpiece=brief.centerpiece,
        )
    prompt = build_prompt(brief, rivals, conf)
    refs = [
        f"data:image/png;base64,{base64.b64encode(logo.png).decode()}"
        for logo in references(rivals)
    ]
    drawn = Drawn(image=b"", brief=brief, prompt=prompt, billed_usd=spent)
    badge = show_of(conf).badge
    for attempt in range(1, IMAGE_TRIES + 1):
        data, usage = generate_image(
            settings.COVER_IMAGE_MODEL,
            prompt,
            purpose="cover",
            resolution=None,
            quality=settings.COVER_IMAGE_QUALITY or None,
            references=refs,
            api_key=api_key,
            fallback_cost=settings.COVER_PRICE_USD,
            timeout=IMAGE_TIMEOUT,
        )
        drawn.billed_usd += _cost(usage) or settings.COVER_PRICE_USD
        drawn.tries = attempt
        raw = work / f"try{attempt}.img"
        raw.write_bytes(data)
        preview = work / f"try{attempt}.jpg"
        ffmpeg.fill_jpeg(raw, preview, width=1280, height=720, quality=4)
        ok, problems, check_cost = _check(preview.read_bytes(), brief.hook, rivals, badge)
        drawn.check_usd += check_cost
        drawn.problems = problems
        if ok:
            drawn.image = data
            return drawn
        logger.info("Cover try %d of %s rejected: %s", attempt, debate.id, "; ".join(problems))
    raise CoverError(f"The cover failed its check twice ({'; '.join(drawn.problems)[:200]})")


def store_files(paths: MediaPaths, version_id: str, image: bytes) -> dict[str, str]:
    """The picture in the sizes the site uses, by name under `covers/`."""
    paths.covers_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=paths.covers_dir) as tmp:
        raw = Path(tmp) / "raw.img"
        raw.write_bytes(image)
        full = ffmpeg.to_web_image(raw, paths.covers_dir / version_id, max_width=1536)
        small = ffmpeg.to_web_image(raw, paths.covers_dir / f"{version_id}-768", max_width=768)
        yt = paths.covers_dir / f"{version_id}-yt.jpg"
        ffmpeg.fill_jpeg(raw, yt, width=1280, height=720, quality=2)
        og = paths.covers_dir / f"{version_id}-og.jpg"
        # Link previews: WhatsApp drops pictures past ~300 KB (q5 gives ~150-200 KB).
        ffmpeg.fill_jpeg(raw, og, width=1200, height=630, quality=5)
    return {"full": full.name, "small": small.name, "yt": yt.name, "og": og.name}


def delete_files(paths: MediaPaths, version: dict[str, Any]) -> None:
    for name in version_files(version):
        if "/" not in name and not name.startswith("."):
            (paths.covers_dir / name).unlink(missing_ok=True)


def new_version_id() -> str:
    return secrets.token_hex(6)


def _iso(moment: Any) -> str:
    return moment.isoformat()


def set_cover_state(
    db: Session, debate: Debate, *, status: str, publish: bool = True, **updates: Any
) -> None:
    state = dict(debate.cover_json or {})
    state.update(updates)
    debate.cover_status = status
    debate.cover_json = state  # reassign so SQLAlchemy sees the change
    db.commit()
    if publish:
        publish_event(
            str(debate.id),
            "cover_progress",
            {"debate_id": str(debate.id), "status": status, "error": state.get("error")},
        )


def _own_key(debate_id: str) -> str | None:
    try:
        value = get_sync_redis().get(provider_key_key(debate_id))
    except Exception:
        logger.warning("Could not read the OpenRouter key of %s", debate_id)
        return None
    if value is None:
        return None
    return value.decode() if isinstance(value, bytes) else str(value)


def _drop_own_key(debate: Debate) -> None:
    """The debate's own key was kept for the cover (no run of it can be going: it finished)."""
    if debate.status in ("queued", "running"):
        return
    try:
        get_sync_redis().delete(provider_key_key(str(debate.id)))
    except Exception:
        logger.warning("Could not drop the OpenRouter key of %s", debate.id)


@beating(cover_beat_key)
@usage_log.attributed
def build_cover_job(debate_id: str) -> None:
    with get_sync_session() as db:
        debate = db.get(Debate, uuid.UUID(debate_id))
        if debate is None or debate.cover_status != "queued":
            return
        request: dict[str, Any] = dict((debate.cover_json or {}).get("request") or {})
        set_cover_state(db, debate, status="running", error=None, started_at=_iso(utcnow()))
        own = bool(request.get("own_key"))
        key = _own_key(debate_id) if own else None
        if own and not key:
            set_cover_state(
                db,
                debate,
                status="error",
                error="Your OpenRouter key expired before the cover was drawn: generate it again",
            )
            return
        paths = MediaPaths(debate_id)
        version_id = new_version_id()
        try:
            paths.covers_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(dir=paths.covers_dir) as work:
                drawn = draw_cover(debate, hook=request.get("hook"), api_key=key, work=Path(work))
                files = store_files(paths, version_id, drawn.image)
        except CoverError as e:
            logger.warning("Cover of %s failed: %s", debate_id, e)
            set_cover_state(
                db, debate, status="error", error=str(e)[:300], finished_at=_iso(utcnow())
            )
            return
        except Exception:
            logger.exception("Cover of %s failed", debate_id)
            set_cover_state(
                db,
                debate,
                status="error",
                error="The cover could not be drawn: try again",
                finished_at=_iso(utcnow()),
            )
            return
        finally:
            if own:
                _drop_own_key(debate)

        version = {
            "id": version_id,
            "files": files,
            "hook": drawn.brief.hook,
            "brief": drawn.brief.as_dict(),
            "prompt_version": PROMPT_VERSION,
            "cost_usd": round(drawn.billed_usd, 6),
            "check_usd": round(drawn.check_usd, 6),
            "tries": drawn.tries,
            "source": str(request.get("source") or "owner"),
            "own_key": own,
            "created_at": _iso(utcnow()),
        }
        db.refresh(debate)  # the owner may have picked another version meanwhile
        state, removed = add_version(dict(debate.cover_json or {}), version)
        for old in removed:
            delete_files(paths, old)
        debate.cover_json = state
        db.commit()  # the picture is kept whatever happens to the charge
        if not own and not request.get("free"):
            try:
                markup = prices_of(request).markup
                charge_cover_sync(
                    db, debate, usd=drawn.billed_usd, version_id=version_id, markup=markup
                )
            except Exception:
                logger.exception("Failed to charge the cover of %s", debate_id)
                db.rollback()
        set_cover_state(
            db,
            debate,
            status="ready",
            error=None,
            request=None,
            finished_at=_iso(utcnow()),
        )
        logger.info("Cover %s of %s ready (%d tries)", version_id, debate_id, drawn.tries)
