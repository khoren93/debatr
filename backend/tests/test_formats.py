"""Show formats (services/formats): the classic debate runs exactly as before formats existed
(snapshot), sides reach the prompts only when set, and the interface fits a format with fixed
seats and alternating turns (a battle-like test format). Pure."""

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from app.api import routes_formats, routes_gallery, serializers
from app.models.models import Debate, DebateParticipant, Turn
from app.schemas.schemas import DebateConfig
from app.services.formats import FORMATS, Format, Seat, format_of, get_format
from app.services.formats.base import Messages
from app.services.media import music
from app.services.scheduler import ScheduledTurn

SNAPSHOT = Path(__file__).parent / "fixtures" / "debate_prompts_v1.json"
HISTORY = [
    {"speaker_name": "The Host", "text": "Welcome to the debate.", "turn_type": "moderator_intro"},
    {"speaker_name": "Claude", "text": "Remote work wins on focus.", "turn_type": "opening"},
    {"speaker_name": "GPT", "text": "Offices win on mentoring.", "turn_type": "opening"},
]


def _sql(statement: Any) -> str:
    return str(
        statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )


# --- the classic debate, byte for byte --------------------------------------------------------


@pytest.mark.parametrize("name", list(json.loads(SNAPSHOT.read_text())))
def test_debates_without_sides_run_as_before_formats(name: str) -> None:
    """tests/fixtures/debate_prompts_v1.json was recorded from the code before the format
    engine: schedules, prompts and verdicts of configs without a format or sides."""
    case = json.loads(SNAPSHOT.read_text())[name]
    conf = case["config"]
    fmt = format_of(conf)
    assert fmt.id == "debate"
    schedule = fmt.schedule(conf)
    assert len(schedule) == len(case["turns"])
    for turn, want in zip(schedule, case["turns"], strict=True):
        got = (turn.seq_index, turn.round_number, turn.turn_type, turn.speaker_index, turn.round_id)
        assert got == (want["seq"], want["round"], want["type"], want["speaker"], want["round_id"])
        speaker = conf["participants"][turn.speaker_index]
        history = HISTORY[: turn.seq_index % 4]
        if turn.is_moderator:
            messages = fmt.host_messages(conf, speaker, turn, history)
        else:
            messages = fmt.debater_messages(
                conf, speaker, turn, history, visual_claims="1. bars by GPT"
            )
        assert messages == want["messages"], (name, turn.seq_index)
    assert fmt.verdict_messages(conf, HISTORY, "") == case["verdict"]
    assert (
        fmt.verdict_messages(conf, HISTORY, "Fact-check: 1 claim refuted.")
        == (case["verdict_with_evidence"])
    )
    assert fmt.verdict_words(conf) == case["verdict_words"]


def test_unknown_or_missing_formats_run_as_debates() -> None:
    assert format_of({}).id == "debate"
    assert format_of({"format": "opera"}).id == "debate"
    assert get_format("opera") is None
    assert format_of({"format": "debate"}) is FORMATS["debate"]


# --- sides --------------------------------------------------------------------------------------


def _sided_conf() -> dict[str, Any]:
    return {
        "topic": "Is remote work better than the office?",
        "language": "English",
        "num_rounds": 2,
        "output_style": "spoken",
        "participants": [
            {"role": "moderator", "model_id": "m/h", "display_name": "The Host", "side": "for"},
            {"role": "debater", "model_id": "m/a", "display_name": "Claude", "side": "for"},
            {"role": "debater", "model_id": "m/b", "display_name": "GPT", "side": "against"},
            {"role": "debater", "model_id": "m/c", "display_name": "Gemini", "side": "own"},
        ],
    }


def test_sides_reach_the_prompts() -> None:
    conf = _sided_conf()
    fmt = format_of(conf)
    schedule = fmt.schedule(conf)
    by_speaker = {t.speaker_index: t for t in schedule if t.round_number == 1}
    lines = {
        1: "Your side: you argue FOR the topic (if it asks 'A or B?', you back A).",
        2: "Your side: you argue AGAINST the topic (if it asks 'A or B?', you back B).",
        3: "Your side: you take a position of your own, not simply for or against the topic.",
    }
    for index, line in lines.items():
        system, user = fmt.debater_messages(
            conf, conf["participants"][index], by_speaker[index], HISTORY
        )
        assert line in system["content"]
        assert "- Claude (debater, for)" in user["content"]
        assert "- GPT (debater, against)" in user["content"]
        assert "- Gemini (debater, own position)" in user["content"]
        # The host has no side, whatever its config says.
        assert "- The Host (moderator)" in user["content"]
    intro = fmt.host_messages(conf, conf["participants"][0], schedule[0], [])
    assert "introduce each debater by name and side" in intro[1]["content"]
    verdict = fmt.verdict_messages(conf, HISTORY)
    assert "Sides: Claude (for), GPT (against), Gemini (own position)" in verdict[1]["content"]
    assert fmt.side_of(conf["participants"], 0) is None
    assert [fmt.side_of(conf["participants"], i) for i in (1, 2, 3)] == ["for", "against", "own"]


