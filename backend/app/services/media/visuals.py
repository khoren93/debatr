"""Visual director: design charts, numbers and drawn schemes for every spoken turn.

A cheap LLM reads one turn and returns typed scene specs (`app/schemas/visuals.py`), each tied
to a phrase of the speech (`anchor`). After TTS the phrases are located in the word timestamps,
so scenes appear exactly when the idea is spoken and follow any change of voices. Everything
except the model call is pure and unit-tested.
"""

import logging
import re
from dataclasses import dataclass
from typing import Any

from pydantic import TypeAdapter, ValidationError

from app.schemas.timeline import TimelineSegment
from app.schemas.visuals import (
    ICONS,
    BarsScene,
    LineScene,
    PieScene,
    ProportionScene,
    QuoteScene,
    RebuttalScene,
    Scene,
    StatScene,
    TimelineVisual,
    item_anchors,
    parse_number,
)
from app.services.media.highlights import locate_quote

logger = logging.getLogger(__name__)

# Bump when the prompt or the scene contract changes: invalidates cached plans.
PROMPT_VERSION = "1"

WORDS_PER_SECOND = 2.6  # typical TTS pace, for the scene budget before audio exists
SECONDS_PER_SCENE = 18
MAX_SCENES_PER_TURN = 4
LEAD_MS = 250  # a scene appears slightly before its phrase
ITEM_LEAD_MS = 120
MIN_SCENE_MS = 3000  # shorter scenes flicker; such scenes are dropped
MAX_SCENE_MS = 16_000
MAX_ITEMS_SCENE_MS = 40_000  # scenes revealing elements one by one may stay longer
ITEM_GAP_MS = 3000  # a scene whose first element comes later than this starts with it
ITEM_HOLD_MS = 2500  # the last revealed element stays readable at least this long
JOIN_GAP_MS = 1500  # a scene is stretched to the next one when the gap is shorter
END_HOLD_MS = 400  # after the end of the turn audio
DEFAULT_MS: dict[str, int] = {"stat": 6500, "headline": 5500, "quote": 7500}
DEFAULT_SCENE_MS = 9000

_SCENE = TypeAdapter(Scene)
TYPE_ALIASES: dict[str, str] = {
    "number": "stat", "statistic": "stat", "kpi": "stat", "bar": "bars",
    "bar_chart": "bars", "chart": "bars", "line_chart": "line", "trend": "line",
    "pie_chart": "pie", "donut": "pie", "list": "bullets", "points": "bullets",
    "comparison": "versus", "compare": "versus", "pros_cons": "versus", "citation": "quote",
    "keyword": "headline", "punchline": "headline", "diagram": "flow", "chain": "flow",
    "cycle": "flow", "chronology": "timeline", "pictograms": "icons", "icon": "icons",
    "isotype": "proportion", "ratio": "proportion",
}  # fmt: skip


@dataclass(frozen=True)
class TurnBrief:
    seq_index: int
    speaker_id: str
    speaker_name: str
    role: str  # moderator | debater | judge
    turn_type: str
    text: str
    previous_text: str | None = None
    opponent: str | None = None  # name of the debater who spoke just before (for rebuttals)


def build_briefs(segments: list[TimelineSegment], roles: dict[str, str]) -> list[TurnBrief]:
    """One brief per spoken turn. A debater's opponent is the last other debater who spoke
    (host turns in between are skipped), so round openings can rebut too."""
    briefs: list[TurnBrief] = []
    for i, seg in enumerate(segments):
        role = roles.get(seg.speaker_id, "debater")
        rival = None
        if role == "debater":
            rival = next(
                (
                    p
                    for p in reversed(segments[:i])
                    if roles.get(p.speaker_id, "debater") == "debater"
                    and p.speaker_id != seg.speaker_id
                ),
                None,
            )
        briefs.append(
            TurnBrief(
                seq_index=seg.seq_index,
                speaker_id=seg.speaker_id,
                speaker_name=seg.speaker_name,
                role=role,
                turn_type=seg.turn_type,
                text=seg.text,
                previous_text=rival.text if rival else None,
                opponent=rival.speaker_name if rival else None,
            )
        )
    return briefs


def scene_budget(text: str, role: str) -> int:
    """How many scenes a turn deserves: about one per SECONDS_PER_SCENE of speech."""
    seconds = len(text.split()) / WORDS_PER_SECOND
    if role == "moderator":
        return 1 if seconds >= 15 else 0
    if seconds < 10:
        return 0
    limit = 2 if role == "judge" else MAX_SCENES_PER_TURN
    return max(1, min(limit, round(seconds / SECONDS_PER_SCENE)))


