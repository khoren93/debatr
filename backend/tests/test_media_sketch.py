import pytest
from pydantic import ValidationError

from app.schemas.visuals import SketchScene, SketchStroke
from app.services.media.sketch import build_sketch_messages, sanitize_svg

HOUSE = """```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 300">
  <g stroke="black" fill="none">
    <rect x="100" y="120" width="200" height="140"/>
    <polygon points="90,120 200,40 310,120" class="accent"/>
    <line x1="0" y1="260" x2="400" y2="260"/>
    <circle cx="330" cy="60" r="25"/>
    <ellipse cx="60" cy="60" rx="30" ry="12"/>
    <polyline points="150,260 150,190 190,190 190,260"/>
    <path d="M220 160 h40 v40 h-40 Z" fill="black"/>
  </g>
</svg>
```"""


def test_sanitize_turns_shapes_into_paths():
    drawing = sanitize_svg(HOUSE)
    assert drawing is not None
    assert drawing.view == [0, 0, 400, 300]
    assert len(drawing.strokes) == 7
    rect, roof, ground, sun, cloud, door, window = drawing.strokes
    assert rect.d == "M100 120 H300 V260 H100 Z" and not rect.fill
    assert roof.accent and roof.d.endswith("Z")
    assert ground.d == "M0 260 L400 260"
    assert sun.d.startswith("M305 60 A25 25")
    assert cloud.d.startswith("M30 60 A30 12")
    assert door.d.startswith("M150 260 L150 190") and not door.d.endswith("Z")
    assert window.fill  # a closed shape with an explicit fill gets a wash
    assert all(s.w == 1.0 for s in drawing.strokes)  # 2px model strokes = our marker


def test_sanitize_drops_everything_but_lines():
    svg = """<svg viewBox="0 0 100 100">
      <script>alert(1)</script>
      <style>path { stroke: red }</style>
      <text x="1" y="1">Hello</text>
      <image href="https://evil.example/x.png"/>
      <foreignObject><div xmlns="http://www.w3.org/1999/xhtml">x</div></foreignObject>
      <use href="#a"/>
      <a href="javascript:alert(1)"><path d="M0 0 L5 5"/></a>
      <path d="M0 0 L10 10" onload="alert(1)" stroke="black"/>
      <path d="M0 0 L10 10 url(#x)"/>
      <path d="M1 1 L2 2" transform="translate(1,2) expression(alert(1))"/>
      <line x1="0" y1="0" x2="1" y2="1"/>
      <line x1="0" y1="0" x2="2" y2="2" stroke="none"/>
      <circle cx="5" cy="5" r="2" style="stroke-width: 6; fill: none"/>
      <rect x="0" y="0" width="0" height="10"/>
      <g transform="rotate(45 50 50)"><path d="m 10 10 l 5 5"/></g>
    </svg>"""
    drawing = sanitize_svg(svg)
    assert drawing is not None
    ds = [s.d for s in drawing.strokes]
    assert ds == [
        "M0 0 L10 10",
        "M0 0 L1 1",
        "M3 5 A2 2 0 1 0 7 5 A2 2 0 1 0 3 5 Z",
        "m 10 10 l 5 5",
    ]
    assert drawing.strokes[2].w == 3.0
    assert drawing.strokes[3].t == "rotate(45 50 50)"


@pytest.mark.parametrize(
    "text",
    [
        "no svg at all",
        '<!DOCTYPE svg [<!ENTITY x "y">]><svg><path d="M0 0 L1 1"/></svg>',
        "<svg><path d='M0 0 L1 1'/>",  # unterminated
        '<svg viewBox="0 0 10 10"><path d="M0 0 L1 1"/><path d="M1 1 L2 2"/></svg>',  # too few
    ],
)
def test_sanitize_rejects(text):
    assert sanitize_svg(text) is None


def test_sanitize_caps_strokes_and_reads_size():
    paths = "".join(f'<line x1="{i}" y1="0" x2="{i}" y2="9"/>' for i in range(400))
    drawing = sanitize_svg(f'<svg width="640" height="480">{paths}</svg>')
    assert drawing is not None
    assert drawing.view == [0, 0, 640, 480]
    assert len(drawing.strokes) == 160


def test_stroke_validation_is_strict():
    with pytest.raises(ValidationError):
        SketchStroke.model_validate({"d": "L0 0"})  # must start with a move
    with pytest.raises(ValidationError):
        SketchStroke.model_validate({"d": "M0 0", "t": "translate(1) url(x)"})
    scene = SketchScene.model_validate(
        {"type": "sketch", "subject": "a lamp", "caption": "x" * 200}
    )
    assert scene.drawing is None and len(scene.caption) == 90


def test_sketch_prompt_names_the_subject():
    messages = build_sketch_messages("a piggy bank")
    assert "a piggy bank" in messages[1]["content"]
    assert "No text" in messages[1]["content"]
