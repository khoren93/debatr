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
    UNORDERED_ITEMS,
    BarsScene,
    BulletsScene,
    DefinitionScene,
    DirectorScene,
    FlowScene,
    HeadlineScene,
    IconsScene,
    ImageScene,
    LineScene,
    MapScene,
    MatrixScene,
    PieScene,
    ProportionScene,
    QuoteScene,
    RankingScene,
    RebuttalScene,
    ScaleScene,
    ScoreboardScene,
    SketchScene,
    StatScene,
    TimelineScene,
    TimelineVisual,
    VennScene,
    VersusScene,
    item_anchors,
    parse_number,
)
from app.services.media.highlights import locate_quote, normalize_token

logger = logging.getLogger(__name__)

# Bump when the prompt or the scene contract changes: invalidates stored plans.
PROMPT_VERSION = "3"

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
DEFAULT_MS: dict[str, int] = {"stat": 6500, "headline": 5500, "quote": 7500, "definition": 8000}
DEFAULT_SCENE_MS = 9000

_SCENE = TypeAdapter(DirectorScene)
TYPE_ALIASES: dict[str, str] = {
    "number": "stat", "statistic": "stat", "kpi": "stat", "bar": "bars",
    "bar_chart": "bars", "chart": "bars", "line_chart": "line", "trend": "line",
    "pie_chart": "pie", "donut": "pie", "list": "bullets", "points": "bullets",
    "comparison": "versus", "compare": "versus", "pros_cons": "versus", "citation": "quote",
    "keyword": "headline", "punchline": "headline", "diagram": "flow", "chain": "flow",
    "cycle": "flow", "chronology": "timeline", "pictograms": "icons", "icon": "icons",
    "isotype": "proportion", "ratio": "proportion", "balance": "scale", "scales": "scale",
    "weighing": "scale", "tradeoff": "scale", "trade_off": "scale", "quadrant": "matrix",
    "2x2": "matrix", "matrix_2x2": "matrix", "overlap": "venn", "intersection": "venn",
    "venn_diagram": "venn", "rank": "ranking", "top": "ranking", "top_list": "ranking",
    "leaderboard": "ranking", "pyramid": "ranking", "term": "definition", "glossary": "definition",
    "dictionary": "definition", "world_map": "map", "geo": "map", "countries": "map",
    "drawing": "sketch", "illustration": "sketch", "doodle": "sketch", "picture": "image",
    "photo": "image", "photograph": "image",
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
    debaters: tuple[str, ...] = ()  # everyone's exact names, for labels such as scale pans
    hints: tuple[tuple[str, str], ...] = ()  # the speaker's [visual: …] requests: (text, after)
    images: bool = False  # the show may use photos / AI pictures

    @property
    def hint_text(self) -> str:
        """The speaker's requests as text: their numbers count as the speaker's words."""
        return " ".join(text for text, _after in self.hints)


def build_briefs(segments: list[TimelineSegment], roles: dict[str, str]) -> list[TurnBrief]:
    """One brief per spoken turn. A debater's opponent is the last other debater who spoke
    (host turns in between are skipped), so round openings can rebut too."""
    debaters = tuple(
        dict.fromkeys(
            s.speaker_name for s in segments if roles.get(s.speaker_id, "debater") == "debater"
        )
    )
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
                debaters=debaters,
            )
        )
    return briefs


def scene_budget(text: str, role: str, hints: int = 0) -> int:
    """How many scenes a turn deserves: about one per SECONDS_PER_SCENE of speech, and at least
    one per visual the speaker asked for."""
    seconds = len(text.split()) / WORDS_PER_SECOND
    if role == "moderator":
        return 1 if seconds >= 15 else 0
    if seconds < 10:
        return min(hints, 1) if seconds >= 5 else 0
    limit = 2 if role == "judge" else MAX_SCENES_PER_TURN
    return max(1, hints, min(limit, round(seconds / SECONDS_PER_SCENE)))


