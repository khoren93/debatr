"""Rap battle format (services/formats/rap_battle): seats and limits, the alternating schedule,
verse prompts and tidy lyrics, the judge's round scores. Pure."""

from typing import Any

import pytest
from pydantic import ValidationError

from app.schemas.schemas import DebateConfig
from app.services.formats import FORMATS, format_of
from app.services.formats.rap_battle import VERSE, tidy_verse, verse_lines
from app.services.moderation import build_moderation_messages
from app.services.verdict import (
    build_verdict_parse_messages,
    fallback_round_scores,
    parse_round_scores,
)

RAP = FORMATS["rap_battle"]
DEBATERS = [{"id": "participant_1", "name": "Claude"}, {"id": "participant_2", "name": "GPT"}]


def _conf(**extra: Any) -> dict[str, Any]:
    return {
        "format": "rap_battle",
        "topic": "Is remote work better than the office?",
        "language": "English",
        "num_rounds": 3,
        "length_preset": "short",
        "participants": [
            {"role": "moderator", "model_id": "m/mc", "display_name": "The Host"},
            {"role": "debater", "model_id": "m/a", "display_name": "Claude"},
            {"role": "debater", "model_id": "m/b", "display_name": "GPT"},
        ],
        **extra,
    }


# --- seats, limits, what the format decides -------------------------------------------------------


def test_rappers_take_turns_and_swap_who_opens() -> None:
    conf = _conf()
    assert format_of(conf) is RAP
    schedule = RAP.schedule(conf)
    assert [(t.turn_type, t.speaker_index, t.round_number) for t in schedule] == [
        ("moderator_intro", 0, 1),
        (VERSE, 1, 1),
        (VERSE, 2, 1),
        (VERSE, 2, 2),
        (VERSE, 1, 2),
        (VERSE, 1, 3),
        (VERSE, 2, 3),
    ]
    assert [t.seq_index for t in schedule] == list(range(7))
    assert RAP.side_of(conf["participants"], 1) == "for"
    assert RAP.side_of(conf["participants"], 2) == "against"
    assert RAP.round_label("round_2", VERSE) == "Round 2"


def _config(**changes: Any) -> DebateConfig:
    return DebateConfig.model_validate({**_conf(), **changes})


def test_the_config_must_fit_a_battle() -> None:
    people = _conf()["participants"]
    with pytest.raises(ValidationError, match="Rap battle takes 2 debaters, not 3"):
        _config(participants=[*people, {**people[2], "display_name": "Gemini"}])
    with pytest.raises(ValidationError, match="Rap battle needs a mc"):
        _config(participants=people[1:])
    with pytest.raises(ValidationError, match="runs 1 to 3 rounds"):
        _config(num_rounds=4)
    with pytest.raises(ValidationError, match="sets the sides itself"):
        _config(participants=[people[0], {**people[1], "side": "against"}, people[2]])
    edge_audio = {"provider": "edge", "outputs": ["audio", "video"]}
    with pytest.raises(ValidationError, match="voiced with premium voices only"):
        _config(media_plan=edge_audio)
    # Lyrics without audio are a battle too (the CLI in a terminal, a free check).
    assert _config(media_plan={"provider": "edge", "outputs": []}).format == "rap_battle"


def test_the_format_decides_style_and_scenes() -> None:
    config = _config(
        output_style="markdown",
        fact_check=True,
        media_plan={"provider": "elevenlabs", "visuals": True, "images": "ai"},
    )
    assert config.output_style == "spoken"
    assert config.fact_check is False
    assert config.media_plan is not None
    assert (config.media_plan.visuals, config.media_plan.images) == (False, "off")
    # A debate keeps what it was given.
    debate = DebateConfig.model_validate(
        {**_conf(format="debate"), "output_style": "markdown", "fact_check": True}
    )
    assert debate.output_style == "markdown" and debate.fact_check is True


def test_the_catalogue_tells_clients_the_rules() -> None:
    card = RAP.catalogue()
    assert (card["voices"], card["verdict_scores"], card["visuals"], card["sides"]) == (
        "elevenlabs",
        True,
        False,
        False,
    )
    assert card["seats"] == [
        {"label": "Rapper One", "side": "for"},
        {"label": "Rapper Two", "side": "against"},
    ]
    assert (card["min_debaters"], card["max_debaters"], card["max_rounds"]) == (2, 2, 3)


# --- prompts ------------------------------------------------------------------------------------