CATALOGUE = """\
- stat: {"type":"stat","anchor":"...","value":42,"prefix":"$","suffix":"%","label":"what the number means","trend":"up|down|null","icon":ICON}
  One striking number the speaker says.
- bars: {"type":"bars","anchor":"...","title":"...","unit":"%","items":[{"label":"...","value":10,"highlight":true}]}
  2-6 quantities the speaker compares; highlight the one the speaker stresses.
- line: {"type":"line","anchor":"...","title":"...","unit":"...","points":[{"label":"2010","value":5}]}
  3-12 points of a trend over time, every value said by the speaker.
- pie: {"type":"pie","anchor":"...","title":"...","unit":"%","items":[{"label":"...","value":30}]}
  2-5 shares of one whole.
- proportion: {"type":"proportion","anchor":"...","count":1,"total":4,"label":"...","icon":ICON}
  "1 in 4", "7 out of 10" (total at most 100).
- bullets: {"type":"bullets","anchor":"...","title":"...","items":[{"text":"...","anchor":"..."}]}
  2-4 key points of the argument, each anchored where it is said.
- versus: {"type":"versus","anchor":"...","title":"...","left":{"label":"...","items":["..."]},"right":{"label":"...","items":["..."]}}
  Two options side by side, pros vs cons, before vs after (1-4 short items per side).
- quote: {"type":"quote","anchor":"...","text":"...","author":"..."}
  Words of SOMEONE ELSE the speaker cites (a thinker, a law, a report) with that author.
  Never the speaker's own words: use headline for those.
- rebuttal: {"type":"rebuttal","anchor":"...","claim":"...","response":"...","response_anchor":"..."}
  Only when the speaker attacks the opponent's previous turn: claim = the opponent's own
  point as THEY argued it (a few words), response = the speaker's counter (a few words).
- headline: {"type":"headline","anchor":"...","text":"...","emphasis":"..."}
  The single most quotable idea, max 8 words; emphasis = 1-2 of its words to highlight.
- flow: {"type":"flow","anchor":"...","title":"...","layout":"chain|cycle","steps":[{"label":"...","icon":ICON,"anchor":"..."}]}
  Cause -> effect chain, or a vicious/virtuous cycle; 2-5 steps.
- timeline: {"type":"timeline","anchor":"...","title":"...","events":[{"date":"1969","label":"...","anchor":"..."}]}
  2-6 dated events.
- icons: {"type":"icons","anchor":"...","items":[{"icon":ICON,"label":"...","anchor":"..."}]}
  1-3 concrete things the speaker names, drawn as simple pictograms."""


# What fits each kind of turn, so a debate does not become a row of identical scenes.
TURN_HINTS: dict[str, str] = {
    "moderator": "This is the host: at most a headline (the question at stake) or the bullets "
    "of what comes next.",
    "judge": "This is the judge's verdict: prefer versus (the strengths of each side), bullets "
    "or a headline. Numbers only if the judge states scores.",
    "opening": "Opening statement: build the case — prefer bullets, flow, icons, or a chart "
    "when numbers are said. Use rebuttal only for a direct attack on the opponent's words.",
    "argument": "Main argument: prefer bullets, flow, icons, or a chart when numbers are said.",
    "rebuttal": "Rebuttal turn: rebuttal or versus fit best; a chart if numbers are said.",
    "closing": "Closing statement: prefer a headline or bullets that sum up the case; a "
    "rebuttal only if it clearly answers the opponent's last point.",
}


