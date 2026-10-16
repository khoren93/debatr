import base64
import json

import httpx

from app.services.media.tts import SpeakerRef, SynthRequest, VoiceInfo
from app.services.media.tts.elevenlabs import ElevenLabsProvider, estimate_usd, pick_default_voices


def _alignment(text: str) -> dict:
    chars = list(text)
    return {
        "characters": chars,
        "character_start_times_seconds": [i * 0.1 for i in range(len(chars))],
        "character_end_times_seconds": [i * 0.1 + 0.1 for i in range(len(chars))],
    }


def _provider(handler) -> ElevenLabsProvider:
    return ElevenLabsProvider(api_key="test", transport=httpx.MockTransport(handler))


def test_synthesize_with_timestamps() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert request.headers["xi-api-key"] == "test"
        body = json.loads(request.content)
        assert body["model_id"] == "eleven_v3" and body["text"].startswith("[calm]")
        return httpx.Response(
            200,
            json={
                "audio_base64": base64.b64encode(b"MP3").decode(),
                "alignment": _alignment("[calm] Hi there"),
            },
            headers={"character-cost": "8"},
        )

    result = _provider(handler).synthesize(SynthRequest("[calm] Hi there", "v1", "eleven_v3", "en"))
    assert result.audio == b"MP3" and result.char_cost == 8
    assert result.words is not None and [w.w for w in result.words] == ["Hi", "there"]
    assert "with-timestamps" in seen[0].url.path


def test_synthesize_context_text_only_for_supported_models() -> None:
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(
            200, json={"audio_base64": base64.b64encode(b"x").decode(), "alignment": None}
        )

    provider = _provider(handler)
    provider.synthesize(
        SynthRequest(
            "Hi", "v1", "eleven_v3", "en", previous_text="[warm] Before", next_text="After"
        )
    )
    # ElevenLabs rejects previous_text / next_text for eleven_v3 with HTTP 400.
    assert "previous_text" not in bodies[0] and "next_text" not in bodies[0]

    provider.synthesize(
        SynthRequest(
            "Hi",
            "v1",
            "eleven_multilingual_v2",
            "en",
            previous_text="[warm] Before",
            next_text="After",
        )
    )
    assert bodies[1]["previous_text"] == "Before" and bodies[1]["next_text"] == "After"


def test_synthesize_falls_back_to_forced_alignment() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path.endswith("/with-timestamps"):
            return httpx.Response(400, json={"detail": {"message": "timestamps unsupported"}})
        if request.url.path.endswith("/forced-alignment"):
            assert b'name="text"' in request.content
            return httpx.Response(200, json={"words": [{"text": "Hi", "start": 0.0, "end": 0.3}]})
        return httpx.Response(200, content=b"AUDIO")

    result = _provider(handler).synthesize(
        SynthRequest("[calm] Hi", "v1", "eleven_multilingual_v2", "en")
    )
    assert result.audio == b"AUDIO"
    assert result.words is not None and result.words[0].w == "Hi"
    assert result.note and "forced-alignment" in result.note
    assert calls == [
        "/v1/text-to-speech/v1/with-timestamps",
        "/v1/text-to-speech/v1",
        "/v1/forced-alignment",
    ]


def test_synthesize_retries_on_429(monkeypatch) -> None:
    monkeypatch.setattr("app.services.media.tts.elevenlabs.time.sleep", lambda _s: None)
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] == 1:
            return httpx.Response(429, headers={"retry-after": "0"})
        return httpx.Response(
            200, json={"audio_base64": base64.b64encode(b"x").decode(), "alignment": None}
        )

    result = _provider(handler).synthesize(SynthRequest("Hi", "v1", "eleven_v3", "en"))
    assert attempts["n"] == 2 and result.words is None


