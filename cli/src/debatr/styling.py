"""Light Markdown styling for text that arrives in chunks.

A live turn cannot be re-rendered once printed, so instead of rich's Markdown (which needs the
whole text) this turns the common inline syntax into terminal styles as the text streams:
`**bold**`, `# headings`, `- bullets` and a leading spoken-style `[emotion]` cue. Characters
that may still become syntax (a lone `*`, `#` at the start of a line) wait for the next chunk.
"""

from __future__ import annotations

import re

Segment = tuple[str, str]  # (text, rich style)

_HEADING = re.compile(r"#{1,6}[ \t]+")
_BULLET = re.compile(r"([ \t]*)[-*+][ \t]+")
_CUE = re.compile(r"\[([a-z][a-z ]{1,24})\][ \t]*", re.IGNORECASE)
_MAYBE_LINE_MARK = re.compile(r"[ \t]*(?:#{1,6}|[-*+])?")  # an incomplete heading / bullet


class InlineMarkdown:
    def __init__(self) -> None:
        self.pending = ""
        self.bold = False
        self.heading = False
        self.line_start = True
        self.turn_start = True
        self.last = ""  # the previous character emitted

    def _hold_line_mark(self, rest: str) -> bool:
        """At the start of a line, `#`, `##`, `-`… may still become a heading or a bullet."""
        return bool(rest) and _MAYBE_LINE_MARK.fullmatch(rest) is not None and len(rest) <= 12

    def feed(self, text: str, *, final: bool = False) -> list[Segment]:
        buf = self.pending + text
        out: list[Segment] = []
        i = 0

        def emit(chunk: str, style: str | None = None) -> None:
            if not chunk:
                return
            style = style if style is not None else ("bold" if self.bold or self.heading else "")
            if out and out[-1][1] == style:
                out[-1] = (out[-1][0] + chunk, style)
            else:
                out.append((chunk, style))

        while i < len(buf):
            rest = buf[i:]
            if self.turn_start:
                cue = _CUE.match(rest)
                if cue:
                    emit(f"({cue.group(1).lower()}) ", "dim italic")
                    i += cue.end()
                    self.turn_start = False
                    continue
                if rest.startswith("[") and "]" not in rest and len(rest) < 28 and not final:
                    break  # maybe a cue still being typed
                self.turn_start = False
            if self.line_start:
                if rest.startswith("**"):
                    self.line_start = False
                elif heading := _HEADING.match(rest):
                    self.heading, self.line_start = True, False
                    i += heading.end()
                    continue
                elif bullet := _BULLET.match(rest):
                    indent = bullet.group(1)
                    emit(f"{indent}◦ " if indent else "• ")
                    self.line_start = False
                    i += bullet.end()
                    continue
                elif self._hold_line_mark(rest) and not final:
                    break
                else:
                    self.line_start = False
            if rest.startswith("**"):
                self.bold = not self.bold
                i += 2
                continue
            if rest == "*" and not final:
                break  # may be the first half of "**"
            char = buf[i]
            emit(char, "" if char == "\n" else None)
            i += 1
            if char == "\n":
                if self.heading or self.last == "\n":
                    self.bold = False  # bold never spans a heading line or a paragraph
                self.heading = False
                self.line_start = True
            self.last = char
        self.pending = "" if final else buf[i:]
        return out

    def finish(self) -> list[Segment]:
        """Flush what was held back (the turn is over)."""
        return self.feed("", final=True)