def test_unset_sides_add_nothing() -> None:
    conf = _sided_conf()
    for p in conf["participants"]:
        p.pop("side")
    fmt = format_of(conf)
    turn = fmt.schedule(conf)[1]
    system, user = fmt.debater_messages(conf, conf["participants"][1], turn, HISTORY)
    assert "Your side" not in system["content"] and "(debater)" in user["content"]
    assert "Sides:" not in fmt.verdict_messages(conf, HISTORY)[1]["content"]


def test_the_config_names_a_known_format_and_valid_sides() -> None:
    base = {
        "topic": "Tabs or spaces?",
        "participants": [{"role": "debater", "model_id": "a/b", "display_name": "A"}],
    }
    config = DebateConfig.model_validate(base)
    assert config.format == "debate" and config.persisted()["format"] == "debate"
    stored_before_formats = DebateConfig.stored(base)
    assert stored_before_formats.format == "debate"
    with pytest.raises(ValidationError):
        DebateConfig.model_validate({**base, "format": "opera"})
    with pytest.raises(ValidationError):
        DebateConfig.model_validate(
            {**base, "participants": [{**base["participants"][0], "side": "maybe"}]}
        )
    sided = DebateConfig.model_validate(
        {**base, "participants": [{**base["participants"][0], "side": "against"}]}
    )
    assert sided.persisted()["participants"][0]["side"] == "against"


# --- the interface fits a format with fixed seats -------------------------------------------------


class Battle(Format):
    """Test only: two fixed seats, a required host, the first speaker alternating per round."""

    id = "battle"
    name = "Battle"
    tagline = "Two rappers, three rounds."
    host_label = "MC"
    seats = (Seat("Rapper One", side="for"), Seat("Rapper Two", side="against"))
    min_debaters = 2
    max_debaters = 2
    host_required = True
    max_rounds = 3

    def schedule(self, conf: Mapping[str, Any]) -> list[ScheduledTurn]:
        people = list(conf["participants"])
        host = next(i for i, p in enumerate(people) if p["role"] == "moderator")
        one, two = [i for i, p in enumerate(people) if p["role"] == "debater"]
        out: list[ScheduledTurn] = []
        for r in range(1, int(conf["num_rounds"]) + 1):
            out.append(ScheduledTurn(len(out), r, "moderator_intro", host))
            for speaker in (one, two) if r % 2 else (two, one):
                out.append(ScheduledTurn(len(out), r, "verse", speaker))
        return out

    def host_messages(self, conf: Any, speaker: Any, turn: Any, history: Any) -> Messages:
        return [{"role": "user", "content": "hype the crowd"}]

    def debater_messages(
        self, conf: Any, speaker: Any, turn: Any, history: Any, visual_claims: str = ""
    ) -> Messages:
        return [{"role": "user", "content": f"verse as {self.side_of(conf['participants'], 1)}"}]

    def verdict_messages(self, conf: Any, history: Any, evidence: str = "") -> Messages:
        return [{"role": "user", "content": "score each round"}]

    def verdict_words(self, conf: Any) -> int:
        return 60

    def round_label(self, round_id: str, turn_type: str) -> str:
        return (
            "Final scores"
            if round_id == "verdict"
            else super().round_label(round_id, turn_type).replace("Round", "Battle round")
        )


def _people(debaters: int, host: bool = True, side: str | None = None) -> list[dict[str, Any]]:
    people = [{"role": "moderator", "display_name": "MC"}] if host else []
    people += [{"role": "debater", "display_name": f"R{i}", "side": side} for i in range(debaters)]
    return people


