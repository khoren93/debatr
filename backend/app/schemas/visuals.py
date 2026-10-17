"""Visual scenes shown while a speaker talks: charts, numbers and drawn schemes.

The contract between the visual director (`services/media/visuals.py`), `timeline.json` and the
browser renderer (`frontend/src/api/visuals.ts`, `frontend/src/video/visuals/`). The models are
lenient on input because they parse LLM output: long strings are clipped and long lists cut
instead of rejecting the whole scene. Only data travels here — never markup or code.
"""

import hashlib
import json
import math
import re
from collections.abc import Callable
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    model_validator,
)

from app.schemas.geo import normalize_countries

# Pictogram keys the director may use; mirrored by frontend/src/video/visuals/icons.ts.
ICONS: tuple[str, ...] = (
    "person", "people", "child", "brain", "robot", "sparkles", "chip", "server", "data",
    "internet", "phone", "laptop", "money", "coins", "savings", "wallet", "shopping", "bank",
    "factory", "office", "house", "school", "education", "book", "hospital", "health",
    "medicine", "vaccine", "science", "research", "dna", "atom", "idea", "rocket", "growth",
    "decline", "chart", "bars", "pie", "percent", "target", "trophy", "crown", "flag",
    "conflict", "law", "justice", "vote", "megaphone", "news", "tv", "film", "music", "game",
    "chat", "eye", "search", "time", "deadline", "calendar", "location", "globe", "earth",
    "energy", "fire", "water", "sun", "cloud", "wind", "leaf", "tree", "plant", "mountain",
    "ocean", "recycle", "battery", "fuel", "car", "bus", "bike", "train", "plane", "ship",
    "truck", "food", "farm", "fish", "dog", "cat", "bird", "bug", "heart", "care", "deal",
    "shield", "lock", "key", "warning", "danger", "bomb", "ban", "yes", "no", "like",
    "dislike", "work", "tools", "build", "gift", "gem", "infinity", "chance", "mail",
)  # fmt: skip
ICON_ALIASES: dict[str, str] = {
    "ai": "robot", "computer": "laptop", "economy": "money", "cash": "money", "dollar": "money",
    "salary": "money", "tax": "coins", "home": "house", "city": "office", "building": "office",
    "company": "office", "job": "work", "jobs": "work", "university": "education",
    "student": "education", "doctor": "health", "climate": "earth", "world": "globe",
    "environment": "leaf", "nature": "tree", "pollution": "factory", "electricity": "energy",
    "power": "energy", "court": "law", "police": "shield", "security": "shield",
    "privacy": "lock", "war": "conflict", "weapon": "conflict", "election": "vote",
    "democracy": "vote", "media": "news", "social": "chat", "clock": "time", "up": "growth",
    "down": "decline", "success": "trophy", "win": "trophy", "risk": "warning",
    "death": "danger", "love": "heart", "family": "people", "population": "people",
    "human": "person", "kids": "child", "children": "child", "transport": "car",
    "travel": "plane", "trade": "ship", "agriculture": "farm", "check": "yes", "cross": "no",
}  # fmt: skip
_ICON_SET = frozenset(ICONS)


def _clip(limit: int) -> Callable[[Any], Any]:
    def run(value: Any) -> Any:
        if value is None or isinstance(value, (dict, list, bool)):
            return value
        text = " ".join(str(value).replace("*", "").split())
        return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"

    return run


def _take(limit: int) -> Callable[[Any], Any]:
    return lambda value: value[:limit] if isinstance(value, list) else value


_NUM_RE = re.compile(r"[-+\u2212]?\d[\d\s\u00a0\u202f,.'\u2019]*")


