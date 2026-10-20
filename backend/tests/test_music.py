"""The rap battle's soundtrack (media/music.py and the battle build in media/jobs.py): the
composition plan, the Music API client and its answer, words per section, the cache, prices,
the estimate and the whole build with ffmpeg and ElevenLabs faked. Pure."""

import itertools
import json
import re
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.core.config import settings
from app.models.models import Debate, Turn
from app.schemas.media import MediaOptions
from app.schemas.timeline import TimelineSegment, TimelineSpeaker, TimelineWord
from app.services import ledger
from app.services.credits import music_charge_usd
from app.services.estimate import WORDS_PER_MINUTE, estimate_debate
from app.services.formats import FORMATS
from app.services.media import ffmpeg, jobs, music
from app.services.media.paths import MediaPaths
from app.services.media.tts import elevenlabs

BAR = music.BAR_MS
GRITTY, SHARP = music.FLOWS["gritty"], music.FLOWS["sharp"]


def _verses(lines: int = 4, rounds: int = 2) -> list[music.Verse]:
    lyrics = "\n".join(f"line {i}" for i in range(lines))
    out = []
    seq = 1
    for r in range(1, rounds + 1):
        for flow in (GRITTY, SHARP) if r % 2 else (SHARP, GRITTY):
            out.append(music.Verse(seq, r, lyrics, flow))
            seq += 1
    return out


# --- the plan -----------------------------------------------------------------------------------


def test_the_plan_frames_the_verses() -> None:
    sections = music.build_plan(20_000, _verses(), 30_000)
    assert [s.kind for s in sections] == [
        "intro",
        "verse",
        "verse",
        "break",
        "verse",
        "verse",
        "outro",
    ]
    intro, first, *_rest, outro = sections
    # The MC talks over the intro: a lead-in, the speech, one more bar.
    assert intro.duration_ms == music.VOICE_LEAD_MS + 20_000 + BAR
    assert outro.duration_ms == music.VOICE_LEAD_MS + 30_000 + BAR
    assert first.duration_ms == 5 * BAR and first.seq_index == 1  # 4 lines and a bar to breathe
    assert first.text == "[Verse]\nline 0\nline 1\nline 2\nline 3"
    assert "deep gritty baritone voice" in first.styles and "rap vocals" in first.styles
    assert "vocals" in intro.negative and "vocals" in outro.negative
    assert "92 BPM" in intro.styles  # the first section sets the beat for the whole track
    assert sections[3].text.startswith("[Round 2]")
    assert sections[4].styles[0] == "female rapper"  # round 2: the second rapper opens


def test_every_verse_names_its_voice_and_the_one_it_must_not_have() -> None:
    # Round 2 of a male / female battle once came out with its last verse in the female voice:
    # the model kept the voice of the verse before. The plan now says it both ways.
    verses = [s for s in music.build_plan(0, _verses(), 0) if s.kind == "verse"]
    voices = ["male", "female", "female", "male"]  # round 2: the second rapper opens
    for section, voice in zip(verses, voices, strict=True):
        other = music.OTHER_VOICE[voice]
        assert f"solo {voice} vocals" in section.styles
        assert {f"{other} vocals", f"{other} rapper"} <= set(section.negative)
        assert not any(re.search(rf"\b{other}\b", style) for style in section.styles)
    # The mic changes hands to the other voice: said; the same voice again after a break: not.
    handovers = [any("takes the mic" in s for s in v.styles) for v in verses]
    assert handovers == [False, True, False, True]


def test_sections_stay_within_the_apis_limits() -> None:
    short = music.build_plan(0, [music.Verse(1, 1, "one", GRITTY)], 0)
    assert all(s.duration_ms >= music.MIN_SECTION_MS for s in short)
    long_lyrics = "\n".join(["bar"] * 80)
    assert music.verse_ms(long_lyrics) == music.MAX_SECTION_MS
    with pytest.raises(ValueError, match="more than one track holds"):
        music.build_plan(0, [music.Verse(i, 1, long_lyrics, GRITTY) for i in range(6)], 0)