def test_verse_prompts() -> None:
    conf = _conf(length_preset="medium", intensity=9)
    schedule = RAP.schedule(conf)
    history = [
        {"speaker_name": "The Host", "text": "Make some noise!", "turn_type": "moderator_intro"},
        {"speaker_name": "Claude", "text": "Line one\nLine two", "turn_type": VERSE},
    ]
    system, user = RAP.debater_messages(conf, conf["participants"][2], schedule[2], history)
    assert (
        "Write EXACTLY 12 lines" in system["content"]
        and "Output only the 12 lines" in system["content"]
    )
    assert "You are GPT, a battle rapper in a rap battle against Claude." in system["content"]
    assert (
        "Your side: you rap AGAINST the topic (if it asks 'A or B?', you back B)."
        in system["content"]
    )
    assert "never real people" in system["content"] and "Markdown" in system["content"]
    assert "very passionate" in system["content"]  # intensity 9
    # The battle so far shows the verses only (not the MC's hype).
    assert (
        "Claude:\nLine one\nLine two" in user["content"]
        and "Make some noise" not in user["content"]
    )
    assert user["content"].endswith("Round 1 of 3. Your 12 lines, GPT:")
    assert verse_lines({"length_preset": "very_short"}) == 4 and verse_lines({}) == 8


def test_mc_and_judge_prompts() -> None:
    conf = _conf(num_rounds=2)
    schedule = RAP.schedule(conf)
    system, user = RAP.host_messages(conf, conf["participants"][0], schedule[0], [])
    assert "MC of a rap battle" in system["content"] and "never take a side" in system["content"]
    assert "Claude raps FOR the topic, GPT raps AGAINST it" in user["content"]
    assert "2 rounds" in user["content"] and "hand the mic to Claude" in user["content"]
    verdict_system, verdict_user = RAP.verdict_messages(conf, [])
    assert "'Round 1: Claude 8, GPT 7'" in verdict_system["content"]
    assert "about 100 words" in verdict_system["content"]  # 50 + 25 per round
    assert "2 round(s)" in verdict_user["content"]


# --- lyrics as they are saved ----------------------------------------------------------------------


def test_verses_are_tidied_into_lines() -> None:
    raw = (
        "**Verse 1:**\n"
        '1. "I read the whole context, every page, every line,"\n'
        "- [confident] You skim through the prompt, then you swear that it's fine.\n"
        "\n"
        "Round one, I'm coming for your crown,\n"
        "(Round 2 - GPT)\n"
        "> Your bars are so weak they fall straight down.\n"
        "Fifth line that should be cut\n"
    )
    assert tidy_verse(raw, 4).splitlines() == [
        "I read the whole context, every page, every line,",
        "You skim through the prompt, then you swear that it's fine.",
        "Round one, I'm coming for your crown,",
        "Your bars are so weak they fall straight down.",
    ]
    conf = _conf(length_preset="very_short")
    verse = RAP.schedule(conf)[1]
    mc = RAP.schedule(conf)[0]
    assert RAP.finish_text(conf, verse, raw) == tidy_verse(raw, 4)
    assert RAP.finish_text(conf, mc, raw) == raw  # the MC's words are left alone


# --- the judge's scores ------------------------------------------------------------------------


def test_round_scores_from_the_structuring_answer() -> None:
    raw = [
        {"round": 1, "scores": {"Claude": 8, "GPT": "7"}},
        {"round": "2", "scores": {"claude": 6.6, "gpt": 9}},
        {"round": 3, "scores": {"Claude": 8}},  # a debater missing: dropped
        {"round": 9, "scores": {"Claude": 8, "GPT": 7}},  # no such round
        {"round": 1, "scores": {"Claude": 11, "GPT": 7}},  # out of range
        "nonsense",
    ]
    assert parse_round_scores(raw, DEBATERS, 3) == [
        {"round": 1, "scores": {"participant_1": 8, "participant_2": 7}},
        {"round": 2, "scores": {"participant_1": 7, "participant_2": 9}},
    ]
    assert parse_round_scores(None, DEBATERS, 3) == []


def test_round_scores_from_the_judges_words() -> None:
    text = (
        "GPT takes it, 16 to 15! Round 1: Claude 8, GPT 7 - sharper rebuttals. "
        "Round 2: Claude 7, GPT 9, the punchlines landed. Round 3 was close."
    )
    assert fallback_round_scores(text, DEBATERS, 3) == [
        {"round": 1, "scores": {"participant_1": 8, "participant_2": 7}},
        {"round": 2, "scores": {"participant_1": 7, "participant_2": 9}},
    ]


def test_structuring_asks_for_scores_and_the_formats_rules() -> None:
    (_, user) = build_verdict_parse_messages(
        topic="t",
        language="English",
        verdict_text="v",
        debaters=DEBATERS,
        rounds=3,
        extra_rules=RAP.moderation_note,
    )
    assert '"rounds": [{"round": <1 to 3>' in user["content"]
    assert "trash talk and bragging are expected and fine" in user["content"]
    (_, plain) = build_verdict_parse_messages(
        topic="t", language="English", verdict_text="v", debaters=DEBATERS
    )
    assert '"rounds"' not in plain["content"]
    (_, check) = build_moderation_messages(
        topic="t", description=None, extra_rules=RAP.moderation_note
    )
    assert "roasting the opposing rapper" in check["content"]
