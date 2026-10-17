"""Hide the studio markers (`[visual: …]`, `[dispute N: …]`) while a turn streams.

Debaters may write these markers for the visual studio; the server strips them before a turn is
saved, but the live stream carries the raw text. Mirrors `hideStudioMarkers` in the web app
(frontend/src/lib/format.ts): a marker still being typed at the end is hidden too.
"""

from __future__ import annotations

import re

_FULL = re.compile(r"[ \t]*\[\s*(?:visual|dispute)\b[^\]\n]*\]", re.IGNORECASE)
_PARTIAL = re.compile(
    r"[ \t]*\[\s*(?:v(?:i(?:s(?:u(?:a(?:l)?)?)?)?)?|d(?:i(?:s(?:p(?:u(?:t(?:e)?)?)?)?)?)?)"
    r"(?:\b[^\]\n]*)?$",
    re.IGNORECASE,
)


def hide_studio_markers(text: str) -> str:
    return _PARTIAL.sub("", _FULL.sub("", text))


def _settled(visible: str) -> str:
    """The part of the visible text that can no longer change: trailing blanks and a lone `[`
    are held back, as the next chunk may turn them into a hidden marker."""
    text = visible.rstrip(" \t")
    if text.endswith("["):
        text = text[:-1].rstrip(" \t")
    return text


class StreamedTurn:
    """Collects the deltas of one turn and hands out only text that is safe to print, so the
    terminal never shows a marker that disappears a moment later."""

    def __init__(self) -> None:
        self.raw = ""
        self.printed = ""

    def feed(self, delta: str) -> str:
        """Add a delta; returns the newly printable text (often empty)."""
        self.raw += delta
        settled = _settled(hide_studio_markers(self.raw)).lstrip()
        if len(settled) <= len(self.printed) or not settled.startswith(self.printed):
            return ""
        new = settled[len(self.printed) :]
        self.printed = settled
        return new

    def finish(self, final: str | None = None) -> str:
        """The rest of the turn once it is complete. `final` is the saved text (markers already
        stripped by the server); text already on screen is never repeated."""
        text = (final if final is not None else hide_studio_markers(self.raw)).strip()
        # When the server tidied the text around removed markers, what is on screen is complete.
        rest = text[len(self.printed) :] if text.startswith(self.printed) else ""
        self.printed += rest
        return rest