CATALOGUE = """\
- stat: {"type":"stat","anchor":"...","value":42,"prefix":"$","suffix":"%","label":"what the number means","trend":"up|down|null","icon":ICON}
  One striking number the speaker says. "prices fell 90% in ten years" -> value 90, suffix "%", trend "down".
- bars: {"type":"bars","anchor":"...","title":"...","unit":"%","items":[{"label":"...","value":10,"highlight":true}]}
  2-6 quantities the speaker compares; highlight the one the speaker stresses. "Denmark pays 40 cents, Germany 35, the US 15" -> three bars.
- line: {"type":"line","anchor":"...","title":"...","unit":"...","points":[{"label":"2010","value":5}]}
  3-12 points of a trend over time, every value said by the speaker. "2 million in 2010, 5 in 2015, 14 in 2023".
- pie: {"type":"pie","anchor":"...","title":"...","unit":"%","items":[{"label":"...","value":30}]}
  2-5 shares of one whole. "70% of the budget goes to pensions, 20% to health".
- proportion: {"type":"proportion","anchor":"...","count":1,"total":4,"label":"...","icon":ICON}
  "1 in 4", "7 out of 10" (total at most 100).
- ranking: {"type":"ranking","anchor":"...","title":"...","layout":"list|pyramid","unit":"...","items":[{"label":"...","value":null,"anchor":"..."}]}
  2-6 items in rank order, #1 first, even if the speaker counts down. "The biggest emitters are China, then the US, then India". Values only if said for every item; "pyramid" for a hierarchy (needs, power, a food chain).
- map: {"type":"map","anchor":"...","title":"...","unit":"%","regions":[{"code":"NOR","label":"...","value":null,"anchor":"..."}]}
  1-8 countries the speaker names. code = ISO 3166-1 alpha-3 ("USA", "DEU", "CHN") or "EU"; label = the name in the debate language; value only if a number is said for every country. "Norway, Sweden and Finland already did it".
- bullets: {"type":"bullets","anchor":"...","title":"...","items":[{"text":"...","anchor":"..."}]}
  2-4 key points of the argument, each anchored where it is said. "First... Second... Third...".
- versus: {"type":"versus","anchor":"...","title":"...","left":{"label":"...","items":["..."]},"right":{"label":"...","items":["..."]}}
  Two options side by side, pros vs cons, before vs after (1-4 short items per side). "Remote work saves the commute; the office builds the team".
- scale: {"type":"scale","anchor":"...","title":"...","left":{"label":"...","items":[{"text":"...","anchor":"..."}]},"right":{"label":"...","items":[{"text":"...","anchor":"..."}]},"heavier":"left|right|even"}
  Arguments weighed against each other on a balance, 1-3 per pan; heavier = the side the speaker says wins. "Yes, it is costly and slow, but it is clean and reliable, and that outweighs it" -> left costs, right benefits, heavier "right".
- matrix: {"type":"matrix","anchor":"...","title":"...","x_axis":"...","y_axis":"...","quadrants":["top-left","top-right","bottom-left","bottom-right"],"items":[{"label":"...","x":8,"y":2,"highlight":true,"anchor":"..."}]}
  1-6 options placed on two criteria, x and y from 0 (low) to 10 (high); quadrants optional (four labels or omit). "Wind is cheap and clean, coal is cheap but dirty, nuclear is clean but costly" -> x_axis cost, y_axis cleanliness.
- venn: {"type":"venn","anchor":"...","title":"...","sets":[{"label":"...","anchor":"..."}],"overlap":"...","overlap_anchor":"..."}
  2-3 ideas and what they share. "Both science and religion try to explain where we come from" -> sets Science, Religion; overlap "Our origins".
- definition: {"type":"definition","anchor":"...","term":"...","kind":"...","text":"...","source":"..."}
  A key term the speaker defines or redefines. "By basic income I mean a monthly payment to every citizen, no strings attached". kind like "noun" or "legal term" (optional); source only if the speaker cites one.
- flow: {"type":"flow","anchor":"...","title":"...","layout":"chain|cycle","steps":[{"label":"...","icon":ICON,"anchor":"..."}]}
  Cause -> effect chain, or a vicious/virtuous cycle; 2-5 steps. "Cheaper energy means cheaper factories, which means more jobs".
- timeline: {"type":"timeline","anchor":"...","title":"...","events":[{"date":"1969","label":"...","anchor":"..."}]}
  2-6 dated events. "In 1990... by 2008... today...".
- quote: {"type":"quote","anchor":"...","text":"...","author":"..."}
  Words of SOMEONE ELSE the speaker cites (a thinker, a law, a report) with that author.
  Never the speaker's own words: use headline for those.
- rebuttal: {"type":"rebuttal","anchor":"...","claim":"...","response":"...","response_anchor":"..."}
  Only when the speaker attacks the opponent's previous turn: claim = the opponent's own
  point as THEY argued it (a few words), response = the speaker's counter (a few words).
- headline: {"type":"headline","anchor":"...","text":"...","emphasis":"..."}
  The single most quotable idea, max 8 words; emphasis = 1-2 of its words to highlight.
- icons: {"type":"icons","anchor":"...","items":[{"icon":ICON,"label":"...","anchor":"..."}]}
  1-3 concrete things the speaker names, drawn as simple pictograms. "Cars, planes and ships all burn oil".
- sketch: {"type":"sketch","anchor":"...","title":"...","subject":"...","caption":"..."}
  A hand-drawn illustration of ONE concrete object, scene or metaphor the speaker evokes; an
  illustrator draws it from "subject" (in English, concrete and drawable, e.g. "a piggy bank
  melting in the sun", "an offshore wind turbine"); never people's faces, text or logos.
  caption = a few words in the debate language. "Our savings melt like ice in the sun"."""

