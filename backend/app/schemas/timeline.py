"""Timeline: the contract between the audio build (worker), the API and the browser-side
video renderer. Serialized to `media/{debate_id}/timeline.json`."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.visuals import TimelineVisual

SpeakerRole = Literal["moderator", "debater", "judge"]
Mascot = Literal["orb", "bolt", "cube"]


class TimelineWord(BaseModel):
    w: str
    s: int  # ms relative to the segment's own audio
    e: int


class TimelineSpeaker(BaseModel):
    id: str  # "participant_{i}" | "judge"
    name: str
    role: SpeakerRole
    model: str  # short name for captions ("gpt-4o-mini")
    color: str
    mascot: Mascot
    avatar_url: str | None = None
    voice_id: str | None = None
    # Full OpenRouter id ("openai/gpt-4o-mini"): the video draws the provider's logo from it.
    model_id: str = ""


class TimelineSegment(BaseModel):
    seq_index: int
    speaker_id: str
    speaker_name: str
    round_id: str
    # The format's name for this part of the show ("Round 2"); older timelines have none.
    round_label: str | None = None
    turn_type: str
    start_ms: int  # absolute on the full track
    end_ms: int
    audio: str  # relative path, e.g. "turns/003.wav"
    text: str  # spoken text without audio tags
    words: list[TimelineWord] = Field(default_factory=list)
    levels: list[float] = Field(default_factory=list)  # RMS envelope 0..1
    levels_hz: int = 20
    note: str | None = None


class TimelineHighlight(BaseModel):
    index: int
    title: str
    hook: str
    start_ms: int
    end_ms: int
    seq_indexes: list[int] = Field(default_factory=list)


class TimelineVerdict(BaseModel):
    seq_index: int
    winner_id: str | None = None
    winner_name: str | None = None


class TimelineStats(BaseModel):
    chars: int = 0
    tts_ms: int = 0
    estimated_usd: float | None = None
    cached_turns: int = 0
    visuals_usd: float | None = None  # director, sketches, picture checks (system key, not billed)
    images_usd: float | None = None  # AI pictures (billed to the owner)
    # A rap battle's generated track: its length, what generating it cost (0: from the cache).
    music_ms: int | None = None
    music_usd: float | None = None
    music_cached: bool | None = None


class Timeline(BaseModel):
    version: Literal[1] = 1
    debate_id: str
    # The show format (services/formats): the video's label ("AI DEBATE", "RAP BATTLE").
    format: str = "debate"
    title: str
    topic: str
    language: str
    language_code: str
    created_at: datetime
    provider: str
    model_id: str
    speakers: list[TimelineSpeaker]
    segments: list[TimelineSegment]
    gap_ms: int
    total_ms: int
    full_audio_wav: str = "full.wav"
    full_audio_mp3: str = "full.mp3"
    verdict: TimelineVerdict | None = None
    highlights: list[TimelineHighlight] = Field(default_factory=list)
    # Charts / drawn schemes synced with the speech (schemas/visuals.py), sorted by start_ms.
    visuals: list[TimelineVisual] = Field(default_factory=list)
    stats: TimelineStats = Field(default_factory=TimelineStats)