def test_list_voices_and_defaults() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "voices": [
                    {
                        "voice_id": "a",
                        "name": "Adam",
                        "labels": {"gender": "male"},
                        "verified_languages": [{"language": "en"}],
                    },
                    {
                        "voice_id": "s",
                        "name": "Sarah",
                        "labels": {"gender": "female"},
                        "verified_languages": [{"language": "ru"}],
                    },
                    {"voice_id": "g", "name": "George", "labels": {}},
                ]
            },
        )

    voices = _provider(handler).list_voices("ru")
    assert voices[0].name == "Sarah"  # verified for the requested language first
    speakers = [
        SpeakerRef("participant_0", "moderator", 0),
        SpeakerRef("participant_1", "debater", 0),
        SpeakerRef("judge", "judge", 0),
    ]
    defaults = pick_default_voices(voices, speakers)
    assert defaults["participant_0"] == "g"  # George preferred for moderators
    assert defaults["participant_1"] == "s"  # Sarah preferred for the first debater
    assert defaults["judge"] == "a"  # only unused voice left
    assert len(set(defaults.values())) == 3


def test_pick_default_voices_without_catalogue() -> None:
    assert pick_default_voices([], [SpeakerRef("x", "debater", 0)]) == {"x": ""}
    assert pick_default_voices(
        [VoiceInfo("only", "Only")], [SpeakerRef("a", "debater", 0), SpeakerRef("b", "debater", 1)]
    ) == {"a": "only", "b": "only"}


def test_list_voices_adds_native_library_voices_on_paid_plans() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/v1/user/subscription":
            return httpx.Response(200, json={"tier": "creator"})
        if request.url.path == "/v1/shared-voices":
            assert request.url.params["language"] == "hy"
            return httpx.Response(
                200,
                json={
                    "voices": [
                        {
                            "voice_id": "an",
                            "name": "Anahit - Bright",
                            "gender": "female",
                            "language": "hy",
                            "description": "A long marketing blurb " * 5,
                            "verified_languages": [{"language": "hy"}, {"language": "hy"}],
                        },
                        {"voice_id": "ar", "name": "Aram", "gender": "male", "language": "hy"},
                        {"voice_id": "pricey", "name": "Gor", "language": "hy", "rate": 2.0},
                    ]
                },
            )
        return httpx.Response(
            200,
            json={"voices": [{"voice_id": "r", "name": "Roger - Casual", "labels": {}}]},
        )

    provider = ElevenLabsProvider(api_key="paid", transport=httpx.MockTransport(handler))
    voices = provider.list_voices("hy")
    assert [v.id for v in voices] == ["an", "ar", "r"]  # native first, surcharged voice dropped
    assert voices[0].languages == ("hy",) and voices[0].description == "female"
    speakers = [
        SpeakerRef("participant_0", "moderator", 0),
        SpeakerRef("participant_1", "debater", 0),
    ]
    defaults = pick_default_voices(voices, speakers, "hy")
    assert defaults == {"participant_0": "an", "participant_1": "ar"}  # natives, mixed genders
    provider.list_voices("hy")
    assert paths.count("/v1/voices") == 1  # cached


def test_list_voices_free_plan_skips_library_voices() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/user/subscription":
            return httpx.Response(200, json={"tier": "free"})
        assert request.url.path == "/v1/voices"
        return httpx.Response(
            200,
            json={
                "voices": [
                    {"voice_id": "r", "name": "Roger - Casual", "labels": {}, "sharing": None},
                    {"voice_id": "n", "name": "Nikolay", "sharing": {"status": "copied"}},
                ]
            },
        )

    provider = ElevenLabsProvider(api_key="free", transport=httpx.MockTransport(handler))
    assert [v.id for v in provider.list_voices("ru")] == ["r"]


def test_pick_default_voices_matches_names_with_descriptions() -> None:
    voices = [VoiceInfo("x", "Xavier - Calm"), VoiceInfo("g", "George - Warm Storyteller")]
    assert pick_default_voices(voices, [SpeakerRef("m", "moderator", 0)]) == {"m": "g"}


def test_estimate_usd() -> None:
    assert estimate_usd("eleven_v3", 12_000) == 1.2
    assert estimate_usd("unknown", 100) is None