def parse_number(value: Any) -> float:
    """Number from LLM output: 42, "42%", "1 200", "1,5", "$3.4 trillion" (-> 3.4)."""
    if isinstance(value, bool):
        raise ValueError("not a number")
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        match = _NUM_RE.search(value)
        if not match:
            raise ValueError("no number")
        raw = re.sub(r"[\s\u00a0\u202f'\u2019]", "", match.group(0))
        raw = raw.replace("\u2212", "-").rstrip(",.")
        if "," in raw and "." in raw:
            decimal = "," if raw.rfind(",") > raw.rfind(".") else "."
            thousands = "." if decimal == "," else ","
            raw = raw.replace(thousands, "").replace(decimal, ".")
        elif raw.count(",") > 1 or re.search(r",\d{3}$", raw):
            raw = raw.replace(",", "")
        elif "," in raw:
            raw = raw.replace(",", ".")
        elif raw.count(".") > 1:
            raw = raw.replace(".", "")
        number = float(raw)
    else:
        raise ValueError("not a number")
    if not math.isfinite(number) or abs(number) >= 1e15:
        raise ValueError("number out of range")
    return number


def _maybe_number(value: Any) -> float | None:
    try:
        return None if value is None or value == "" else parse_number(value)
    except ValueError:
        return None