def test_payload_key_and_windows() -> None:
    sections = music.build_plan(10_000, _verses(rounds=1), 10_000)
    payload = music.plan_payload(sections)
    assert len(payload["chunks"]) == 4
    assert set(payload["chunks"][1]) == {
        "text",
        "duration_ms",
        "positive_styles",
        "negative_styles",
    }
    key = music.plan_key(sections)
    assert key == music.plan_key(music.build_plan(10_000, _verses(rounds=1), 10_000))
    changed = _verses(rounds=1)
    changed[0] = music.Verse(1, 1, "other words", GRITTY)
    assert key != music.plan_key(music.build_plan(10_000, changed, 10_000))
    wins = music.windows(sections)
    assert wins[0][0] == 0 and wins[-1][1] == music.track_ms(sections)
    assert all(a[1] == b[0] for a, b in itertools.pairwise(wins))


def test_flows_default_to_two_different_voices() -> None:
    assert music.flow_for({}, "participant_1", 0) is GRITTY
    assert music.flow_for({}, "participant_2", 1) is SHARP
    assert music.flow_for({"participant_2": "cold"}, "participant_2", 1).voice == "female"
    assert music.flow_for({"participant_1": "nope"}, "participant_1", 0) is GRITTY
    assert {GRITTY.voice, SHARP.voice} == {"male", "female"}


def test_words_per_section() -> None:
    words = [
        music.SungWord("{DJ", 0, 0),
        music.SungWord("scratch}", 0, 0),
        music.SungWord("[Verse]", 6_000, 6_000),
        music.SungWord("I", 7_400, 7_600),
        music.SungWord("read", 7_600, 7_900),
        music.SungWord("you", 18_220, 18_400),
    ]
    assert music.words_between(words, 5_000, 18_000) == [
        TimelineWord(w="I", s=2_400, e=2_600),
        TimelineWord(w="read", s=2_600, e=2_900),
    ]
    assert [w.w for w in music.words_between(words, 18_000, 30_000)] == ["you"]
    assert music.parse_words([{"word": "a", "start_ms": 1, "end_ms": 2}, "x", {"word": ""}]) == [
        music.SungWord("a", 1, 2)
    ]


def test_prices() -> None:
    assert music.music_usd(60_000) == 0.15
    assert music_charge_usd(90_000, 0.3) == music_charge_usd(90_000, 0.30)
    assert float(music_charge_usd(90_000, 0.3)) == 0.45
    assert float(music_charge_usd(0, 0.3)) == 0.0


# --- the API ----------------------------------------------------------------------------------


def _multipart(meta: dict[str, Any], audio: bytes) -> tuple[str, bytes]:
    boundary = "b0undary"
    body = (
        (
            f"--{boundary}\r\nContent-Type: application/json\r\n\r\n{json.dumps(meta)}\r\n"
            f"--{boundary}\r\nContent-Type: audio/mpeg\r\nContent-Transfer-Encoding: binary\r\n\r\n"
        ).encode()
        + audio
        + f"\r\n--{boundary}--\r\n".encode()
    )
    return f"multipart/mixed; boundary={boundary}", body


def test_the_detailed_answer_is_parsed() -> None:
    meta = {"words_timestamps": [{"word": "yo", "start_ms": 100, "end_ms": 300}], "song_id": "s1"}
    content_type, body = _multipart(meta, b"ID3fake-mp3")
    track = music.parse_detailed(content_type, body)
    assert track.audio == b"ID3fake-mp3" and track.song_id == "s1"
    assert track.words == [music.SungWord("yo", 100, 300)]
    with pytest.raises(music.MusicError, match="without audio"):
        music.parse_detailed(*_multipart(meta, b""))