IMAGE_ENTRY = """- image: {"type":"image","anchor":"...","title":"...","subject":"...","caption":"..."}
  A real-world picture of a place, object or phenomenon the speaker names ("subject" in English,
  e.g. "offshore wind farm at sea", "coal power plant with cooling towers"). Never a person, a
  crowd close-up, a logo, a brand, a chart or text. At most one per turn. "The Great Barrier Reef is bleaching"."""

# Which type fits which content, so the director does not default to bullets.
CHOOSING = (
    "numbers -> stat, bars, line, pie or proportion; an order or a top list -> ranking; "
    "countries -> map; a key term explained -> definition; costs against benefits, which side "
    "outweighs -> scale; options rated on two criteria -> matrix; what two ideas share -> venn; "
    "two sides in parallel -> versus; causes and effects -> flow; dates -> timeline; someone "
    "else's words -> quote; the opponent's point answered -> rebuttal; the punchline -> "
    "headline; a vivid object or metaphor -> sketch; concrete things -> icons; a list of points "
    "-> bullets (only when nothing above fits)"
)
CHOOSING_IMAGE = "; a real place or thing worth seeing -> image"


# What fits each kind of turn, so a debate does not become a row of identical scenes.
TURN_HINTS: dict[str, str] = {
    "moderator": "This is the host: at most a headline (the question at stake), a definition "
    "of the key term, or the bullets of what comes next.",
    "judge": "This is the judge's verdict: prefer scale (which side outweighs), versus (the "
    "strengths of each side) or bullets. Numbers only if the judge states scores. The studio "
    "shows the winner on its own scoreboard: do not design a scene announcing the winner.",
    "opening": "Opening statement: build the case — prefer flow, definition, map, a sketch of a "
    "vivid image the speaker evokes, icons, bullets, or a chart when numbers are said. Use "
    "rebuttal only for a direct attack on the opponent's words.",
    "argument": "Main argument: prefer flow, scale, matrix, map, a sketch, bullets, or a chart "
    "when numbers are said.",
    "rebuttal": "Rebuttal turn: rebuttal, scale or versus fit best; a chart if numbers are said.",
    "closing": "Closing statement: prefer a headline, scale or bullets that sum up the case; a "
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
        f"Scene types:\n{CATALOGUE}\n{IMAGE_ENTRY if brief.images else ''}\n"
        f"ICON is one of: {', '.join(ICONS)}, or null.\n\n"
        "Rules:\n"
        '1. Every scene MUST have "anchor": 3-8 consecutive words copied EXACTLY from the '
        "speech (same language, same spelling) at the moment the scene should appear. Optional "
        '"until": exact words where it may disappear. Item anchors are the exact words where '
        "that item is said. Scenes follow the order of the speech and must not overlap.\n"
        "2. Data: every number must be said in the speech (or in the speaker's own visual "
        "requests). Never invent, estimate, complete or score anything; a speech without numbers "
        "gets non-numeric scenes.\n"
        f"3. All visible text in {language}. Labels at most 4 words, titles at most 8 words, "
        "no Markdown, no emoji.\n"
        f"4. Pick the type by content: {CHOOSING}{CHOOSING_IMAGE if brief.images else ''}. "
        "Vary types within the turn. Fewer strong "
        "scenes beat many weak ones; an empty list is fine.\n"
        '5. Return {"scenes": [...]}.'
    )
    parts = [
        f"Debate topic: {topic}",
        f"Language: {language}",
        f"Speaker: {brief.speaker_name} ({brief.role}, {brief.turn_type.replace('_', ' ')})",
    ]
    if brief.debaters:
        parts.append(
            f"Debaters: {', '.join(brief.debaters)}. A side, set or item that stands for a "
            "debater is labelled with that exact name."
        )
    if brief.opponent and brief.previous_text:
        previous = brief.previous_text
        if len(previous) > 1500:
            previous = previous[:1500].rsplit(" ", 1)[0] + " …"
        parts.append(f"The opponent ({brief.opponent}) said just before:\n{previous}")
    else:
        parts.append("No opponent turn precedes this one: do not use rebuttal.")
    parts.append(f"Speech to illustrate:\n{brief.text}")
    if brief.hints:
        requests = "\n".join(
            f"{i}. {text}" + (f' (right after: "{after}")' if after else "")
            for i, (text, after) in enumerate(brief.hints, start=1)
        )
        parts.append(
            "The speaker asked the studio to show these visuals. Design them first, anchored right "
            "after the quoted words, with the scene type that fits the data rather than the one "
            "named in the request (one figure is a stat, 2-6 compared values are bars, a trend "
            "needs 3+ points):\n" + requests
        )
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
    if isinstance(scene, RankingScene):
        return [i.value for i in scene.items if i.value is not None]
    if isinstance(scene, MapScene):
        return [r.value for r in scene.regions if r.value is not None]
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


