"""Studio markers inside a debater's turn: `[visual: …]` and `[dispute N: …]`.

Debaters may ask the studio for a visual right after the sentence it illustrates and challenge
a visual their opponent put on screen (see `prompt_builder`). The markers are neither voiced nor
shown in the transcript: the worker strips them before the turn is saved and keeps them in
`turns.visuals_json`. The frontend hides them while the turn streams. Pure functions.
"""

import re
from dataclasses import dataclass

MAX_HINTS = 2
MAX_DISPUTES = 1
AFTER_WORDS = 10  # words before a hint, where its scene should appear

_MARKER_RE = re.compile(
    r"[ \t]*\[\s*(?:"
    r"(?P<visual>visual)\s*[:\-–—]\s*(?P<hint>[^\[\]\n]{0,400}?)"  # noqa: RUF001 (dashes)
    r"|(?P<dispute>dispute)\s*#?\s*(?P<number>\d{1,2})\s*(?:[:\-–—]\s*(?P<reason>[^\[\]\n]{0,400}?))?"  # noqa: RUF001
    r")\s*\]",
    re.IGNORECASE,
)
_MARKDOWN_RE = re.compile(r"[*_`#>|]+")


@dataclass(frozen=True)
class Hint:
    text: str  # what the debater wants on screen
    after: str  # the words said right before the marker (anchor for the scene)


@dataclass(frozen=True)
class DisputeMark:
    number: int  # index into the list of opponents' visuals offered in the prompt
    reason: str


_CUT = "\x00"  # where a marker was removed


def _tidy(text: str) -> str:
    # "cars. [visual: …]." -> "cars." (a marker between two sentence ends)
    text = re.sub(rf"([.!?…])[ \t]*{_CUT}[ \t]*[.!?…]+", r"\1", text)
    text = text.replace(_CUT, "")
    text = re.sub(r"[ \t]+([.,;:!?…])", r"\1", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _last_words(text: str, n: int) -> str:
    words = _MARKDOWN_RE.sub(" ", text).split()
    return " ".join(words[-n:])


def extract_markers(text: str) -> tuple[str, list[Hint], list[DisputeMark]]:
    """Clean text plus the hints and disputes found in it (extra ones are dropped)."""
    hints: list[Hint] = []
    disputes: list[DisputeMark] = []
    out: list[str] = []
    cursor = 0
    for match in _MARKER_RE.finditer(text or ""):
        out.append(text[cursor : match.start()] + _CUT)
        cursor = match.end()
        if match.group("visual"):
            hint = " ".join((match.group("hint") or "").split())
            if len(hint) >= 3 and len(hints) < MAX_HINTS:
                before = "".join(out).replace(_CUT, " ")
                hints.append(Hint(text=hint, after=_last_words(before, AFTER_WORDS)))
        elif match.group("dispute") and len(disputes) < MAX_DISPUTES:
            reason = " ".join((match.group("reason") or "").split())
            disputes.append(DisputeMark(number=int(match.group("number")), reason=reason))
    out.append((text or "")[cursor:])
    return _tidy("".join(out)), hints, disputes


def has_markers(text: str) -> bool:
    return bool(_MARKER_RE.search(text or ""))