def test_a_fixed_seat_format() -> None:
    battle = Battle()
    people = _people(2)
    assert battle.problems({"participants": people, "num_rounds": 3}) == []
    assert battle.problems({"participants": _people(3), "num_rounds": 1}) == [
        "Battle takes 2 debaters, not 3"
    ]
    assert battle.problems({"participants": _people(2, host=False), "num_rounds": 1}) == [
        "Battle needs a mc"
    ]
    assert battle.problems({"participants": people, "num_rounds": 4}) == [
        "Battle runs 1 to 3 rounds"
    ]
    assert battle.problems({"participants": _people(2, side="for"), "num_rounds": 1}) == [
        "Battle sets the sides itself"
    ]
    # Seats fix the sides, by speaking position.
    assert [battle.side_of(people, i) for i in range(3)] == [None, "for", "against"]
    assert battle.seat(5).label == "Rapper Two"
    schedule = battle.schedule({"participants": people, "num_rounds": 3})
    assert [t.speaker_index for t in schedule] == [0, 1, 2, 0, 2, 1, 0, 1, 2]
    assert battle.round_label("round_2", "verse") == "Battle round 2"
    assert battle.round_label("verdict", "verdict") == "Final scores"
    card = battle.catalogue()
    assert card["seats"] == [
        {"label": "Rapper One", "side": "for"},
        {"label": "Rapper Two", "side": "against"},
    ]
    assert (card["host_label"], card["sides"], card["max_debaters"]) == ("MC", False, 2)


def test_the_debate_format_limits_stay_as_they_were() -> None:
    debate = FORMATS["debate"]
    assert debate.problems({"participants": _people(1, host=False), "num_rounds": 1}) == []
    assert debate.problems({"participants": _people(7), "num_rounds": 10}) == []
    assert debate.problems({"participants": _people(2, side="own"), "num_rounds": 3}) == []
    assert debate.problems({"participants": _people(0), "num_rounds": 1}) == [
        "Debate takes 1 to 8 debaters, not 0"
    ]


# --- API --------------------------------------------------------------------------------------


async def test_the_format_catalogue() -> None:
    formats = await routes_formats.list_formats()
    assert [f.id for f in formats] == ["debate", "rap_battle"]
    debate = formats[0]
    assert debate.sides and debate.visuals and debate.host_label == "Host"
    assert debate.seats[0].label == "Debater" and debate.seats[0].side is None
    assert debate.voices == "any" and debate.soundtrack == "speech" and debate.flows == []
    battle = formats[1]
    assert battle.show == "battle" and battle.host_label == "MC" and not battle.visuals
    assert battle.voices == "elevenlabs" and battle.soundtrack == "music"
    assert battle.verdict_scores and [s.side for s in battle.seats] == ["for", "against"]
    # The wizard and the CLI offer these in place of the rappers' voices.
    assert {f.id for f in battle.flows} == set(music.FLOWS)
    assert battle.default_flows == list(music.DEFAULT_FLOWS)
    assert {f.voice for f in battle.flows if f.id in battle.default_flows} == {"male", "female"}


def test_formats_filter_the_gallery_and_rank_apart() -> None:
    sql = _sql(routes_gallery.format_sql() == "debate")
    assert (
        "coalesce(CAST((debates.config_json ->> 'format') AS VARCHAR), 'debate') = 'debate'" in sql
    )


def test_turns_and_participants_carry_labels_and_sides() -> None:
    debate = FORMATS["debate"]
    turn = Turn(
        seq_index=3,
        round_id="round_2",
        turn_type="rebuttal",
        speaker_id="participant_1",
        speaker_name="Claude",
        text="x",
        model_used="m/a",
        usage_json={},
        visuals_json={},
    )
    assert serializers.turn_out(turn, debate).round_label == "Round 2"
    verdict = Turn(**{**{c: getattr(turn, c) for c in ("text", "model_used")}, "seq_index": 9})
    verdict.round_id, verdict.turn_type = "verdict", "verdict"
    verdict.speaker_id, verdict.speaker_name, verdict.usage_json = "judge", "Verdict", {}
    verdict.visuals_json = {}
    assert serializers.turn_out(verdict, debate).round_label == "Verdict"
    row = Debate(
        config_json=_sided_conf(),
        participants=[
            DebateParticipant(
                role=p["role"], model_id=p["model_id"], persona_name=p["display_name"]
            )
            for p in _sided_conf()["participants"]
        ],
    )
    sides = [p.side for p in serializers.participants_out(row)]
    assert sides == [None, "for", "against", "own"]
