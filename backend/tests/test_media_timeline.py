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