def build_director_messages(
    brief: TurnBrief, *, topic: str, language: str, budget: int
) -> list[dict[str, str]]:
    system = (
        "You are the visual director of a debate video show. While a speaker talks, the centre "
        "of the screen shows animated, hand-drawn scenes: charts, numbers, schemes and "
        "pictograms that illustrate exactly what is being said at that moment. You design "
        "those scenes as JSON data; the studio draws them. Reply with JSON only.\n\n"
        f"Scene types:\n{CATALOGUE}\n\n"
        f"ICON is one of: {', '.join(ICONS)}, or null.\n\n"
        "Rules:\n"
        '1. Every scene MUST have "anchor": 3-8 consecutive words copied EXACTLY from the '
        "speech (same language, same spelling) at the moment the scene should appear. Optional "
        '"until": exact words where it may disappear. Item anchors are the exact words where '
        "that item is said. Scenes follow the order of the speech and must not overlap.\n"
        "2. Data: every number must be said in the speech. Never invent, estimate, complete or "
        "score anything; a speech without numbers gets non-numeric scenes.\n"
        f"3. All visible text in {language}. Labels at most 4 words, titles at most 8 words, "
        "no Markdown, no emoji.\n"
        "4. Pick the type that fits the content best and vary types within the turn. Fewer "
        "strong scenes beat many weak ones; an empty list is fine.\n"
        '5. Return {"scenes": [...]}.'
    )
    parts = [
        f"Debate topic: {topic}",
        f"Language: {language}",
        f"Speaker: {brief.speaker_name} ({brief.role}, {brief.turn_type.replace('_', ' ')})",
    ]
    if brief.opponent and brief.previous_text:
        previous = brief.previous_text
        if len(previous) > 1500:
            previous = previous[:1500].rsplit(" ", 1)[0] + " …"
        parts.append(f"The opponent ({brief.opponent}) said just before:\n{previous}")
    else:
        parts.append("No opponent turn precedes this one: do not use rebuttal.")
    parts.append(f"Speech to illustrate:\n{brief.text}")
    hint = TURN_HINTS.get(brief.role if brief.role != "debater" else brief.turn_type)
    if hint:
        parts.append(hint)
    parts.append(
        f"Design up to {budget} scene{'s' if budget != 1 else ''}, then one spare scene of a "
        "different type at the end (the studio may swap it in to avoid repeating the previous "
        "turns)."
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": "\n\n".join(parts)}]


_DIGITS_RE = re.compile(r"\d(?:[\d\u00a0\u202f,.'\u2019 ]*\d)?")
SMALL_NUMBER = 12  # often spelled out ("one in four"), so not looked up in the text
_SCALES = (1.0, 1e3, 1e6, 1e9, 1e12)


def spoken_numbers(text: str) -> list[float]:
    """Numbers written with digits in a speech ("40%", "1,5 млн", "2 000")."""
    found: list[float] = []
    for match in _DIGITS_RE.finditer(text):
        for chunk in (match.group(0), *match.group(0).split()):
            try:
                found.append(parse_number(chunk))
            except ValueError:
                continue
    return found


def _said(value: float, spoken: list[float]) -> bool:
    if value.is_integer() and 0 <= value <= SMALL_NUMBER:
        return True
    for scale in _SCALES:
        x = abs(value) / scale
        if any(abs(x - s) <= max(1e-9, abs(s) * 0.005) for s in spoken):
            return True
    return False


def _values(scene: Any) -> list[float]:
    if isinstance(scene, StatScene):
        return [scene.value]
    if isinstance(scene, BarsScene | PieScene):
        return [i.value for i in scene.items]
    if isinstance(scene, LineScene):
        return [p.value for p in scene.points]
    if isinstance(scene, ProportionScene):
        return [scene.count] + ([] if scene.total in (10, 100) else [scene.total])
    return []


def is_grounded(scene: Any, speech: str) -> bool:
    """Numeric scenes must take their numbers from the speech (at least half of them) — the
    director may not invent statistics or scores."""
    values = _values(scene)
    if not values:
        return True
    spoken = spoken_numbers(speech)
    return sum(_said(v, spoken) for v in values) * 2 >= len(values)


def _same_person(a: str, b: str) -> bool:
    x, y = a.strip().lower(), b.strip().lower()
    return bool(x and y) and (x == y or x in y or y in x)


def parse_scenes(
    payload: Any, limit: int, *, speech: str = "", speaker: str = "", opponent: str | None = None
) -> list[Any]:
    """Valid scene specs from the director's reply; invalid scenes are skipped, not fatal.

    With `speech` the content rules are enforced too: numbers must come from the speech, a
    quote may not be the speaker's own words, a rebuttal needs the opponent's turn before."""
    items = payload.get("scenes") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        return []
    scenes: list[Any] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("type") or "").strip().lower().replace("-", "_").replace(" ", "_")
        if kind in TYPE_ALIASES:
            if kind == "cycle":
                item = {**item, "layout": "cycle"}
            kind = TYPE_ALIASES[kind]
        try:
            scene = _SCENE.validate_python({**item, "type": kind})
        except ValidationError as e:
            logger.debug("Dropping invalid %s scene: %s", kind or "untyped", e.errors()[:2])
            continue
        if speech:
            if not is_grounded(scene, speech):
                logger.debug("Dropping %s scene with numbers not in the speech", kind)
                continue
            if isinstance(scene, QuoteScene) and _same_person(scene.author, speaker):
                continue
            if isinstance(scene, RebuttalScene):
                if not opponent:
                    continue
                scene.claim_author = opponent
        scenes.append(scene)
        if len(scenes) >= limit:
            break
    return scenes


RECENT_TYPES = 3  # how far back a repeated scene type counts against a candidate


def diversify(turns: list[tuple[int, list[Any], int]]) -> dict[int, list[Any]]:
    """Pick `budget` scenes per turn out of the director's candidates (one spare each), dropping
    the ones whose type repeats the previous turns or the same turn. `turns` = [(seq_index,
    candidates in speech order, budget)] in debate order."""
    recent: list[str] = []
    picked: dict[int, list[Any]] = {}
    for seq, candidates, budget in turns:
        chosen = list(candidates)
        while len(chosen) > budget:
            kinds = [c.type for c in chosen]

            def penalty(i: int, kinds: list[str] = kinds) -> tuple[int, int]:
                kind = kinds[i]
                return (recent[-RECENT_TYPES:].count(kind) + kinds.count(kind) - 1, i)

            chosen.pop(max(range(len(chosen)), key=penalty))
        picked[seq] = chosen
        recent.extend(c.type for c in chosen)
    return picked


