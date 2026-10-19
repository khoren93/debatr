"""What a show format is: its seats, limits and how it runs (turn order, prompts, verdict).

The orchestrator, the estimate and the recovery never branch on a format id: they ask the
debate's format (`formats.format_of(conf)`). A format is data plus a handful of methods over the
stored config (`config_json`), so the worker and the API share it without schemas in between.
"""

import re
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from app.services.scheduler import ScheduledTurn

# for / against the motion, or a position of one's own (a third or fourth debater). Not set
# (None) means the speaker's persona text carries the stance, as before sides existed.
Side = Literal["for", "against", "own"]
SIDES: tuple[Side, ...] = ("for", "against", "own")

Messages = list[dict[str, str]]
_ROUND_ID = re.compile(r"round_(\d+)")


@dataclass(frozen=True)
class Seat:
    """A debater's place in a format, by speaking position."""

    label: str  # "Debater", "Prosecution", "Rapper"
    side: Side | None = None  # fixed by the format; None: the participant picks (Format.sides)


def debaters_of(participants: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [p for p in participants if p.get("role") == "debater"]


class Format(ABC):
    """One show format. Subclasses set the class attributes and the behaviour below."""

    id: str
    name: str
    show: str = "debate"  # what the show is called in a sentence ("Alice wins the battle")
    tagline: str  # one line for the format's card
    host_label: str = "Host"
    # Debater seats in speaking order; the last one repeats up to `max_debaters`.
    seats: tuple[Seat, ...] = (Seat("Debater"),)
    min_debaters: int = 1
    max_debaters: int = 8
    host_required: bool = False
    min_rounds: int = 1
    max_rounds: int = 10
    sides: bool = False  # debaters pick their own side (seats without a fixed one)
    visuals: bool = True  # charts and sketches may accompany the speeches
    # "elevenlabs": the show is voiced with premium voices only (no Edge); audio stays optional.
    voices: Literal["any", "elevenlabs"] = "any"
    # "speech": every turn voiced by TTS; "music": one generated track carries the debaters'
    # turns (media/music.py), the host and the judge talk over it.
    soundtrack: Literal["speech", "music"] = "speech"
    # The texts are written for one style whatever the config says (None: the config's).
    output_style: Literal["markdown", "spoken"] | None = None
    # The judge scores every round; the verdict structuring keeps the scores (verdict_json.rounds).
    verdict_scores: bool = False
    # Added to the gallery check's rules (what is fine in this format).
    moderation_note: str = ""

    # --- seats ----------------------------------------------------------------------------------

    def seat(self, debater_index: int) -> Seat:
        return self.seats[min(debater_index, len(self.seats) - 1)]

    def side_of(self, participants: Sequence[Mapping[str, Any]], index: int) -> Side | None:
        """The side of the participant at `index` (None for the host and unset sides)."""
        speaker = participants[index]
        if speaker.get("role") != "debater":
            return None
        seat = self.seat(sum(1 for p in participants[:index] if p.get("role") == "debater"))
        if seat.side is not None:
            return seat.side
        side = speaker.get("side")
        return side if self.sides and side in SIDES else None

    def problems(self, conf: Mapping[str, Any]) -> list[str]:
        """Why a configuration does not fit this format (empty when it does)."""
        participants: Sequence[Mapping[str, Any]] = conf.get("participants") or []
        num_rounds = int(conf.get("num_rounds") or 1)
        out: list[str] = []
        debaters = len(debaters_of(participants))
        if debaters < self.min_debaters or debaters > self.max_debaters:
            span = (
                str(self.min_debaters)
                if self.min_debaters == self.max_debaters
                else f"{self.min_debaters} to {self.max_debaters}"
            )
            out.append(f"{self.name} takes {span} debaters, not {debaters}")
        if self.host_required and not any(p.get("role") == "moderator" for p in participants):
            out.append(f"{self.name} needs a {self.host_label.lower()}")
        if not self.min_rounds <= num_rounds <= self.max_rounds:
            out.append(f"{self.name} runs {self.min_rounds} to {self.max_rounds} rounds")
        if not self.sides and any(p.get("side") for p in participants):
            out.append(f"{self.name} sets the sides itself")
        plan: Mapping[str, Any] = conf.get("media_plan") or {}
        audio = "audio" in (plan.get("outputs") or [])
        if self.voices == "elevenlabs" and audio and plan.get("provider") != "elevenlabs":
            out.append(f"{self.name} is voiced with premium voices only")
        return out

    # --- running ---------------------------------------------------------------------------------

    @abstractmethod
    def schedule(self, conf: Mapping[str, Any]) -> list[ScheduledTurn]:
        """Every turn before the verdict, in order (the single source of turn order)."""

    @abstractmethod
    def host_messages(
        self,
        conf: Mapping[str, Any],
        speaker: Mapping[str, Any],
        turn: ScheduledTurn,
        history: list[dict[str, Any]],
    ) -> Messages: ...

    @abstractmethod
    def debater_messages(
        self,
        conf: Mapping[str, Any],
        speaker: Mapping[str, Any],
        turn: ScheduledTurn,
        history: list[dict[str, Any]],
        visual_claims: str = "",
    ) -> Messages: ...

    @abstractmethod
    def verdict_messages(
        self, conf: Mapping[str, Any], history: list[dict[str, Any]], evidence: str = ""
    ) -> Messages: ...

    @abstractmethod
    def verdict_words(self, conf: Mapping[str, Any]) -> int:
        """Word budget of the verdict (the estimate prices it too)."""

    def track_ms(self, conf: Mapping[str, Any], words_per_minute: int) -> int:
        """Length of the generated track of a `soundtrack="music"` format (the estimate)."""
        return 0

    def finish_text(self, conf: Mapping[str, Any], turn: ScheduledTurn, text: str) -> str:
        """A debater's answer as it is saved (a format may tidy it up, e.g. verse lines)."""
        return text

    def round_label(self, round_id: str, turn_type: str) -> str:
        """What the transcript, the live card and the video call this part of the show."""
        if round_id == "verdict":
            return "Verdict"
        match = _ROUND_ID.fullmatch(round_id)
        return f"Round {match.group(1)}" if match else round_id

    def catalogue(self) -> dict[str, Any]:
        """The format as the API lists it (`GET /api/formats`)."""
        return {
            "id": self.id,
            "name": self.name,
            "show": self.show,
            "tagline": self.tagline,
            "host_label": self.host_label,
            "host_required": self.host_required,
            "seats": [{"label": s.label, "side": s.side} for s in self.seats],
            "min_debaters": self.min_debaters,
            "max_debaters": self.max_debaters,
            "min_rounds": self.min_rounds,
            "max_rounds": self.max_rounds,
            "sides": self.sides,
            "visuals": self.visuals,
            "voices": self.voices,
            "soundtrack": self.soundtrack,
            "verdict_scores": self.verdict_scores,
        }
