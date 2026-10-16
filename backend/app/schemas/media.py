"""Request/response schemas for the media (audio + video) endpoints."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

MediaStatus = Literal["none", "queued", "running", "ready", "error"]
TTSProviderName = Literal["elevenlabs", "edge"]


class MediaOptions(BaseModel):
    provider: TTSProviderName = "edge"
    model_id: str = Field(default="eleven_v3", max_length=100)
    voices: dict[str, str] = Field(default_factory=dict)  # speaker_id -> provider voice id
    visuals: bool = True  # design charts / drawn scenes synced with the speech


class GenerateMediaRequest(MediaOptions):
    force: bool = False  # ignore cached turn audio
    # Optional BYO ElevenLabs key. Kept in Redis for the build only, never in Postgres.
    user_tts_key: str | None = Field(default=None, max_length=200)


class MediaProgress(BaseModel):
    step: str = ""
    current: int = 0
    total: int = 0
    message: str = ""
    error: str | None = None


class MediaUrls(BaseModel):
    timeline: str
    full_mp3: str
    full_wav: str
    base: str  # folder URL, used by the video renderer to load segment audio


class MediaStats(BaseModel):
    chars: int = 0
    tts_ms: int = 0
    estimated_usd: float | None = None
    total_ms: int = 0
    cached_turns: int = 0


class DebateMediaOut(BaseModel):
    debate_id: str
    media_status: MediaStatus
    progress: MediaProgress = Field(default_factory=MediaProgress)
    options: MediaOptions | None = None
    urls: MediaUrls | None = None
    stats: MediaStats | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class MediaAccepted(BaseModel):
    debate_id: str
    media_status: MediaStatus
    message: str


class VoiceOut(BaseModel):
    id: str
    name: str
    description: str | None = None
    preview_url: str | None = None
    gender: str | None = None
    languages: list[str] = Field(default_factory=list)


class VoicesResponse(BaseModel):
    provider: TTSProviderName
    language: str = "en"  # ISO code of the debate language (voices[].languages use it)
    voices: list[VoiceOut]
    defaults: dict[str, str]  # speaker_id -> voice id


class MediaCapabilities(BaseModel):
    elevenlabs: bool  # system key configured
    edge: bool
    ffmpeg: bool
    default_provider: TTSProviderName
    default_model_id: str
    elevenlabs_models: list[str]
    # Why premium voices are unavailable (key missing or rejected), for the UI.
    elevenlabs_error: str | None = None
