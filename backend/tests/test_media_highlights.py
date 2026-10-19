import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.schemas.timeline import TimelineSegment, TimelineSpeaker, TimelineWord
from app.services.media import jobs
from app.services.media.highlights import (
    HighlightPick,
    build_highlights_messages,
    extract_winner,
    fallback_highlights,
    locate_quote,
    match_speaker,
    parse_highlights,
    snap_highlight,
)

SPEAKERS = [
    TimelineSpeaker(
        id="participant_0",
        name="Moderator",
        role="moderator",
        model="m",
        color="#999",
        mascot="cube",
    ),
    TimelineSpeaker(
        id="participant_1", name="Nova", role="debater", model="gpt", color="#0ff", mascot="orb"
    ),
    TimelineSpeaker(
        id="participant_2", name="Atlas", role="debater", model="gem", color="#f80", mascot="bolt"
    ),
]


def _segment(
    seq: int, speaker: TimelineSpeaker, start_ms: int, text: str, turn_type: str = "rebuttal"
) -> TimelineSegment:
    tokens = text.split()
    per = 400
    words = [TimelineWord(w=t, s=i * per, e=i * per + per - 50) for i, t in enumerate(tokens)]
    return TimelineSegment(
        seq_index=seq,
        speaker_id=speaker.id,
        speaker_name=speaker.name,
        round_id="round_2",
        turn_type=turn_type,
        start_ms=start_ms,
        end_ms=start_ms + len(tokens) * per,
        audio=f"turns/{seq:03d}.wav",
        text=text,
        words=words,
    )


def test_parse_highlights_tolerates_bad_items() -> None:
    winner, picks = parse_highlights(
        {
            "winner_name": "Nova",
            "highlights": [
                {"title": "t", "hook": "h", "start_seq": "3", "end_seq": 2},
                "junk",
                {"title": "x"},
            ],
        }
    )
    assert winner == "Nova"
    assert picks == [HighlightPick(title="t", hook="h", start_seq=2, end_seq=3)]
    assert parse_highlights("nope") == (None, [])


def test_locate_quote_fuzzy() -> None:
    words = [
        (w, i * 100, i * 100 + 90)
        for i, w in enumerate(
            ["So", "a", "hammer", "should", "hit", "your", "thumb", "if", "you", "ask", "nicely"]
        )
    ]
    assert locate_quote(words, "hammer should hit") == 2
    assert locate_quote(words, "ask nicely!", from_end=True) == 10
    assert locate_quote(words, "completely unrelated words here") is None


def test_snap_highlight_uses_quotes_and_limits() -> None:
    text_a = " ".join(f"w{i}" for i in range(60))  # 24 s
    text_b = " ".join(f"v{i}" for i in range(60))  # 24 s
    seg_a = _segment(3, SPEAKERS[1], 0, text_a)
    seg_b = _segment(4, SPEAKERS[2], 25_000, text_b)
    pick = HighlightPick(
        title="t",
        hook="h",
        start_seq=3,
        end_seq=4,
        start_quote="w10 w11 w12",
        end_quote="v20 v21 v22",
    )
    hl = snap_highlight([seg_a, seg_b], pick, 0, 60_000)
    assert hl is not None
    assert hl.start_ms == 10 * 400 - 250
    assert hl.end_ms == 25_000 + 22 * 400 + 350 + 250
    assert hl.seq_indexes == [3, 4]

    # No quotes: whole range, clipped to the maximum length at a word boundary.
    hl2 = snap_highlight([seg_a, seg_b], HighlightPick("t", "h", 3, 4), 1, 60_000)
    assert hl2 is not None and hl2.end_ms - hl2.start_ms <= 60_000 + 500


def test_fallback_highlights_and_winner() -> None:
    seg_m = _segment(
        0, SPEAKERS[0], 0, "welcome everyone to the debate", turn_type="moderator_intro"
    )
    seg_a = _segment(1, SPEAKERS[1], 5_000, "yes we should refuse harmful requests")
    seg_b = _segment(2, SPEAKERS[2], 10_000, "no the user must stay in control")
    hls = fallback_highlights([seg_m, seg_a, seg_b], 20_000)
    assert len(hls) == 1 and hls[0].seq_indexes == [1, 2]

    assert extract_winner("## Winner\n**Atlas** wins by a narrow margin.", SPEAKERS) == SPEAKERS[2]
    assert extract_winner("Победа присуждается Нове.", SPEAKERS) is None  # name not present
    assert match_speaker("nova", SPEAKERS) == SPEAKERS[1]
    assert match_speaker(None, SPEAKERS) is None