def test_compose_calls_the_api_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(music.time, "sleep", lambda _s: None)
    seen: list[httpx.Request] = []
    answers = [httpx.Response(503, json={"detail": "busy"})]
    content_type, body = _multipart({"words_timestamps": []}, b"mp3")
    answers.append(
        httpx.Response(200, headers={"content-type": content_type, "song-id": "s9"}, content=body)
    )

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return answers.pop(0)

    sections = music.build_plan(5_000, _verses(rounds=1), 5_000)
    track = music.compose(sections, api_key="k", transport=httpx.MockTransport(handler))
    assert track.audio == b"mp3" and track.song_id == "s9" and len(seen) == 2
    request = seen[0]
    assert request.url.path == "/v1/music/detailed"
    assert request.url.params["output_format"] == "mp3_44100_128"
    sent = json.loads(request.content)
    assert sent["model_id"] == "music_v2_5" and sent["with_timestamps"] is True
    assert sent["composition_plan"] == music.plan_payload(sections)
    assert request.headers["xi-api-key"] == "k"


def test_compose_reports_elevenlabs_refusals() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        detail = {"status": "bad_prompt", "message": "The lyrics mention a real artist"}
        return httpx.Response(422, json={"detail": detail})

    sections = music.build_plan(5_000, _verses(rounds=1), 5_000)
    with pytest.raises(music.MusicError, match="422: The lyrics mention a real artist") as caught:
        music.compose(sections, api_key="k", transport=httpx.MockTransport(handler))
    assert caught.value.status_code == 422


def test_the_cache_keeps_track_and_words(tmp_path: Path) -> None:
    track = music.Track(b"mp3", [music.SungWord("yo", 1, 2)], "s1")
    music.store(tmp_path, "k1", track)
    assert music.cached(tmp_path, "k1") == track
    assert music.cached(tmp_path, "nope") is None


def test_a_users_key_needs_a_paid_plan() -> None:
    plans = {"free-key": "free", "paid-key": "starter"}

    def handler(request: httpx.Request) -> httpx.Response:
        tier = plans.get(request.headers["xi-api-key"])
        return httpx.Response(200, json={"tier": tier}) if tier else httpx.Response(401)

    transport = httpx.MockTransport(handler)
    elevenlabs._plan_cache.clear()
    assert elevenlabs.music_allowed("paid-key", transport=transport) is True
    assert elevenlabs.music_allowed("free-key", transport=transport) is False
    assert elevenlabs.music_allowed("bad-key", transport=transport) is False


def test_ducking_filter() -> None:
    assert ffmpeg.duck_filter([], 0.3) == "anull"
    assert ffmpeg.duck_filter([(600, 20_600), (90_000, 120_500)], 0.3) == (
        "volume=0.3:enable='between(t,0.600,20.600)+between(t,90.000,120.500)'"
    )


def test_music_lands_in_its_own_ledger_category() -> None:
    from app.models.models import CreditTransaction

    row = CreditTransaction(kind="media", description="Music: Tabs or spaces?")
    row.provider_ref = f"debate:{uuid.uuid4()}:music:123"
    assert ledger.category(row) == "music"
    assert ledger.title(row) == "Tabs or spaces?"


# --- the estimate ------------------------------------------------------------------------------


def _battle_conf(**plan: Any) -> dict[str, Any]:
    return {
        "format": "rap_battle",
        "topic": "Tabs or spaces?",
        "num_rounds": 2,
        "length_preset": "very_short",
        "participants": [
            {"role": "moderator", "model_id": "m/free:free", "display_name": "MC"},
            {"role": "debater", "model_id": "m/free:free", "display_name": "A"},
            {"role": "debater", "model_id": "m/free:free", "display_name": "B"},
        ],
        "media_plan": {"provider": "elevenlabs", "outputs": ["audio"], **plan},
    }


def _estimate(conf: dict[str, Any], provider: str | None, own_tts_key: bool = False) -> Any:
    return estimate_debate(
        conf,
        {},
        own_key=True,
        tts_provider=provider,
        own_tts_key=own_tts_key,
        tts_price_per_1k=0.15,
        markup=1.2,
        music_price_per_min=0.3,
    )


