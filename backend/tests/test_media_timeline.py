from app.services.media.timeline import build_speakers


def test_build_speakers_keep_full_model_ids_for_logos() -> None:
    participants = [
        {"role": "moderator", "model_id": "google/gemini-2.5-flash", "display_name": "The Host"},
        {"role": "debater", "model_id": "anthropic/claude-sonnet-4", "display_name": "Claude"},
        {"role": "debater", "model_id": "openai/gpt-4o:free", "display_name": "GPT"},
    ]
    speakers = build_speakers(participants, "en", "deepseek/deepseek-chat")
    by_id = {s.id: s for s in speakers}
    assert by_id["participant_1"].model == "claude-sonnet-4"
    assert by_id["participant_1"].model_id == "anthropic/claude-sonnet-4"
    assert by_id["participant_2"].model == "gpt-4o"
    assert by_id["participant_2"].model_id == "openai/gpt-4o:free"
    assert by_id["judge"].model_id == "deepseek/deepseek-chat"


def test_a_refreshed_timeline_gets_a_new_address() -> None:
    from types import SimpleNamespace
    from typing import Any

    from app.api.routes_media import media_out

    state: dict[str, Any] = {"finished_at": "2026-10-21T09:48:16.123456+00:00"}
    debate: Any = SimpleNamespace(
        id="5f0c3a1e-2b4d-4c6e-8f10-123456789abc", media_status="ready", media_json=state
    )
    first = media_out(debate).urls
    assert first is not None and first.timeline.endswith("v=2026-10-21T094816.12")
    state["revision"] = 2
    second = media_out(debate).urls
    assert second is not None and second.timeline.endswith("v=2026-10-21T094816.12r2")


def test_crowd_sounds_follow_the_format_unless_chosen() -> None:
    from app.schemas.media import MediaOptions
    from app.services.formats import format_of

    assert format_of({"format": "rap_battle"}).crowd_sounds is True
    assert format_of({}).crowd_sounds is False
    assert MediaOptions().sfx is None
    assert MediaOptions.model_validate({"sfx": False}).sfx is False