def test_build_highlights_messages_contains_transcript() -> None:
    seg = _segment(1, SPEAKERS[1], 0, "hello world")
    messages = build_highlights_messages(
        topic="T", language="English", segments=[seg], speakers=SPEAKERS
    )
    assert messages[0]["role"] == "system"
    assert "[1] Nova (rebuttal, 1s): hello world" in messages[1]["content"]
    assert "Nova" in messages[1]["content"] and "Atlas" in messages[1]["content"]


def _debate_segments() -> list[TimelineSegment]:
    return [
        _segment(1, SPEAKERS[1], 0, "Cars clog every street we have"),
        _segment(2, SPEAKERS[2], 3000, "Yet shops die without the drivers"),
    ]


def test_highlights_key_follows_the_transcript_not_the_voices() -> None:
    segments = _debate_segments()
    key = jobs.highlights_key("host/model", "Cars?", "English", segments)
    slower = [s.model_copy(update={"end_ms": s.end_ms + 900}) for s in segments]
    assert jobs.highlights_key("host/model", "Cars?", "English", slower) == key
    edited = [segments[0], segments[1].model_copy(update={"text": "Shops survive"})]
    assert jobs.highlights_key("host/model", "Cars?", "English", edited) != key
    assert jobs.highlights_key("other/model", "Cars?", "English", segments) != key


def _picks(
    model: str, cache: Path, segments: list[TimelineSegment]
) -> tuple[str | None, list[HighlightPick]]:
    paths: Any = SimpleNamespace(highlights=cache)
    return jobs._host_picks(
        model, paths, topic="Cars?", language="English", segments=segments, speakers=SPEAKERS
    )


def test_the_host_model_is_asked_once_per_transcript(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, levers: dict
) -> None:
    calls: list[str] = []
    answer = {
        "winner_name": "Nova",
        "highlights": [{"title": "Clash", "hook": "Who pays?", "start_seq": 1, "end_seq": 2}],
    }

    def complete(model: str, _messages: Any, **kw: Any) -> tuple[str, dict]:
        calls.append(model)
        assert kw["purpose"] == "highlights"
        return json.dumps(answer), {}

    monkeypatch.setattr(jobs, "complete", complete)
    monkeypatch.setattr(jobs.free_quota, "wait_for_slot", lambda _deadline: True)
    cache, segments = tmp_path / "highlights.json", _debate_segments()
    winner, picks = _picks("vendor/host-model", cache, segments)
    assert (winner, [p.title for p in picks]) == ("Nova", ["Clash"])
    assert _picks("vendor/host-model", cache, segments) == (winner, picks)  # from the cache
    assert calls == ["vendor/host-model"]
    _picks("vendor/other-model", cache, segments)  # another host: asked again
    assert calls == ["vendor/host-model", "vendor/other-model"]

    cache.write_text("{broken")  # a damaged cache is a miss, never an error
    _picks("vendor/host-model", cache, segments)
    assert len(calls) == 3


def test_host_picks_respect_levers_and_the_free_quota(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, levers: dict
) -> None:
    def complete(*_a: Any, **_kw: Any) -> tuple[str, dict]:
        raise AssertionError("must not be asked")

    monkeypatch.setattr(jobs, "complete", complete)
    levers["disabled_models"] = ["vendor/off-model"]
    with pytest.raises(RuntimeError, match="turned off"):
        _picks("vendor/off-model", tmp_path / "h.json", _debate_segments())
    monkeypatch.setattr(jobs.free_quota, "wait_for_slot", lambda _deadline: False)
    with pytest.raises(RuntimeError, match="slot"):
        _picks("vendor/host:free", tmp_path / "h.json", _debate_segments())
    # _pick_highlights turns either into the deterministic fallback.
    paths: Any = SimpleNamespace(highlights=tmp_path / "h.json")
    monkeypatch.setattr(jobs.settings, "OPENROUTER_API_KEY", "sk-test")
    highlights, winner = jobs._pick_highlights(
        model="vendor/host:free",
        paths=paths,
        topic="Cars?",
        language="English",
        segments=_debate_segments(),
        speakers=SPEAKERS,
        total_ms=6000,
    )
    assert winner is None and highlights == fallback_highlights(_debate_segments(), 6000)
