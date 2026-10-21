"""The beat of a generated soundtrack (rap battle), for the video to move on.

The music model is asked for a tempo (music.BPM) and keeps it; where the beats sit is measured.
The onsets of the track's low end (kick drum, bass) line up with one phase of the beat grid over
the whole track: sections do not start on a beat (the intro is as long as the MC's speech), but
the model keeps one continuous groove (measured on two battles: 92 BPM, phase within ±10 ms over
130 s). Pure, but for the envelope (ffmpeg.bass_envelope).
"""

from collections.abc import Sequence

from app.schemas.timeline import TimelineBeat

WINDOW_MS = 10
MIN_BEATS = 16
# The best phase against the average one: below this the track has no clear beat (no grid).
MIN_CONTRAST = 1.25


def onsets(envelope: Sequence[float]) -> list[float]:
    """How much louder each window is than the one before (rises only; the first has none)."""
    previous = [envelope[0], *envelope[:-1]] if envelope else []
    return [max(0.0, value - prev) for prev, value in zip(previous, envelope, strict=True)]


def _sum_at(values: Sequence[float], offset_ms: float, period_ms: float, window_ms: int) -> float:
    """The onsets on a grid, each read with one window of slack (the grid falls between windows)."""
    total = 0.0
    t = offset_ms
    while (i := int(t // window_ms)) < len(values):
        total += max(values[i], values[i + 1] if i + 1 < len(values) else 0.0)
        t += period_ms
    return total


def beat_grid(
    envelope: Sequence[float], *, bpm: float, window_ms: int = WINDOW_MS
) -> TimelineBeat | None:
    """The phase of a `bpm` grid that the track's onsets fit best, and which half of the beats
    is stronger; None for a track too short or without a clear beat."""
    values = onsets(envelope)
    period = 60_000 / bpm
    if bpm <= 0 or len(values) * window_ms < MIN_BEATS * period:
        return None
    scores = [
        (_sum_at(values, phase, period, window_ms), phase)
        for phase in range(0, int(period), window_ms)
    ]
    best, offset = max(scores)
    mean = sum(score for score, _ in scores) / len(scores)
    if mean <= 0 or best / mean < MIN_CONTRAST:
        return None
    even = _sum_at(values, offset, 2 * period, window_ms)
    odd = _sum_at(values, offset + period, 2 * period, window_ms)
    return TimelineBeat(bpm=bpm, offset_ms=offset, accent=0 if even >= odd else 1)
