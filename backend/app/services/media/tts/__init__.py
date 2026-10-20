"""TTS provider abstraction. Providers are synchronous (worker code); the API calls
them through `run_in_threadpool`."""

from dataclasses import dataclass, field
from typing import Protocol

from app.services.media.alignment import WordTiming

PROVIDER_NAMES: tuple[str, ...] = ("elevenlabs", "edge")


@dataclass(frozen=True)
class SynthRequest:
    text: str  # may contain [audio tags]; the provider decides whether to keep them
    voice_id: str
    model_id: str
    language_code: str
    previous_text: str | None = None
    next_text: str | None = None
    # How expressive the delivery is (ElevenLabs stability, 0-1); None: the provider's default.
    stability: float | None = None


@dataclass
class SynthResult:
    audio: bytes
    ext: str  # mp3 | wav
    words: list[WordTiming] | None  # None -> spread evenly over the audio
    char_cost: int = 0
    note: str | None = None


@dataclass(frozen=True)
class VoiceInfo:
    id: str
    name: str
    description: str | None = None
    preview_url: str | None = None
    gender: str | None = None
    languages: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class SpeakerRef:
    id: str  # participant_{i} | judge
    role: str  # moderator | debater | judge
    index: int  # order among speakers with the same role


class TTSError(Exception):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class TTSProvider(Protocol):
    name: str

    def available(self) -> bool: ...

    # `announcers`: the host and the judge of a show format get announcer voices (ElevenLabs).
    def list_voices(self, language_code: str, *, announcers: bool = False) -> list[VoiceInfo]: ...

    def default_voices(
        self, language_code: str, speakers: list[SpeakerRef], *, announcers: bool = False
    ) -> dict[str, str]: ...

    def synthesize(self, request: SynthRequest) -> SynthResult: ...


def get_provider(name: str, api_key: str | None = None) -> TTSProvider:
    if name == "elevenlabs":
        from app.services.media.tts.elevenlabs import ElevenLabsProvider

        return ElevenLabsProvider(api_key=api_key)
    if name == "edge":
        from app.services.media.tts.edge import EdgeProvider

        return EdgeProvider()
    raise TTSError(f"Unknown TTS provider: {name}")
