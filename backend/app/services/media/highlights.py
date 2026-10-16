"""Pick short-video moments (and the winner) from a finished debate.

The LLM chooses whole-turn ranges plus opening/closing quotes; boundaries are then snapped
to word timestamps so a short never starts or ends mid-word. Everything except the model
call is pure and unit-tested.
"""

import difflib
import re
from dataclasses import dataclass
from typing import Any

from app.schemas.timeline import TimelineHighlight, TimelineSegment, TimelineSpeaker

MIN_SHORT_MS = 20_000
MAX_SHORT_MS = 60_000
PAD_MS = 250


@dataclass(frozen=True)
class HighlightPick:
    title: str
    hook: str
    start_seq: int
    end_seq: int
    start_quote: str = ""
    end_quote: str = ""


def _fmt_s(ms: int) -> str:
    return f"{ms / 1000:.0f}s"


def build_highlights_messages(
    *,
    topic: str,
    language: str,
    segments: list[TimelineSegment],
    speakers: list[TimelineSpeaker],
    max_items: int = 2,
) -> list[dict[str, str]]:
    names = ", ".join(f"{s.name} ({s.role})" for s in speakers)
    lines = []
    for seg in segments:
        lines.append(
            f"[{seg.seq_index}] {seg.speaker_name} ({seg.turn_type}, {_fmt_s(seg.end_ms - seg.start_ms)}): {seg.text}"
        )
    transcript = "\n".join(lines)
    debater_names = [s.name for s in speakers if s.role == "debater"]
    system = (
        "You are a video editor picking the most viral moments of an AI debate for vertical short videos "
        f"({MIN_SHORT_MS // 1000}-{MAX_SHORT_MS // 1000} seconds each). Reply with JSON only."
    )
    user = (
        f"Topic: {topic}\nLanguage of the debate: {language}\nSpeakers: {names}\n\n"
        f"Transcript (turn index, speaker, type, spoken duration):\n{transcript}\n\n"
        f"Pick up to {max_items} moments. Each moment is a contiguous range of turns, ideally a sharp exchange "
        "between debaters (a claim and the reply). Because turns can be long, also give the exact opening words "
        "(start_quote, 4-8 words copied verbatim from the transcript) where the moment should start and the exact "
        "closing words (end_quote, 4-8 words verbatim) where it should end, so the clip fits the time limit.\n"
        f"Also decide who won the debate based on the judge's verdict if present: one of {debater_names} or null.\n"
        "Write title and hook in the language of the debate. The hook is a punchy quote or question (max 12 words) "
        "shown before the clip.\n"
        'Return: {"winner_name": string|null, "highlights": [{"title": string, "hook": string, '
        '"start_seq": number, "end_seq": number, "start_quote": string, "end_quote": string}]}'
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def parse_highlights(payload: Any) -> tuple[str | None, list[HighlightPick]]:
    if not isinstance(payload, dict):
        return None, []
    winner = payload.get("winner_name")
    picks: list[HighlightPick] = []
    for item in payload.get("highlights") or []:
        if not isinstance(item, dict):
            continue
        raw_start = item.get("start_seq")
        raw_end = item.get("end_seq", raw_start)
        if raw_start is None:
            continue
        try:
            start_seq = int(raw_start)
            end_seq = int(raw_end if raw_end is not None else raw_start)
        except (TypeError, ValueError):
            continue
        if end_seq < start_seq:
            start_seq, end_seq = end_seq, start_seq
        picks.append(
            HighlightPick(
                title=str(item.get("title") or "").strip()[:120] or "Highlight",
                hook=str(item.get("hook") or "").strip()[:140],
                start_seq=start_seq,
                end_seq=end_seq,
                start_quote=str(item.get("start_quote") or "").strip(),
                end_quote=str(item.get("end_quote") or "").strip(),
            )
        )
    return (str(winner).strip() if winner else None), picks


_WORD_RE = re.compile(r"[^\w']+", re.UNICODE)


def normalize_token(token: str) -> str:
    return _WORD_RE.sub("", token.lower())


def locate_quote(
    words: list[tuple[str, int, int]], quote: str, *, from_end: bool = False
) -> int | None:
    """Index of the word where `quote` starts (or ends when from_end) using fuzzy token matching.

    `words` = [(text, start_ms, end_ms)]. Returns None when nothing matches well enough."""
    q = [normalize_token(t) for t in quote.split() if normalize_token(t)]
    if not q or not words:
        return None
    tokens = [normalize_token(w[0]) for w in words]
    n = len(q)
    best_ratio = 0.0
    best_index: int | None = None
    for i in range(0, max(1, len(tokens) - n + 1)):
        window = tokens[i : i + n]
        ratio = difflib.SequenceMatcher(None, window, q, autojunk=False).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_index = i
    if best_index is None or best_ratio < 0.6:
        return None
    return min(best_index + n - 1, len(words) - 1) if from_end else best_index


def snap_highlight(
    segments: list[TimelineSegment], pick: HighlightPick, index: int, total_ms: int
) -> TimelineHighlight | None:
    """Convert a turn range + quotes into absolute ms, clamped to the short-video limits."""
    by_seq = {s.seq_index: s for s in segments}
    chosen = [by_seq[i] for i in range(pick.start_seq, pick.end_seq + 1) if i in by_seq]
    if not chosen:
        return None
    words: list[tuple[str, int, int]] = []
    for seg in chosen:
        words.extend((w.w, seg.start_ms + w.s, seg.start_ms + w.e) for w in seg.words)
    start_ms = chosen[0].start_ms
    end_ms = chosen[-1].end_ms
    if words:
        s_idx = locate_quote(words, pick.start_quote) if pick.start_quote else None
        e_idx = locate_quote(words, pick.end_quote, from_end=True) if pick.end_quote else None
        if s_idx is not None:
            start_ms = words[s_idx][1]
        if e_idx is not None and words[e_idx][2] > start_ms:
            end_ms = words[e_idx][2]
        # Enforce the length window at word boundaries.
        if end_ms - start_ms > MAX_SHORT_MS:
            end_ms = max(
                (e for _, _, e in words if e - start_ms <= MAX_SHORT_MS),
                default=start_ms + MAX_SHORT_MS,
            )
        if end_ms - start_ms < MIN_SHORT_MS:
            end_ms = min(chosen[-1].end_ms, start_ms + MIN_SHORT_MS)
    start_ms = max(0, start_ms - PAD_MS)
    end_ms = min(total_ms, end_ms + PAD_MS)
    if end_ms <= start_ms:
        return None
    return TimelineHighlight(
        index=index,
        title=pick.title,
        hook=pick.hook or chosen[0].text.split(".")[0][:120],
        start_ms=start_ms,
        end_ms=end_ms,
        seq_indexes=[s.seq_index for s in chosen],
    )


def fallback_highlights(segments: list[TimelineSegment], total_ms: int) -> list[TimelineHighlight]:
    """Without an LLM: the last exchange between two debaters, clipped to the limit."""
    debaters = [
        s for s in segments if s.turn_type in ("rebuttal", "closing", "argument", "opening")
    ]
    if not debaters:
        return []
    pair = debaters[-2:] if len(debaters) >= 2 else debaters[-1:]
    pick = HighlightPick(
        title="Key exchange",
        hook=pair[0].text.split(".")[0][:120],
        start_seq=pair[0].seq_index,
        end_seq=pair[-1].seq_index,
    )
    hl = snap_highlight(segments, pick, 0, total_ms)
    return [hl] if hl else []


def match_speaker(name: str | None, speakers: list[TimelineSpeaker]) -> TimelineSpeaker | None:
    if not name:
        return None
    needle = name.strip().lower()
    for sp in speakers:
        if sp.role != "debater":
            continue
        if sp.name.lower() == needle or needle in sp.name.lower() or sp.name.lower() in needle:
            return sp
    return None


def extract_winner(verdict_text: str, speakers: list[TimelineSpeaker]) -> TimelineSpeaker | None:
    """Regex fallback: the debater named closest after 'winner' in the verdict."""
    text = verdict_text or ""
    debaters = [s for s in speakers if s.role == "debater"]
    if not debaters:
        return None
    m = re.search(r"winner[\s\S]{0,160}", text, re.IGNORECASE) or re.search(
        r"побед[а-яё]*[\s\S]{0,160}",  # noqa: RUF001 (Cyrillic on purpose)
        text,
        re.IGNORECASE,
    )
    window = m.group(0) if m else text[:400]
    best: tuple[int, TimelineSpeaker] | None = None
    for sp in debaters:
        pos = window.lower().find(sp.name.lower())
        if pos >= 0 and (best is None or pos < best[0]):
            best = (pos, sp)
    return best[1] if best else None