def test_a_battle_is_estimated_with_its_music() -> None:
    conf = _battle_conf()
    rap = FORMATS["rap_battle"]
    est = _estimate(conf, "elevenlabs")
    assert est.music_ms == rap.track_ms(conf, WORDS_PER_MINUTE) > 0
    assert est.music_cost_usd == round(est.music_ms / 60_000 * 0.3, 6)
    # Only the MC and the judge's announcement are voiced: (MC words + its words) x 6 characters.
    assert est.tts_chars == int((50 + rap.voiced_verdict_words(conf)) * 6)
    assert est.duration_ms == est.music_ms + 4000
    assert est.credits_cost_usd == pytest.approx(est.music_cost_usd + est.tts_cost_usd)
    own = _estimate(conf, "elevenlabs", own_tts_key=True)
    assert own.credits_cost_usd == 0 and own.music_ms == est.music_ms
    lyrics_only = _estimate(conf, None)
    assert lyrics_only.music_ms == 0 and lyrics_only.credits_cost_usd == 0
    longer = _estimate({**conf, "num_rounds": 3, "length_preset": "medium"}, "elevenlabs")
    assert longer.music_ms > est.music_ms


# --- the whole build, ElevenLabs and ffmpeg faked -----------------------------------------------------


class FakeProvider:
    name = "elevenlabs"