def normalize_icon(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    key = re.sub(r"[\s_]+", "-", value.strip().lower())
    key = ICON_ALIASES.get(key, key)
    return key if key in _ICON_SET else None


def _trend(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    return text if text in ("up", "down") else None


def _layout(value: Any) -> str:
    return "cycle" if str(value or "").strip().lower() == "cycle" else "chain"


def _rank_layout(value: Any) -> str:
    return "pyramid" if str(value or "").strip().lower() == "pyramid" else "list"


def _heavier(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    if text in ("left", "right"):
        return text
    return "even" if text in ("even", "balanced", "equal", "tie", "draw") else None


_COORD_WORDS = {
    "very low": 1.0,
    "low": 2.5,
    "mid": 5.0,
    "medium": 5.0,
    "high": 7.5,
    "very high": 9.0,
}


def _coord(value: Any) -> float:
    """Position on a 0-10 matrix axis: a number (0-10, or 0-100 read as percent) or a word."""
    if isinstance(value, str) and value.strip().lower() in _COORD_WORDS:
        return _COORD_WORDS[value.strip().lower()]
    number = parse_number(value)
    if 10 < number <= 100:
        number /= 10
    return min(10.0, max(0.0, number))


def _quadrants(value: Any) -> list[str]:
    """Four corner labels (top-left, top-right, bottom-left, bottom-right) or none."""
    if not isinstance(value, list) or len(value) != 4:
        return []
    labels = [_clip(32)(v) if isinstance(v, (str, int, float)) else "" for v in value]
    return [str(v or "") for v in labels]


def _regions(value: Any) -> Any:
    """Map regions with at least one drawable country; the rest are dropped, not fatal."""
    if not isinstance(value, list):
        return value
    out: list[Any] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        raw = item.get("codes") or item.get("code") or item.get("country") or item.get("iso")
        codes = normalize_countries(raw)
        if codes:
            out.append({**item, "codes": codes})
    return out


Label = Annotated[str, BeforeValidator(_clip(32)), Field(min_length=1)]
Title = Annotated[str, BeforeValidator(_clip(64))]
Line = Annotated[str, BeforeValidator(_clip(90)), Field(min_length=1)]
Long = Annotated[str, BeforeValidator(_clip(160)), Field(min_length=1)]
Affix = Annotated[str, BeforeValidator(_clip(14))]
Anchor = Annotated[str, BeforeValidator(_clip(120))]
Number = Annotated[float, BeforeValidator(parse_number)]
OptNumber = Annotated[float | None, BeforeValidator(_maybe_number)]
Icon = Annotated[str | None, BeforeValidator(normalize_icon)]


class _Base(BaseModel):
    model_config = ConfigDict(extra="ignore")


class _Scene(_Base):
    # Stable id within the debate ("{seq}:{hash}", see `scene_key`); set by the studio, never
    # by the director. Fact-checks and disputes refer to scenes by it.
    key: Annotated[str, BeforeValidator(_clip(40))] = ""
    # Exact words of the speech where the scene appears (and optionally disappears).
    anchor: Anchor = ""
    until: Anchor = ""
    title: Title = ""


class Point(_Base):
    label: Label
    value: Number
    highlight: bool = False


class StatScene(_Scene):
    type: Literal["stat"]
    value: Number
    prefix: Affix = ""
    suffix: Affix = ""
    label: Line
    trend: Annotated[Literal["up", "down"] | None, BeforeValidator(_trend)] = None
    icon: Icon = None


class BarsScene(_Scene):
    type: Literal["bars"]
    unit: Affix = ""
    items: Annotated[list[Point], BeforeValidator(_take(6)), Field(min_length=2)]


class LineScene(_Scene):
    type: Literal["line"]
    unit: Affix = ""
    points: Annotated[list[Point], BeforeValidator(_take(12)), Field(min_length=3)]


class PieScene(_Scene):
    type: Literal["pie"]
    unit: Affix = ""
    items: Annotated[list[Point], BeforeValidator(_take(5)), Field(min_length=2)]

    @model_validator(mode="after")
    def _positive(self) -> "PieScene":
        self.items = [p for p in self.items if p.value > 0]
        if len(self.items) < 2:
            raise ValueError("a pie needs two positive shares")
        return self


class ProportionScene(_Scene):
    type: Literal["proportion"]
    count: Number
    total: Number
    label: Line
    icon: Icon = None

    @model_validator(mode="after")
    def _grid(self) -> "ProportionScene":
        self.total = float(round(self.total))
        self.count = float(round(self.count))
        if not 2 <= self.total <= 100 or not 0 <= self.count <= self.total:
            raise ValueError("count/total must fit a grid of at most 100")
        return self


class AnchoredText(_Base):
    text: Line
    anchor: Anchor = ""


class BulletsScene(_Scene):
    type: Literal["bullets"]
    items: Annotated[list[AnchoredText], BeforeValidator(_take(4)), Field(min_length=2)]


class Side(_Base):
    label: Label
    items: Annotated[
        list[Annotated[str, BeforeValidator(_clip(60)), Field(min_length=1)]],
        BeforeValidator(_take(4)),
        Field(min_length=1),
    ]


class VersusScene(_Scene):
    type: Literal["versus"]
    left: Side
    right: Side


class QuoteScene(_Scene):
    type: Literal["quote"]
    text: Long
    author: Title = ""


class RebuttalScene(_Scene):
    type: Literal["rebuttal"]
    claim: Long
    claim_author: Title = ""
    response: Long
    response_anchor: Anchor = ""


class HeadlineScene(_Scene):
    type: Literal["headline"]
    text: Annotated[str, BeforeValidator(_clip(72)), Field(min_length=1)]
    emphasis: Annotated[str, BeforeValidator(_clip(40))] = ""


class Step(_Base):
    label: Label
    icon: Icon = None
    anchor: Anchor = ""


class FlowScene(_Scene):
    type: Literal["flow"]
    layout: Annotated[Literal["chain", "cycle"], BeforeValidator(_layout)] = "chain"
    steps: Annotated[list[Step], BeforeValidator(_take(5)), Field(min_length=2)]


class Event(_Base):
    date: Annotated[str, BeforeValidator(_clip(16)), Field(min_length=1)]
    label: Annotated[str, BeforeValidator(_clip(40)), Field(min_length=1)]
    anchor: Anchor = ""


class TimelineScene(_Scene):
    type: Literal["timeline"]
    events: Annotated[list[Event], BeforeValidator(_take(6)), Field(min_length=2)]


class Pictogram(_Base):
    icon: Icon
    label: Label
    anchor: Anchor = ""


class IconsScene(_Scene):
    type: Literal["icons"]
    items: Annotated[list[Pictogram], BeforeValidator(_take(3)), Field(min_length=1)]

    @model_validator(mode="after")
    def _known_icons(self) -> "IconsScene":
        self.items = [i for i in self.items if i.icon]
        if not self.items:
            raise ValueError("no known icons")
        return self


Chip = Annotated[str, BeforeValidator(_clip(48)), Field(min_length=1)]


class PanItem(_Base):
    text: Chip
    anchor: Anchor = ""


class Pan(_Base):
    label: Label
    items: Annotated[list[PanItem], BeforeValidator(_take(3)), Field(min_length=1)]


class ScaleScene(_Scene):
    type: Literal["scale"]
    left: Pan
    right: Pan
    # The side the speaker says outweighs; None: by the number of arguments.
    heavier: Annotated[Literal["left", "right", "even"] | None, BeforeValidator(_heavier)] = None


class MatrixPoint(_Base):
    label: Label
    x: Annotated[float, BeforeValidator(_coord)]  # 0 (low) .. 10 (high)
    y: Annotated[float, BeforeValidator(_coord)]
    highlight: bool = False
    anchor: Anchor = ""


class MatrixScene(_Scene):
    type: Literal["matrix"]
    x_axis: Label
    y_axis: Label
    quadrants: Annotated[list[str], BeforeValidator(_quadrants)] = Field(default_factory=list)
    items: Annotated[list[MatrixPoint], BeforeValidator(_take(6)), Field(min_length=1)]


class VennSet(_Base):
    label: Label
    anchor: Anchor = ""


class VennScene(_Scene):
    type: Literal["venn"]
    sets: Annotated[list[VennSet], BeforeValidator(_take(3)), Field(min_length=2)]
    overlap: Annotated[str, BeforeValidator(_clip(32))] = ""
    overlap_anchor: Anchor = ""


class RankItem(_Base):
    label: Chip
    value: OptNumber = None
    anchor: Anchor = ""


class RankingScene(_Scene):
    type: Literal["ranking"]
    layout: Annotated[Literal["list", "pyramid"], BeforeValidator(_rank_layout)] = "list"
    unit: Affix = ""
    items: Annotated[list[RankItem], BeforeValidator(_take(6)), Field(min_length=2)]  # #1 first

    @model_validator(mode="after")
    def _all_or_no_values(self) -> "RankingScene":
        if any(i.value is None for i in self.items):
            for item in self.items:
                item.value = None
        return self


class DefinitionScene(_Scene):
    type: Literal["definition"]
    term: Annotated[str, BeforeValidator(_clip(40)), Field(min_length=1)]
    kind: Annotated[str, BeforeValidator(_clip(24))] = ""  # "noun", "legal term", ...
    text: Long
    source: Title = ""


class MapRegion(_Base):
    codes: Annotated[list[str], Field(min_length=1)]  # ISO alpha-3, see schemas/geo.py
    label: Annotated[str, BeforeValidator(_clip(32))] = ""
    value: OptNumber = None
    anchor: Anchor = ""


class MapScene(_Scene):
    type: Literal["map"]
    unit: Affix = ""
    regions: Annotated[
        list[MapRegion], BeforeValidator(lambda v: _take(8)(_regions(v))), Field(min_length=1)
    ]

    @model_validator(mode="after")
    def _all_or_no_values(self) -> "MapScene":
        if any(r.value is None for r in self.regions):
            for region in self.regions:
                region.value = None
        return self


# --- drawn illustrations and pictures (stage 0.3) ---------------------------------------

_PATH_RE = re.compile(r"^[MmLlHhVvCcSsQqTtAaZz0-9eE.,+\-\s]+$")
_TRANSFORM_RE = re.compile(
    r"^(?:\s*(?:matrix|translate|scale|rotate|skewX|skewY)\s*\([-+0-9.eE,\s]*\)\s*,?)*\s*$"
)
MAX_PATH_CHARS = 6000
MAX_SKETCH_STROKES = 160


def _path_data(value: str) -> str:
    """SVG path data: commands and numbers only (it is rendered as an attribute value)."""
    text = " ".join(value.split())
    if not text or len(text) > MAX_PATH_CHARS or not _PATH_RE.fullmatch(text):
        raise ValueError("invalid path data")
    if text[0] not in "Mm":
        raise ValueError("path data must start with a move")
    return text


def _transform(value: str) -> str:
    text = " ".join(value.split())
    if len(text) > 200 or not _TRANSFORM_RE.fullmatch(text):
        raise ValueError("invalid transform")
    return text


def _stroke_width(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 1.0
    return min(4.0, max(0.4, number)) if math.isfinite(number) else 1.0


class SketchStroke(_Base):
    """One line of a drawing, in the drawing's own coordinates (`SketchDrawing.view`)."""

    d: Annotated[str, AfterValidator(_path_data)]
    t: Annotated[str, AfterValidator(_transform)] = ""  # SVG transform of the line
    accent: bool = False  # drawn in the speaker's colour
    fill: bool = False  # the shape gets a light wash once drawn
    w: Annotated[float, BeforeValidator(_stroke_width)] = 1.0  # relative width


def _view_box(value: Any) -> list[float]:
    numbers = [float(v) for v in value] if isinstance(value, list) else []
    if len(numbers) != 4 or not all(math.isfinite(n) for n in numbers):
        raise ValueError("view needs four numbers")
    if not (0 < numbers[2] <= 10_000 and 0 < numbers[3] <= 10_000):
        raise ValueError("view size out of range")
    return numbers


class SketchDrawing(_Base):
    view: Annotated[list[float], BeforeValidator(_view_box)]  # min-x, min-y, width, height
    strokes: Annotated[list[SketchStroke], Field(min_length=1, max_length=MAX_SKETCH_STROKES)]


class SketchScene(_Scene):
    """A hand-drawn illustration. The director names the subject; the illustrator model draws
    it as SVG, which `services/media/sketch.py` reduces to path data (`drawing`)."""

    type: Literal["sketch"]
    subject: Annotated[str, BeforeValidator(_clip(160)), Field(min_length=3)]  # English
    caption: Annotated[str, BeforeValidator(_clip(90))] = ""
    drawing: SketchDrawing | None = None


_IMAGE_SRC_RE = re.compile(r"^visuals/[0-9a-f]{16,64}\.(?:webp|jpg)$")


def _image_src(value: str) -> str:
    if value and not _IMAGE_SRC_RE.fullmatch(value):
        raise ValueError("invalid image path")
    return value


def _https_url(value: str) -> str:
    text = value.strip()
    if text and (len(text) > 500 or not re.fullmatch(r"https?://[^\s\"'<>]+", text)):
        raise ValueError("invalid url")
    return text


class ImageScene(_Scene):
    """A real-world picture: a free photo (Wikimedia Commons) or an AI image. The director
    describes the subject; the media build finds or generates it (`services/media/images.py`)."""

    type: Literal["image"]
    subject: Annotated[str, BeforeValidator(_clip(160)), Field(min_length=3)]  # English
    caption: Annotated[str, BeforeValidator(_clip(90))] = ""
    src: Annotated[str, AfterValidator(_image_src)] = ""  # relative to the debate media folder
    kind: Literal["photo", "ai"] | None = None
    credit: Annotated[str, BeforeValidator(_clip(140))] = ""  # author, licence, source
    source_url: Annotated[str, AfterValidator(_https_url)] = ""


class ScoreboardScene(_Scene):
    """The judge's result, built from `debates.verdict_json` by code (never by the director)."""

    type: Literal["scoreboard"]
    speaker_ids: list[str]  # debaters in line-up order
    winner_id: str | None = None  # None: a draw
    headline: Annotated[str, BeforeValidator(_clip(160))] = ""


# What the visual director may design.
DirectorScene = Annotated[
    StatScene
    | BarsScene
    | LineScene
    | PieScene
    | ProportionScene
    | BulletsScene
    | VersusScene
    | QuoteScene
    | RebuttalScene
    | HeadlineScene
    | FlowScene
    | TimelineScene
    | IconsScene
    | ScaleScene
    | MatrixScene
    | VennScene
    | RankingScene
    | DefinitionScene
    | MapScene
    | SketchScene
    | ImageScene,
    Field(discriminator="type"),
]
# Everything a timeline may carry.
Scene = Annotated[
    StatScene
    | BarsScene
    | LineScene
    | PieScene
    | ProportionScene
    | BulletsScene
    | VersusScene
    | QuoteScene
    | RebuttalScene
    | HeadlineScene
    | FlowScene
    | TimelineScene
    | IconsScene
    | ScaleScene
    | MatrixScene
    | VennScene
    | RankingScene
    | DefinitionScene
    | MapScene
    | SketchScene
    | ImageScene
    | ScoreboardScene,
    Field(discriminator="type"),
]
SCENE_TYPES: tuple[str, ...] = (
    "stat", "bars", "line", "pie", "proportion", "bullets", "versus", "quote", "rebuttal",
    "headline", "flow", "timeline", "icons", "scale", "matrix", "venn", "ranking", "definition",
    "map", "sketch", "image",
)  # fmt: skip
# Fields the studio fills in after the director (they do not change a scene's identity).
RESOLVED_FIELDS = frozenset({"key", "drawing", "src", "kind", "credit", "source_url"})


def scene_key(seq_index: int, scene: Any) -> str:
    """Stable id of a director scene: the turn plus a hash of what the director designed, so a
    re-plan that produces the same scene keeps its fact-check and disputes."""
    data = scene.model_dump(mode="json", exclude=set(RESOLVED_FIELDS))
    digest = hashlib.sha1(json.dumps(data, sort_keys=True).encode()).hexdigest()[:10]
    return f"{seq_index}:{digest}"


def assign_keys(seq_index: int, scenes: list[Any]) -> list[Any]:
    """Give every scene of a turn its key (identical scenes get a suffix)."""
    seen: set[str] = set()
    for scene in scenes:
        key = scene_key(seq_index, scene)
        n = 2
        while key in seen:
            key = f"{scene_key(seq_index, scene)}-{n}"
            n += 1
        seen.add(key)
        scene.key = key
    return scenes


def key_seq(key: str) -> int | None:
    """The turn a scene key belongs to."""
    head = key.split(":", 1)[0]
    return int(head) if head.isdigit() else None


def item_anchors(scene: Any) -> list[str]:
    """Anchors of the elements revealed one by one (empty list: the scene appears at once)."""
    if isinstance(scene, BulletsScene | IconsScene | MatrixScene | RankingScene):
        return [i.anchor for i in scene.items]
    if isinstance(scene, FlowScene):
        return [s.anchor for s in scene.steps]
    if isinstance(scene, TimelineScene):
        return [e.anchor for e in scene.events]
    if isinstance(scene, RebuttalScene):
        return ["", scene.response_anchor]  # the claim shows first, the counter on its phrase
    if isinstance(scene, ScaleScene):
        return [i.anchor for i in (*scene.left.items, *scene.right.items)]
    if isinstance(scene, VennScene):
        return [s.anchor for s in scene.sets] + ([scene.overlap_anchor] if scene.overlap else [])
    if isinstance(scene, MapScene):
        return [r.anchor for r in scene.regions]
    return []


# Scenes whose elements may be said in any order (a countdown, the two pans, countries):
# each anchor is searched on its own instead of after the previous one.
UNORDERED_ITEMS = (RankingScene, ScaleScene, MapScene)


CheckVerdict = Literal["verified", "disputed", "unverified"]


class CheckSource(_Base):
    url: Annotated[str, AfterValidator(_https_url), Field(min_length=8)]
    title: Annotated[str, BeforeValidator(_clip(120))] = ""


class SceneCheck(_Base):
    """Web fact-check of a scene's figures or quote (`services/factcheck.py`)."""

    verdict: CheckVerdict
    note: Annotated[str, BeforeValidator(_clip(240))] = ""
    sources: Annotated[list[CheckSource], BeforeValidator(_take(3))] = Field(default_factory=list)


class SceneDispute(_Base):
    """A later speaker challenged the scene (`[dispute N: reason]` in their turn)."""

    by_id: str  # participant id
    by_name: Annotated[str, BeforeValidator(_clip(64))]
    seq_index: int  # the turn that disputed it
    reason: Annotated[str, BeforeValidator(_clip(200))] = ""


class TimelineVisual(BaseModel):
    id: str
    seq_index: int
    speaker_id: str
    start_ms: int  # absolute on the full track
    end_ms: int
    item_ms: list[int] = Field(default_factory=list)  # absolute reveal time per element
    anchored: bool = True  # False: the anchor phrase was not found, the timing is estimated
    key: str = ""  # the scene's key ("" for the scoreboard)
    check: SceneCheck | None = None
    disputes: list[SceneDispute] = Field(default_factory=list)
    scene: Scene
