"""Hand-drawn illustrations ("sketch" scenes): an LLM draws SVG line art, we keep only lines.

The model's SVG never reaches a browser. `sanitize_svg` parses it, keeps an allowlist of shape
elements (path, line, circle, ellipse, rect, polyline, polygon, g), turns every shape into path
data and returns plain data (`SketchDrawing`) that the video draws stroke by stroke. Text,
links, styles, scripts, images, `<use>` and unknown elements are dropped with their children.
Everything except the model call is pure and unit-tested.
"""

import logging
import re
import xml.etree.ElementTree as ET
from typing import Any

from pydantic import ValidationError

from app.schemas.visuals import MAX_PATH_CHARS, MAX_SKETCH_STROKES, SketchDrawing, SketchStroke
from app.services.media.llm import complete

logger = logging.getLogger(__name__)

SHAPES = frozenset({"path", "line", "circle", "ellipse", "rect", "polyline", "polygon"})
GROUPS = frozenset({"svg", "g"})
MAX_DEPTH = 8
MAX_TOTAL_PATH_CHARS = 60_000
MIN_STROKES = 3
DEFAULT_VIEW = [0.0, 0.0, 400.0, 300.0]

_SVG_RE = re.compile(r"<svg\b[\s\S]*?</svg\s*>", re.IGNORECASE)
_FORBIDDEN_RE = re.compile(r"<!DOCTYPE|<!ENTITY|<\?xml-stylesheet", re.IGNORECASE)
_NUMBER_RE = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
_NONE = frozenset({"", "none", "transparent"})

SYSTEM = (
    "You are the illustrator of a debate video show. You draw clean, recognizable line-art "
    "illustrations, like a skilled artist sketching with a marker on a whiteboard. Reply with one "
    "<svg> element only."
)


def build_sketch_messages(subject: str) -> list[dict[str, str]]:
    user = (
        f"Draw: {subject}.\n"
        'Rules: viewBox="0 0 400 300". Use only <path>, <line>, <circle>, <ellipse>, <rect>, '
        '<polyline>, <polygon>, <g>. Outlines only: stroke="black", fill="none" (a shape may use '
        'fill="black" only for small solid details). No text, no letters, no numbers, no faces of '
        "real people, no logos. 15-50 elements. The subject is instantly recognizable, centred and "
        "fills about 80% of the canvas; use curves (Q, C, A commands) for organic shapes. Order: "
        'big outlines first, then details. Mark the 1-3 elements that carry the idea with class="accent".'
    )
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]


def _local(tag: Any) -> str:
    return str(tag).rsplit("}", 1)[-1].lower() if isinstance(tag, str) else ""


def _numbers(value: str | None) -> list[float]:
    return [float(n) for n in _NUMBER_RE.findall(value or "")]


def _num(el: ET.Element, name: str, default: float = 0.0) -> float:
    values = _numbers(el.get(name))
    return values[0] if values else default


def _fmt(n: float) -> str:
    text = f"{n:.2f}".rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def _style(el: ET.Element) -> dict[str, str]:
    """Presentation attributes plus the `style` attribute (only the keys we read)."""
    out = {k: (el.get(k) or "").strip() for k in ("fill", "stroke", "stroke-width") if el.get(k)}
    for part in (el.get("style") or "").split(";"):
        if ":" in part:
            key, value = (x.strip().lower() for x in part.split(":", 1))
            if key in ("fill", "stroke", "stroke-width"):
                out[key] = value
    return out