def test_the_battle_build(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, usage_rows: list
) -> None:
    monkeypatch.setattr(settings, "MEDIA_ROOT", str(tmp_path))
    debate = Debate(
        id=uuid.uuid4(), title="Tabs or spaces?", config_json=_battle_conf(), verdict_json={}
    )
    paths = MediaPaths(str(debate.id))

    def turn(seq: int, round_id: str, turn_type: str, speaker: str, name: str, text: str) -> Turn:
        return Turn(
            seq_index=seq,
            round_id=round_id,
            turn_type=turn_type,
            speaker_id=speaker,
            speaker_name=name,
            text=text,
        )

    turns = [
        turn(0, "round_1", "moderator_intro", "participant_0", "MC", "Make some noise!"),
        turn(1, "round_1", "verse", "participant_1", "A", "a one\na two"),
        turn(2, "round_1", "verse", "participant_2", "B", "b one\nb two"),
        turn(3, "verdict", "verdict", "judge", "Verdict", "A wins, 9 to 8."),
    ]
    speakers = [
        TimelineSpeaker(
            id="participant_0", name="MC", role="moderator", model="m", color="#fff", mascot="orb"
        ),  # type: ignore[arg-type]
        TimelineSpeaker(
            id="participant_1", name="A", role="debater", model="m", color="#fff", mascot="orb"
        ),  # type: ignore[arg-type]
        TimelineSpeaker(
            id="participant_2", name="B", role="debater", model="m", color="#fff", mascot="orb"
        ),  # type: ignore[arg-type]
        TimelineSpeaker(
            id="judge", name="Verdict", role="judge", model="m", color="#fff", mascot="orb"
        ),  # type: ignore[arg-type]
    ]
    by_id = {s.id: s for s in speakers}
    cleaned = [(t, by_id[t.speaker_id], t.text) for t in turns]

    voiced_ms = {0: 8_000, 3: 6_000}

    def synthesize(_provider: Any, _paths: Any, task: Any, *_args: Any) -> Any:
        wav = paths.turn_wav(task.seq_index)
        return jobs.TurnAudio(
            task.seq_index,
            wav,
            voiced_ms[task.seq_index],
            [TimelineWord(w="hi", s=0, e=100)],
            [0.5],
            120,
            None,
            cached=False,
        )

    composed: list[list[music.Section]] = []

    def compose(sections: list[music.Section], *, api_key: str | None = None) -> music.Track:
        composed.append(sections)
        wins = music.windows(sections)
        words = [
            music.SungWord("a", wins[1][0] + 2_000, wins[1][0] + 2_300),
            music.SungWord("b", wins[2][0] + 2_000, wins[2][0] + 2_200),
        ]
        return music.Track(b"mp3", words, "song")

    mixed: list[Any] = []
    finished: dict[str, Any] = {}
    monkeypatch.setattr(jobs, "_synthesize_turn", synthesize)
    monkeypatch.setattr(music, "compose", compose)
    monkeypatch.setattr(jobs, "set_media_state", lambda *_a, **_k: None)
    monkeypatch.setattr(ffmpeg, "normalize_music", lambda *_a, **_k: None)
    monkeypatch.setattr(
        ffmpeg, "mix_over", lambda music_wav, voices, *_a, **_k: mixed.append(voices)
    )
    monkeypatch.setattr(ffmpeg, "probe_duration_ms", lambda _p: 99_000)
    monkeypatch.setattr(ffmpeg, "envelope", lambda _p, **_k: [0.1] * 2_000)
    monkeypatch.setattr(jobs, "_finish", lambda *_a, **kw: finished.update(kw))

    options = MediaOptions(
        provider="elevenlabs",
        voices={"participant_0": "v-mc", "judge": "v-judge"},
        flows={"participant_2": "cold"},
    )
    built = jobs._build_battle(
        None,  # type: ignore[arg-type]
        debate,
        paths,
        turns=turns,
        cleaned=cleaned,
        speakers=speakers,
        provider=FakeProvider(),  # type: ignore[arg-type]
        options=options,
        force=False,
        code="en",
        tts_key="system",
        music_key=None,
        judge_model="m",
    )
    [sections] = composed
    assert [s.kind for s in sections] == ["intro", "verse", "verse", "outro"]
    assert sections[1].styles[0] == "male rapper" and "cool calm low voice" in sections[2].styles
    wins = music.windows(sections)
    assert sections[0].duration_ms == music.voiced_ms(8_000)
    # Two lines a verse: three bars (the lines are kept when the audio tags are cleaned).
    assert sections[1].duration_ms == 3 * BAR and sections[1].text == "[Verse]\na one\na two"
    # The MC and the judge talk over the intro and the outro.
    assert mixed == [
        [
            (paths.turn_wav(0), music.VOICE_LEAD_MS, 8_000),
            (paths.turn_wav(3), wins[-1][0] + music.VOICE_LEAD_MS, 6_000),
        ]
    ]
    segments: list[TimelineSegment] = finished["segments"]
    assert [(s.seq_index, s.start_ms, s.end_ms) for s in segments] == [
        (0, music.VOICE_LEAD_MS, music.VOICE_LEAD_MS + 8_000),
        (1, *wins[1]),
        (2, *wins[2]),
        (3, wins[-1][0] + music.VOICE_LEAD_MS, wins[-1][0] + music.VOICE_LEAD_MS + 6_000),
    ]
    assert segments[1].words == [TimelineWord(w="a", s=2_000, e=2_300)]
    assert segments[1].text == "a one\na two" and segments[1].round_label == "Round 1"
    assert finished["total_ms"] == 99_000 and finished["gap_ms"] == 0 and finished["visuals"] == []
    assert built.music_ms == music.track_ms(sections) and built.chars == 240
    assert finished["stats"].music_cached is False
    music_rows = [r for r in usage_rows if r.purpose == "music"]
    assert len(music_rows) == 1 and float(music_rows[0].cost_usd) == music.music_usd(built.music_ms)

    # The same lyrics again: the cached track, no call and nothing to charge.
    again = jobs._build_battle(
        None,  # type: ignore[arg-type]
        debate,
        paths,
        turns=turns,
        cleaned=cleaned,
        speakers=speakers,
        provider=FakeProvider(),  # type: ignore[arg-type]
        options=options,
        force=False,
        code="en",
        tts_key="system",
        music_key=None,
        judge_model="m",
    )
    assert len(composed) == 1 and again.music_ms == 0
    assert finished["stats"].music_cached is True


