from app.services.prompt_builder import (
    build_debater_messages,
    build_moderator_messages,
    build_verdict_messages,
    intensity_description,
    length_words,
    verdict_words,
)
from app.services.scheduler import build_schedule

CONF = {
    "topic": "Is pineapple acceptable on pizza?",
    "description": "A culinary showdown.",
    "language": "Russian",
    "num_rounds": 2,
    "length_preset": "short",
    "intensity": 8,
    "participants": [
        {"role": "moderator", "display_name": "Host", "persona_custom": "Warm and witty."},
        {"role": "debater", "display_name": "Alice", "persona_custom": "Argue in favour."},
        {"role": "debater", "display_name": "Bob", "persona_custom": "Argue against."},
    ],
}
SCHEDULE = build_schedule(CONF["participants"], CONF["num_rounds"])
HISTORY = [{"speaker_name": "Host", "text": "Welcome everyone!", "turn_type": "moderator_intro"}]


def _roles(messages):
    return [m["role"] for m in messages]


def test_debater_opening_prompt():
    turn = SCHEDULE[1]
    messages = build_debater_messages(CONF, CONF["participants"][1], turn, HISTORY)
    assert _roles(messages) == ["system", "user"]
    system, user = messages[0]["content"], messages[1]["content"]
    assert "Alice" in system and "Argue in favour." in system
    assert "Russian" in system
    assert "about 100 words" in system
    assert "OPENING" in user
    assert CONF["topic"] in user and "A culinary showdown." in user
    assert "Host: Welcome everyone!" in user
    assert "Round 1 of 2" in user


def test_debater_closing_prompt_mentions_closing():
    turn = SCHEDULE[-1]
    assert turn.turn_type == "closing"
    user = build_debater_messages(CONF, CONF["participants"][2], turn, HISTORY)[1]["content"]
    assert "CLOSING" in user and "Bob" in user


def test_moderator_intro_invites_first_debater():
    turn = SCHEDULE[0]
    messages = build_moderator_messages(CONF, CONF["participants"][0], turn, [])
    system, user = messages[0]["content"], messages[1]["content"]
    assert "never argue for a side" in system
    assert "Warm and witty." in system
    assert "invite Alice to begin" in user
    assert "No statements yet" in user


def test_moderator_transition_summarizes_previous_round():
    turn = SCHEDULE[3]
    assert turn.turn_type == "moderator_transition"
    user = build_moderator_messages(CONF, CONF["participants"][0], turn, HISTORY)[1]["content"]
    assert "Round 1 has just ended" in user
    assert "open round 2 of 2" in user


def test_verdict_prompt_structure():
    messages = build_verdict_messages(CONF, HISTORY)
    system, user = messages[0]["content"], messages[1]["content"]
    assert "**Winner: <name>**" in system and "one short paragraph per debater" in system
    assert "Key Arguments" not in system  # long multi-section verdicts outweighed the debate
    assert f"about {verdict_words(CONF)} words" in system and "hard limit" in system
    assert "Russian" in system
    assert "Full transcript" in user and "Welcome everyone!" in user


def test_verdict_length_follows_the_turn_length():
    two = [{"role": "moderator"}, {"role": "debater"}, {"role": "debater"}]
    assert verdict_words({"length_preset": "very_short", "participants": two}) == 70
    assert verdict_words({"length_preset": "short", "participants": two}) == 110
    assert verdict_words({"length_preset": "long", "participants": two}) == 260
    assert verdict_words({"length_preset": "nope", "participants": two}) == 170
    four = [*two, {"role": "debater"}, {"role": "debater"}]
    assert verdict_words({"length_preset": "short", "participants": four}) == 160
    spoken = build_verdict_messages(
        {"length_preset": "very_short", "participants": two, "output_style": "spoken"}, []
    )[0]["content"]
    assert "FIRST" in spoken and "about 70 words" in spoken


def test_length_and_intensity_helpers():
    assert length_words("very_short") == 50
    assert length_words("unknown") == 250
    assert "polite" in intensity_description(1)
    assert "persuasive" in intensity_description(5)
    assert "passionate" in intensity_description(10)


def test_visual_requests_and_claims_only_with_visual_scenes():
    turn = SCHEDULE[4]
    plain = build_debater_messages(CONF, CONF["participants"][1], turn, HISTORY, "[1] Bob: stat")
    assert "[visual:" not in plain[0]["content"] and "[1] Bob" not in plain[1]["content"]

    conf = {**CONF, "media_plan": {"visuals": True}}
    claims = "[1] Bob: stat: 90% — fall in prices — fact-check: disputed (It was 40%.)"
    system, user = (
        m["content"]
        for m in build_debater_messages(conf, conf["participants"][1], turn, HISTORY, claims)
    )
    assert "[visual: what to show" in system
    assert claims in user and "[dispute <number>: <short reason>]" in user
    no_claims = build_debater_messages(conf, conf["participants"][1], turn, HISTORY)
    assert "[dispute" not in no_claims[1]["content"]


def test_verdict_gets_the_fact_check_evidence():
    evidence = "Web fact-check of the figures:\n- Alice showed stat: 90% — disputed: It was 40%."
    user = build_verdict_messages(CONF, HISTORY, evidence)[1]["content"]
    assert evidence in user and "Weigh accuracy" in user
    assert "Weigh accuracy" not in build_verdict_messages(CONF, HISTORY)[1]["content"]