def shape_path(el: ET.Element) -> tuple[str, bool] | None:
    """Path data of a shape and whether it is closed; None for degenerate shapes."""
    tag = _local(el.tag)
    if tag == "path":
        d = " ".join((el.get("d") or "").split())
        return (d, d.rstrip().endswith(("z", "Z"))) if d else None
    if tag == "line":
        x1, y1, x2, y2 = (_num(el, a) for a in ("x1", "y1", "x2", "y2"))
        return f"M{_fmt(x1)} {_fmt(y1)} L{_fmt(x2)} {_fmt(y2)}", False
    if tag == "rect":
        x, y, w, h = _num(el, "x"), _num(el, "y"), _num(el, "width"), _num(el, "height")
        if w <= 0 or h <= 0:
            return None
        return f"M{_fmt(x)} {_fmt(y)} H{_fmt(x + w)} V{_fmt(y + h)} H{_fmt(x)} Z", True
    if tag in ("circle", "ellipse"):
        cx, cy = _num(el, "cx"), _num(el, "cy")
        if tag == "circle":
            rx = ry = _num(el, "r")
        else:
            rx, ry = _num(el, "rx"), _num(el, "ry")
        if rx <= 0 or ry <= 0:
            return None
        r = f"{_fmt(rx)} {_fmt(ry)}"
        return (
            f"M{_fmt(cx - rx)} {_fmt(cy)} A{r} 0 1 0 {_fmt(cx + rx)} {_fmt(cy)} "
            f"A{r} 0 1 0 {_fmt(cx - rx)} {_fmt(cy)} Z",
            True,
        )
    if tag in ("polyline", "polygon"):
        pts = _numbers(el.get("points"))
        pairs = list(zip(pts[0::2], pts[1::2], strict=False))
        if len(pairs) < 2:
            return None
        head, *rest = pairs
        d = f"M{_fmt(head[0])} {_fmt(head[1])} " + " ".join(
            f"L{_fmt(x)} {_fmt(y)}" for x, y in rest
        )
        closed = tag == "polygon"
        return (d + " Z" if closed else d), closed
    return None


def _view(root: ET.Element) -> list[float]:
    box = _numbers(root.get("viewBox") or root.get("viewbox"))
    if len(box) == 4 and box[2] > 0 and box[3] > 0:
        return box
    w, h = _num(root, "width"), _num(root, "height")
    return [0.0, 0.0, w, h] if w > 0 and h > 0 else list(DEFAULT_VIEW)


def sanitize_svg(text: str) -> SketchDrawing | None:
    """Reduce a model's SVG to allowlisted line data. None when nothing usable remains."""
    match = _SVG_RE.search(text or "")
    if not match or _FORBIDDEN_RE.search(match.group(0)):
        return None
    try:
        root = ET.fromstring(match.group(0))
    except ET.ParseError:
        return None
    if _local(root.tag) != "svg":
        return None

    strokes: list[dict[str, Any]] = []
    total = 0

    def walk(el: ET.Element, depth: int, inherited: dict[str, Any]) -> None:
        nonlocal total
        tag = _local(el.tag)
        if depth > MAX_DEPTH or len(strokes) >= MAX_SKETCH_STROKES:
            return
        if tag not in GROUPS and tag not in SHAPES:
            return  # text, image, use, style, script, a, defs, foreignObject, ...
        style = _style(el)
        transform = " ".join((el.get("transform") or "").split())
        widths = _numbers(style.get("stroke-width"))
        state = {
            "accent": inherited["accent"] or "accent" in (el.get("class") or "").split(),
            "fill": str(style.get("fill", inherited["fill"])).lower(),
            "stroke": str(style.get("stroke", inherited["stroke"])).lower(),
            "width": widths[0] if widths else inherited["width"],
            "t": " ".join(x for x in (inherited["t"], transform) if x),
        }
        if tag in SHAPES:
            shape = shape_path(el)
            if shape is None:
                return
            d, closed = shape
            filled = closed and state["fill"] not in _NONE
            if state["stroke"] in _NONE and not filled:
                return  # invisible
            if len(d) > MAX_PATH_CHARS or total + len(d) > MAX_TOTAL_PATH_CHARS:
                return
            strokes.append(
                {
                    "d": d,
                    "t": state["t"],
                    "accent": state["accent"],
                    "fill": filled,
                    "w": state["width"] / 2.0,  # models draw 2px lines; 1.0 = our marker width
                }
            )
            total += len(d)
            return
        for child in el:
            walk(child, depth + 1, state)

    walk(root, 0, {"accent": False, "fill": "", "stroke": "black", "width": 2.0, "t": ""})

    valid: list[dict[str, Any]] = []
    for stroke in strokes:
        try:
            valid.append(SketchStroke.model_validate(stroke).model_dump())
        except ValidationError:
            continue  # bad path data or transform: drop that line only
    if len(valid) < MIN_STROKES:
        return None
    try:
        return SketchDrawing.model_validate({"view": _view(root), "strokes": valid})
    except ValidationError:
        return None


def illustrate(subject: str, *, model: str) -> tuple[SketchDrawing | None, float]:
    """Ask the illustrator model for a drawing. Returns (drawing or None, usd spent)."""
    text, usage = complete(model, build_sketch_messages(subject), max_tokens=6000)
    drawing = sanitize_svg(text)
    if drawing is None:
        logger.info("Sketch of %r was unusable", subject)
    return drawing, float((usage or {}).get("cost") or 0.0)