async def test_the_voice_list_says_whether_an_own_key_may_make_music(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api import routes_media

    class Voices:
        def available(self) -> bool:
            return True

        def list_voices(self, code: str, *, announcers: bool = False) -> list[Any]:
            return []

    monkeypatch.setattr(routes_media, "get_provider", lambda name, api_key=None: Voices())
    monkeypatch.setattr(routes_media, "music_allowed", lambda key: key == "paid-key")
    monkeypatch.setattr(routes_media, "system_key_status", lambda: (True, None))

    async def voices(provider: str, key: str | None) -> bool | None:
        out = await routes_media.media_voices(
            provider=provider,
            language="English",
            debate_id=None,
            participants=0,
            x_tts_key=key,
            db=None,  # type: ignore[arg-type]
        )
        return out.paid_plan

    assert await voices("elevenlabs", "paid-key") is True
    assert await voices("elevenlabs", "free-key") is False
    # The system key (ours, paid) and Edge are not asked.
    assert await voices("elevenlabs", None) is None
    assert await voices("edge", None) is None


# --- the result -----------------------------------------------------------------------------


def test_the_judges_score_sheet_closes_the_battle() -> None:
    from app.api import serializers
    from app.schemas.timeline import TimelineSegment, TimelineVerdict
    from app.schemas.visuals import ScoreboardScene
    from app.services.verdict import stored_round_scores

    verdict_json = {
        "source": "llm",
        "winner_id": "participant_1",
        "winner_name": "Ann",
        "headline": "Ann wins the battle.",
        "rounds": [
            {"round": 1, "scores": {"participant_1": 8, "participant_2": 7}},
            {"round": "two"},  # malformed rows are skipped, never fail the build
            {"round": 2, "scores": {"participant_1": 9, "participant_2": "7"}},
        ],
    }
    rounds = stored_round_scores(verdict_json)
    assert rounds == [
        {"round": 1, "scores": {"participant_1": 8, "participant_2": 7}},
        {"round": 2, "scores": {"participant_1": 9, "participant_2": 7}},
    ]
    out = serializers.verdict_out(Debate(verdict_json=verdict_json))
    assert out is not None and [r.round for r in out.rounds] == [1, 2]
    assert serializers.verdict_out(Debate(verdict_json={"winner_id": None})).rounds == []  # type: ignore[union-attr]

    words = [
        TimelineWord(w=w, s=i * 400, e=i * 400 + 300) for i, w in enumerate(["Ann", "wins", "it"])
    ]
    words += [TimelineWord(w="more", s=2_000 + i * 400, e=2_300 + i * 400) for i in range(60)]
    segment = TimelineSegment(
        seq_index=5,
        speaker_id="judge",
        speaker_name="The Judge",
        round_id="verdict",
        turn_type="verdict",
        start_ms=90_000,
        end_ms=120_000,
        audio="turns/005.wav",
        text="Ann wins it",
        words=words,
    )
    speakers = [
        TimelineSpeaker.model_validate(
            {"id": f"participant_{i}", "name": n, "role": r, "model": "m", "color": "#fff"}
            | {"mascot": "orb"}
        )
        for i, (n, r) in enumerate([("MC", "moderator"), ("Ann", "debater"), ("Bob", "debater")])
    ]
    verdict = TimelineVerdict(seq_index=5, winner_id="participant_1", winner_name="Ann")
    [board] = jobs._add_scoreboard([], [segment], speakers, verdict, verdict_json)
    assert isinstance(board.scene, ScoreboardScene)
    assert [r.scores["participant_1"] for r in board.scene.rounds] == [8, 9]
    # Shown from the announcement to the end of the verdict, while the judge goes round by round.
    assert board.start_ms < 90_400 and board.end_ms == 120_400


def test_turn_audio_cache_keys_keep_their_hash_without_a_stability() -> None:
    from app.services.media.jobs import _turn_hash

    before = _turn_hash("elevenlabs", "eleven_v3", "v", "Hi")
    assert _turn_hash("elevenlabs", "eleven_v3", "v", "Hi", None) == before
    assert _turn_hash("elevenlabs", "eleven_v3", "v", "Hi", 0.0) != before
