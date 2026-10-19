"""The classic debate: a host opens every round, each debater speaks once per round (opening,
rebuttals, closing), the host's model judges at the end. Built on `scheduler` and
`prompt_builder`; a config without sides gets exactly the prompts it got before formats existed
(tests/fixtures/debate_prompts_v1.json)."""

from collections.abc import Mapping
from typing import Any

from app.services import prompt_builder
from app.services.formats.base import Format, Messages, Seat
from app.services.scheduler import ScheduledTurn, build_schedule


class DebateFormat(Format):
    id = "debate"
    name = "Debate"
    tagline = "Opening, rebuttals and closing: the judge names the stronger case."
    host_label = "Host"
    seats = (Seat("Debater"),)
    min_debaters = 1
    max_debaters = 8
    sides = True

    def schedule(self, conf: Mapping[str, Any]) -> list[ScheduledTurn]:
        return build_schedule(
            list(conf.get("participants") or []), int(conf.get("num_rounds") or 1)
        )

    def host_messages(
        self,
        conf: Mapping[str, Any],
        speaker: Mapping[str, Any],
        turn: ScheduledTurn,
        history: list[dict[str, Any]],
    ) -> Messages:
        return prompt_builder.build_moderator_messages(dict(conf), dict(speaker), turn, history)

    def debater_messages(
        self,
        conf: Mapping[str, Any],
        speaker: Mapping[str, Any],
        turn: ScheduledTurn,
        history: list[dict[str, Any]],
        visual_claims: str = "",
    ) -> Messages:
        return prompt_builder.build_debater_messages(
            dict(conf), dict(speaker), turn, history, visual_claims=visual_claims
        )

    def verdict_messages(
        self, conf: Mapping[str, Any], history: list[dict[str, Any]], evidence: str = ""
    ) -> Messages:
        return prompt_builder.build_verdict_messages(dict(conf), history, evidence)

    def verdict_words(self, conf: Mapping[str, Any]) -> int:
        return prompt_builder.verdict_words(dict(conf))