_NUMBER_WORDS: dict[str, str] = {
    "one": "1", "two": "2", "three": "3", "four": "4", "first": "1", "second": "2", "third": "3",
    "fourth": "4",
}  # fmt: skip


def _name_key(text: str) -> str:
    tokens: list[str] = re.findall(r"\w+", text.lower())
    return " ".join(_NUMBER_WORDS.get(t, t) for t in tokens)


def debater_label(label: str, debaters: tuple[str, ...]) -> str:
    """A side labelled "Debater One" for the debater "Debater 1" gets the exact name, so the
    studio can paint it in that debater's colour."""
    key = _name_key(label)
    return next((name for name in debaters if key and _name_key(name) == key), label)


def _label_debaters(scene: Any, debaters: tuple[str, ...]) -> None:
    if isinstance(scene, ScaleScene | VersusScene):
        scene.left.label = debater_label(scene.left.label, debaters)
        scene.right.label = debater_label(scene.right.label, debaters)
    elif isinstance(scene, VennScene):
        for item in scene.sets:
            item.label = debater_label(item.label, debaters)


def _coerce_chart(kind: str, item: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Rescue charts too small for their type (often from a debater's request): one value
    becomes a stat, a two-point trend becomes bars."""
    key = "points" if kind == "line" else "items"
    values = item.get(key)
    if kind not in ("bars", "pie", "line") or not isinstance(values, list):
        return kind, item
    points = [v for v in values if isinstance(v, dict)]
    if len(points) == 1:
        only = points[0]
        unit = str(item.get("unit") or "")
        stat = {
            "anchor": item.get("anchor") or only.get("anchor") or "",
            "until": item.get("until") or "",
            "value": only.get("value"),
            "suffix": unit if len(unit) <= 3 else "",
            "label": item.get("title") or only.get("label") or "",
        }
        return "stat", stat
    if kind == "line" and len(points) == 2:
        return "bars", {**{k: v for k, v in item.items() if k != "points"}, "items": points}
    return kind, item


def parse_scenes(
    payload: Any,
    limit: int,
    *,
    speech: str = "",
    speaker: str = "",
    opponent: str | None = None,
    debaters: tuple[str, ...] = (),
    images: bool = True,
) -> list[Any]:
    """Valid scene specs from the director's reply; invalid scenes are skipped, not fatal.

    With `speech` the content rules are enforced too: numbers must come from the speech, a
    quote may not be the speaker's own words, a rebuttal needs the opponent's turn before.
    Sides named after a debater get the debater's exact name. Pictures are dropped when the
    show does not use them, and a turn gets at most one."""
    items = payload.get("scenes") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        return []
    scenes: list[Any] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("type") or "").strip().lower().replace("-", "_").replace(" ", "_")
        if kind in TYPE_ALIASES:
            if kind in ("cycle", "pyramid"):
                item = {**item, "layout": kind}
            kind = TYPE_ALIASES[kind]
        kind, item = _coerce_chart(kind, item)
        try:
            scene = _SCENE.validate_python({**item, "type": kind})
        except ValidationError as e:
            logger.debug("Dropping invalid %s scene: %s", kind or "untyped", e.errors()[:2])
            continue
        if isinstance(scene, ImageScene) and (
            not images or any(isinstance(s, ImageScene) for s in scenes)
        ):
            continue
        if speech:
            if not is_grounded(scene, speech):
                if not isinstance(scene, RankingScene | MapScene):
                    logger.debug("Dropping %s scene with numbers not in the speech", kind)
                    continue
                for element in scene.items if isinstance(scene, RankingScene) else scene.regions:
                    element.value = None  # the order / the countries still stand
            if isinstance(scene, QuoteScene) and _same_person(scene.author, speaker):
                continue
            if isinstance(scene, RebuttalScene):
                if not opponent:
                    continue
                scene.claim_author = opponent
        _label_debaters(scene, debaters)
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
    unordered = isinstance(scene, UNORDERED_ITEMS)
    found: list[int | None] = []
    cursor = at
    for anchor in anchors:
        hit = _locate(words, anchor, at if unordered else cursor) if anchor else None
        if hit is not None:
            cursor = hit + 1
            found.append(max(start, words[hit][1] - ITEM_LEAD_MS))
        else:
            found.append(None)
    items = _spread_items(found, start, end) if unordered else _fill_items(found, start, end)
    if items and min(items) - start > ITEM_GAP_MS:
        start = min(items) - LEAD_MS  # the first element is said much later: appear with it
    if items:
        end = max(end, max(items) + ITEM_HOLD_MS)
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


def _spread_items(found: list[int | None], start: int, end: int) -> list[int]:
    """Reveal times for elements said in any order: located anchors are kept, the others are
    spread evenly over the first 60% of the scene in list order."""
    n = len(found)
    span = (end - start) * 0.6
    return [
        t if t is not None else start + round(span * i / max(1, n - 1)) for i, t in enumerate(found)
    ]


def align_scenes(scenes: list[Any], segment: TimelineSegment) -> list[TimelineVisual]:
    """Turn scene specs into absolute, non-overlapping screen time within one segment."""
    words = [(w.w, w.s, w.e) for w in segment.words]
    duration = segment.end_ms - segment.start_ms
    placed = [_place(s, i, len(scenes), words, duration) for i, s in enumerate(scenes)]
    placed.sort(key=lambda p: p.start)

    kept: list[_Placed] = []
    for p in placed:
        p.end = min(p.end, duration + END_HOLD_MS)
        if p.end - p.start < MIN_SCENE_MS:  # said at the very end (a punchline): appear earlier
            p.start = max(0, p.end - MIN_SCENE_MS)
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
                key=getattr(p.scene, "key", ""),
                scene=p.scene,
            )
        )
    return visuals


SCOREBOARD_MS = 9000
SCOREBOARD_TAIL_MS = 2500  # without an announcement: end this long before the verdict ends
_WIN_RE = re.compile(
    r"(win|wins|winner|winners|winning|won|victory|victor|prevails?|triumphs?|"
    r"побед\w*|побежд\w*|выигр\w*)"
)
_DRAW_RE = re.compile(r"(draw|tie|tied|ничья|ничью|ничьей|вничью)")


def announcement_index(words: list[tuple[str, int, int]], winner: str | None) -> int | None:
    """Index of the word where the judge announces the result: a win word next to the
    winner's name ("the winner is Nova", "Nova wins"), or a draw word for a draw."""
    tokens = [normalize_token(w[0]) for w in words]
    name = next((normalize_token(t) for t in (winner or "").split() if normalize_token(t)), "")
    for i, token in enumerate(tokens):
        if winner is None:
            if _DRAW_RE.fullmatch(token):
                return i
            continue
        if not _WIN_RE.fullmatch(token):
            continue
        near = [j for j in range(max(0, i - 4), min(len(tokens), i + 10)) if tokens[j] == name]
        if near:
            return min(i, near[0])
    return None


def scoreboard_visual(
    segment: TimelineSegment,
    debater_ids: list[str],
    *,
    winner_id: str | None,
    winner_name: str | None,
    headline: str = "",
) -> TimelineVisual:
    """The judge's result on the stage, from the structured verdict (no LLM): shown when the
    judge announces it, otherwise shortly before the verdict ends."""
    words = [(w.w, w.s, w.e) for w in segment.words]
    duration = segment.end_ms - segment.start_ms
    at = announcement_index(words, winner_name if winner_id else None)
    if at is not None:
        start = max(0, words[at][1] - LEAD_MS)
    else:
        start = max(0, duration - SCOREBOARD_MS - SCOREBOARD_TAIL_MS)
    end = min(start + SCOREBOARD_MS, duration + END_HOLD_MS)
    scene = ScoreboardScene(
        type="scoreboard", speaker_ids=debater_ids, winner_id=winner_id, headline=headline
    )
    return TimelineVisual(
        id=f"v{segment.seq_index}_score",
        seq_index=segment.seq_index,
        speaker_id=segment.speaker_id,
        start_ms=segment.start_ms + start,
        end_ms=segment.start_ms + end,
        anchored=at is not None,
        scene=scene,
    )


def make_room(visuals: list[TimelineVisual], pinned: TimelineVisual) -> list[TimelineVisual]:
    """Insert a scene that must stay (the scoreboard): overlapping scenes are cut short, moved
    after it or dropped when too little of them would remain."""
    out = [pinned]
    for v in visuals:
        start, end = v.start_ms, v.end_ms
        if end > pinned.start_ms and start < pinned.end_ms:
            if pinned.start_ms - start >= MIN_SCENE_MS:
                end = pinned.start_ms
            elif end - pinned.end_ms >= MIN_SCENE_MS:
                start = pinned.end_ms
            else:
                continue
        last = max(start, end - 1200)
        items = [min(max(t, start), last) for t in v.item_ms]
        out.append(v.model_copy(update={"start_ms": start, "end_ms": end, "item_ms": items}))
    return sorted(out, key=lambda v: v.start_ms)


# --- scene summaries (prompts of debaters, fact-checker and judge) ------------------------


def _n(value: float, unit: str = "") -> str:
    text = str(int(value)) if float(value).is_integer() else f"{value:g}"
    return f"{text}{unit}" if len(unit) <= 1 else f"{text} {unit}"


def _clip_summary(text: str, limit: int = 240) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def scene_summary(scene: Any) -> str:
    """One line describing what a scene shows, e.g. 'bars "Wind share": Denmark 40%, US 15%'."""
    title = f' "{scene.title}"' if getattr(scene, "title", "") else ""
    out: str
    if isinstance(scene, StatScene):
        trend = f" (trend {scene.trend})" if scene.trend else ""
        out = f"stat: {scene.prefix}{_n(scene.value)}{scene.suffix} — {scene.label}{trend}"
    elif isinstance(scene, BarsScene | PieScene):
        items = ", ".join(f"{i.label} {_n(i.value, scene.unit)}" for i in scene.items)
        out = f"{scene.type}{title}: {items}"
    elif isinstance(scene, LineScene):
        points = ", ".join(f"{p.label}: {_n(p.value, scene.unit)}" for p in scene.points)
        out = f"line{title}: {points}"
    elif isinstance(scene, ProportionScene):
        out = f"proportion: {_n(scene.count)} of {_n(scene.total)} — {scene.label}"
    elif isinstance(scene, RankingScene):
        items = ", ".join(
            f"{i}. {item.label}"
            + ("" if item.value is None else f" ({_n(item.value, scene.unit)})")
            for i, item in enumerate(scene.items, start=1)
        )
        out = f"ranking{title}: {items}"
    elif isinstance(scene, MapScene):
        regions = ", ".join(
            (r.label or "/".join(r.codes))
            + ("" if r.value is None else f" {_n(r.value, scene.unit)}")
            for r in scene.regions
        )
        out = f"map{title}: {regions}"
    elif isinstance(scene, TimelineScene):
        out = f"timeline{title}: " + "; ".join(f"{e.date} — {e.label}" for e in scene.events)
    elif isinstance(scene, QuoteScene):
        out = f'quote: "{scene.text}"' + (f" — {scene.author}" if scene.author else "")
    elif isinstance(scene, DefinitionScene):
        out = f"definition: {scene.term} — {scene.text}"
    elif isinstance(scene, RebuttalScene):
        out = f'rebuttal: "{scene.claim}" answered with "{scene.response}"'
    elif isinstance(scene, HeadlineScene):
        out = f"headline: {scene.text}"
    elif isinstance(scene, BulletsScene):
        out = f"bullets{title}: " + "; ".join(i.text for i in scene.items)
    elif isinstance(scene, VersusScene | ScaleScene):
        left = ", ".join(i if isinstance(i, str) else i.text for i in scene.left.items)
        right = ", ".join(i if isinstance(i, str) else i.text for i in scene.right.items)
        out = f"{scene.type}{title}: {scene.left.label} ({left}) vs {scene.right.label} ({right})"
    elif isinstance(scene, MatrixScene):
        out = f"matrix{title}: {scene.x_axis} vs {scene.y_axis}: " + ", ".join(
            i.label for i in scene.items
        )
    elif isinstance(scene, VennScene):
        out = f"venn{title}: " + " ∩ ".join(s.label for s in scene.sets)
    elif isinstance(scene, FlowScene):
        out = f"flow{title}: " + " → ".join(s.label for s in scene.steps)
    elif isinstance(scene, IconsScene):
        out = "icons: " + ", ".join(i.label for i in scene.items)
    elif isinstance(scene, SketchScene):
        out = f"drawing: {scene.subject}"
    elif isinstance(scene, ImageScene):
        out = f"picture: {scene.subject}"
    else:
        out = str(getattr(scene, "type", "scene"))
    return _clip_summary(out)


def is_checkable(scene: Any) -> bool:
    """Scenes stating facts a web search can confirm: figures, dates and attributed quotes."""
    if isinstance(scene, StatScene | BarsScene | LineScene | PieScene | ProportionScene):
        return True
    if isinstance(scene, RankingScene):
        return any(i.value is not None for i in scene.items)
    if isinstance(scene, MapScene):
        return any(r.value is not None for r in scene.regions)
    if isinstance(scene, TimelineScene):
        return True
    return isinstance(scene, QuoteScene) and bool(scene.author)


def is_disputable(scene: Any) -> bool:
    """Scenes an opponent may challenge on screen: facts, definitions and rebuttals (a rebuttal
    may misrepresent what the opponent said)."""
    return is_checkable(scene) or isinstance(
        scene, QuoteScene | DefinitionScene | RebuttalScene | RankingScene | MapScene
    )
