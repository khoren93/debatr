"""Free fallback voices (Microsoft Edge neural TTS via the `edge-tts` package).

Not the quality we optimise for, but it lets the whole pipeline run without any API key
and it returns word boundaries, so captions stay in sync.
"""

import asyncio
import logging
from typing import Any

from app.services.media.alignment import WordTiming
from app.services.media.script import strip_audio_tags
from app.services.media.tts import SpeakerRef, SynthRequest, SynthResult, TTSError, VoiceInfo

logger = logging.getLogger(__name__)

_DEFAULTS: dict[str, dict[str, list[str]]] = {
    "en": {
        "moderator": ["en-US-GuyNeural", "en-GB-RyanNeural"],
        "debater": [
            "en-US-JennyNeural",
            "en-US-ChristopherNeural",
            "en-US-AriaNeural",
            "en-US-EricNeural",
            "en-GB-SoniaNeural",
            "en-AU-WilliamMultilingualNeural",
        ],
        "judge": ["en-GB-SoniaNeural", "en-US-MichelleNeural"],
    },
    "ru": {
        "moderator": ["ru-RU-DmitryNeural"],
        "debater": ["ru-RU-SvetlanaNeural", "ru-RU-DmitryNeural"],
        "judge": ["ru-RU-SvetlanaNeural"],
    },
}

_voices_cache: list[dict[str, Any]] | None = None


def _all_voices() -> list[dict[str, Any]]:
    global _voices_cache
    if _voices_cache is None:
        import edge_tts

        try:
            _voices_cache = [dict(v) for v in asyncio.run(edge_tts.list_voices())]
        except Exception as e:  # network / DRM token issues
            raise TTSError(f"Edge TTS voice list unavailable: {e}") from e
    return _voices_cache


class EdgeProvider:
    name = "edge"

    def available(self) -> bool:
        return True

    def list_voices(self, language_code: str, *, announcers: bool = False) -> list[VoiceInfo]:
        prefix = language_code.lower()
        out: list[VoiceInfo] = []
        for v in _all_voices():
            locale = str(v.get("Locale") or "")
            if not locale.lower().startswith(prefix):
                continue
            short = str(v.get("ShortName") or "")
            out.append(
                VoiceInfo(
                    id=short,
                    name=short.split("-", 2)[-1].removesuffix("Neural")
                    if short.count("-") >= 2
                    else short,
                    description=f"{v.get('Gender')} · {locale}",
                    gender=str(v.get("Gender") or "") or None,
                    languages=(locale[:2].lower(),),
                )
            )
        return out

    def default_voices(
        self, language_code: str, speakers: list[SpeakerRef], *, announcers: bool = False
    ) -> dict[str, str]:
        voices = self.list_voices(language_code)
        available = {v.id for v in voices}
        prefs = _DEFAULTS.get(language_code.lower(), {})
        out: dict[str, str] = {}
        used: set[str] = set()
        for speaker in speakers:
            wanted = prefs.get(speaker.role, [])
            if speaker.role == "debater" and wanted:
                wanted = (
                    wanted[speaker.index % len(wanted) :] + wanted[: speaker.index % len(wanted)]
                )
            chosen = next((w for w in wanted if w in available and w not in used), None)
            if chosen is None:
                chosen = next((w for w in wanted if w in available), None)
            if chosen is None:
                # Alternate genders so speakers stay distinguishable.
                pool = [v for v in voices if v.id not in used] or voices
                chosen = (
                    pool[(speaker.index * 2 + (speaker.role != "debater")) % len(pool)].id
                    if pool
                    else ""
                )
            used.add(chosen)
            out[speaker.id] = chosen
        return out

    def synthesize(self, request: SynthRequest) -> SynthResult:
        import edge_tts

        text = strip_audio_tags(request.text)

        async def run() -> tuple[bytes, list[WordTiming]]:
            communicate = edge_tts.Communicate(text, request.voice_id, boundary="WordBoundary")
            audio = bytearray()
            words: list[WordTiming] = []
            async for chunk in communicate.stream():
                item: dict[str, Any] = dict(chunk)
                if item.get("type") == "audio" and item.get("data"):
                    audio.extend(bytes(item["data"]))
                elif item.get("type") == "WordBoundary":
                    offset = int(item.get("offset") or 0) // 10_000
                    duration = int(item.get("duration") or 0) // 10_000
                    words.append(WordTiming(str(item.get("text") or ""), offset, offset + duration))
            return bytes(audio), words

        try:
            audio, words = asyncio.run(run())
        except Exception as e:
            raise TTSError(f"Edge TTS failed: {e}") from e
        if not audio:
            raise TTSError("Edge TTS returned no audio")
        return SynthResult(
            audio=audio,
            ext="mp3",
            words=words or None,
            char_cost=len(text),
            note="edge neural voice (free fallback)",
        )