@dataclass
class _Placed:
    scene: Any
    start: int  # ms relative to the segment audio
    end: int
    items: list[int]
    anchored: bool


def _locate(words: list[tuple[str, int, int]], quote: str, start: int = 0) -> int | None:
    """Index (into `words`) of the quote's first word, searching from `start`."""
    if not quote.strip() or start >= len(words):
        return None
    found = locate_quote(words[start:], quote)
    return None if found is None else start + found


def _place(
    scene: Any, index: int, count: int, words: list[tuple[str, int, int]], duration: int
) -> _Placed:
    at = _locate(words, scene.anchor)
    anchored = at is not None
    if at is not None:
        start = max(0, words[at][1] - LEAD_MS)
    else:
        start = round(duration * index / max(1, count))
        at = next((i for i, w in enumerate(words) if w[1] >= start), len(words))
    end: int | None = None
    if scene.until and at < len(words):
        stop = locate_quote(words[at:], scene.until, from_end=True)
        if stop is not None:
            end = words[at + stop][2] + END_HOLD_MS
    if end is None or end - start < MIN_SCENE_MS:
        end = start + DEFAULT_MS.get(scene.type, DEFAULT_SCENE_MS)

    anchors = item_anchors(scene)
    found: list[int | None] = []
    cursor = at
    for anchor in anchors:
        hit = _locate(words, anchor, cursor) if anchor else None
        if hit is not None:
            cursor = hit + 1
            found.append(max(start, words[hit][1] - ITEM_LEAD_MS))
        else:
            found.append(None)
    items = _fill_items(found, start, end)
    if items and items[0] - start > ITEM_GAP_MS:
        start = items[0] - LEAD_MS  # the first element is said much later: appear with it
    if items:
        end = max(end, items[-1] + ITEM_HOLD_MS)
    cap = MAX_ITEMS_SCENE_MS if items else MAX_SCENE_MS
    return _Placed(scene, start, min(end, start + cap), items, anchored)


def _fill_items(found: list[int | None], start: int, end: int) -> list[int]:
    """Monotonic reveal times: located anchors are kept (unless out of order), the rest are
    interpolated between neighbours; the first element defaults to the scene start."""
    n = len(found)
    if n == 0:
        return []
    out: list[int | None] = [None] * n
    last = start
    for i, t in enumerate(found):
        if t is not None and t >= last:
            out[i] = last = t
    if out[0] is None:
        out[0] = start
    if out[-1] is None:
        out[-1] = max(start + round((end - start) * 0.6), last)
    i = 1
    while i < n:
        if out[i] is None:
            j = i
            while out[j] is None:
                j += 1
            a, b = out[i - 1], out[j]
            assert a is not None and b is not None
            for k in range(i, j):
                out[k] = a + (b - a) * (k - i + 1) // (j - i + 1)
            i = j
        i += 1
    return [t for t in out if t is not None]


def align_scenes(scenes: list[Any], segment: TimelineSegment) -> list[TimelineVisual]:
    """Turn scene specs into absolute, non-overlapping screen time within one segment."""
    words = [(w.w, w.s, w.e) for w in segment.words]
    duration = segment.end_ms - segment.start_ms
    placed = [_place(s, i, len(scenes), words, duration) for i, s in enumerate(scenes)]
    placed.sort(key=lambda p: p.start)

    kept: list[_Placed] = []
    for p in placed:
        p.end = min(p.end, duration + END_HOLD_MS)
        if kept and p.start < kept[-1].end:
            kept[-1].end = p.start
            if kept[-1].end - kept[-1].start < MIN_SCENE_MS:
                kept.pop()
        if kept and 0 < p.start - kept[-1].end < JOIN_GAP_MS:
            kept[-1].end = p.start
        if p.end - p.start >= MIN_SCENE_MS:
            kept.append(p)

    visuals: list[TimelineVisual] = []
    for i, p in enumerate(kept):
        last_item = max(p.start, p.end - 1200)
        items = [min(max(t, p.start), last_item) for t in p.items]
        visuals.append(
            TimelineVisual(
                id=f"v{segment.seq_index}_{i}",
                seq_index=segment.seq_index,
                speaker_id=segment.speaker_id,
                start_ms=segment.start_ms + p.start,
                end_ms=segment.start_ms + p.end,
                item_ms=[segment.start_ms + t for t in items],
                anchored=p.anchored,
                scene=p.scene,
            )
        )
    return visuals
