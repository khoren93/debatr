"""The beat grid of a generated soundtrack (services/media/beats)."""

from app.services.media import beats

BPM = 92
PERIOD = 60_000 / BPM


def track(
    offset_ms: int, seconds: int = 30, *, kick_every: int = 1, strong_odd: bool = False
) -> list[float]:
    """A bass envelope at 10 ms: a hit on every beat from `offset_ms`, louder on half of them."""
    env = [0.05] * (seconds * 100)
    k = 0
    while (i := int((offset_ms + k * PERIOD) // 10)) < len(env):
        if k % kick_every == 0:
            env[i] = 1.0 if (k % 2 == 1) == strong_odd else 0.6
            if i + 1 < len(env):
                env[i + 1] = 0.5
        k += 1
    return env


def test_finds_the_phase_of_the_grid() -> None:
    for offset in (0, 370, 645):
        beat = beats.beat_grid(track(offset), bpm=BPM)
        assert beat is not None
        # Phases one period apart are the same grid.
        apart = abs(beat.offset_ms - offset) % PERIOD
        assert min(apart, PERIOD - apart) <= 10
        assert beat.bpm == BPM


def test_tells_which_half_of_the_beats_is_stronger() -> None:
    assert beats.beat_grid(track(200), bpm=BPM).accent == 0  # type: ignore[union-attr]
    assert beats.beat_grid(track(200, strong_odd=True), bpm=BPM).accent == 1  # type: ignore[union-attr]


def test_no_grid_without_a_clear_beat_or_long_enough_track() -> None:
    assert beats.beat_grid([0.3] * 3000, bpm=BPM) is None
    assert beats.beat_grid(track(100, seconds=5), bpm=BPM) is None
    assert beats.beat_grid([], bpm=BPM) is None


def test_onsets_keep_only_rises() -> None:
    assert beats.onsets([0.2, 0.5, 0.1, 0.4]) == [0.0, 0.3, 0.0, 0.30000000000000004]
    assert beats.onsets([]) == []
