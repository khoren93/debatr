"""The rap battle's soundtrack: one ElevenLabs Music generation for the whole battle.

The beat and the rapped verses come out of one call (`POST /v1/music/detailed`, `music_v2_5`,
a composition plan): an instrumental intro under the MC's voice, a section per verse with its
rapper's flow, a short break before every new round, an instrumental outro under the judge's
verdict. v2 models keep every section's duration, so the sections' windows are where each verse
sits in the track; `with_timestamps` gives every rapped word its time for the captions.

A generation costs money and is not repeated on a failure; the track is cached by the plan's
hash, so a rebuild with the same lyrics and flows reuses it (and charges nothing).
"""

import hashlib
import json
import logging
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from email.parser import BytesParser
from email.policy import default as email_policy
from pathlib import Path
from typing import Any, Literal

import httpx

from app.core.config import settings
from app.schemas.timeline import TimelineWord

logger = logging.getLogger(__name__)

MUSIC_MODEL = "music_v2_5"
# 192 kbps (the v2 models' "auto") is listed from the Creator plan up: ask for 128 explicitly.
OUTPUT_FORMAT = "mp3_44100_128"
PLAN_VERSION = 2  # bump when the plan's wording changes, so cached tracks are not reused
BPM = 92
BAR_MS = round(60_000 * 4 / BPM)  # one rapped line per bar (spike: 2.65 s a line at 92 BPM)
VOICE_LEAD_MS = 600  # the MC and the judge start talking this far into their section
MIN_SECTION_MS = 3_000
MAX_SECTION_MS = 120_000
MAX_TRACK_MS = 600_000
BREAK_BARS = 2
# ElevenAPI price list, 2026-10-19: what a minute of music costs us (the estimate of a booking).
USD_PER_MINUTE = 0.15

BEAT = (
    "battle rap",
    "hard-hitting boom bap hip hop beat",
    f"{BPM} BPM",
    "punchy dusty drums",
    "deep sub bass",
    "vinyl scratches",
    "underground rap battle atmosphere",
    "polished production",
)
NO_SINGING = ("singing", "melodic chorus", "auto-tune", "pop")
INSTRUMENTAL_ONLY = ("vocals", "rap vocals", "spoken words", *NO_SINGING)
# The model tends to keep the voice of the section before: a verse also names the voice it must
# not have (the other one), and says when the mic changes hands. Without it a battle of a male
# and a female rapper came out with round 2's second verse in the first verse's voice.
OTHER_VOICE = {"male": "female", "female": "male"}

Kind = Literal["intro", "verse", "break", "outro"]


@dataclass(frozen=True)
class Flow:
    """How a rapper sounds (the wizard's "flow" in place of a voice)."""

    id: str
    label: str
    hint: str
    voice: Literal["male", "female"]
    styles: tuple[str, ...]


FLOWS: dict[str, Flow] = {
    f.id: f
    for f in (
        Flow(
            "gritty",
            "Gritty baritone",
            "Deep, slow, menacing",
            "male",
            ("male rapper", "deep gritty baritone voice", "slow menacing confident flow"),
        ),
        Flow(
            "sharp",
            "Sharp double-time",
            "Bright, fast, aggressive",
            "female",
            ("female rapper", "sharp bright voice", "fast double-time aggressive flow"),
        ),
        Flow(
            "smooth",
            "Smooth and laid-back",
            "Warm, relaxed, cool",
            "male",
            ("male rapper", "smooth warm voice", "laid-back relaxed cool flow"),
        ),
        Flow(
            "fierce",
            "Fierce and raspy",
            "Raspy, loud, in your face",
            "female",
            ("female rapper", "raspy powerful voice", "loud fierce in-your-face flow"),
        ),
        Flow(
            "hype",
            "High-energy hype",
            "High-pitched, choppy, wild",
            "male",
            ("male rapper", "high-pitched energetic voice", "fast choppy hype flow"),
        ),
        Flow(
            "cold",
            "Cold and precise",
            "Calm, clipped, deadly",
            "female",
            ("female rapper", "cool calm low voice", "precise clipped deadpan flow"),
        ),
    )
}
# Rapper One and Rapper Two by default: a male and a female voice (two male rappers tend to come
# out as one voice).
DEFAULT_FLOWS = ("gritty", "sharp")


def flow_for(flows: Mapping[str, str], speaker_id: str, rapper_index: int) -> Flow:
    chosen = FLOWS.get(str(flows.get(speaker_id) or ""))
    return chosen or FLOWS[DEFAULT_FLOWS[rapper_index % len(DEFAULT_FLOWS)]]


# --- the plan -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Verse:
    seq_index: int
    round_number: int
    lyrics: str  # one line per bar
    flow: Flow


@dataclass(frozen=True)
class Section:
    kind: Kind
    duration_ms: int
    text: str
    styles: tuple[str, ...]
    negative: tuple[str, ...]
    seq_index: int | None = None  # the verse's turn


def _clamp(ms: int) -> int:
    return max(MIN_SECTION_MS, min(MAX_SECTION_MS, ms))


def verse_ms(lyrics: str) -> int:
    """A bar per line and one more to breathe in."""
    lines = max(1, len([line for line in lyrics.splitlines() if line.strip()]))
    return _clamp((lines + 1) * BAR_MS)


def voiced_ms(speech_ms: int) -> int:
    """An instrumental section the MC or the judge talks over: their speech and a bar."""
    return _clamp(VOICE_LEAD_MS + speech_ms + BAR_MS)


def build_plan(
    intro_speech_ms: int, verses: Sequence[Verse], outro_speech_ms: int
) -> list[Section]:
    """Intro (under the MC), the verses in turn order with a break before each new round,
    outro (under the verdict). Raises ValueError when the track would be too long."""
    sections = [
        Section(
            "intro",
            voiced_ms(intro_speech_ms),
            "[Intro]\n{crowd cheering, DJ scratch}",
            (*BEAT, "instrumental intro", "crowd noise"),
            INSTRUMENTAL_ONLY,
        )
    ]
    last_round = verses[0].round_number if verses else 1
    last_voice: str | None = None
    for verse in verses:
        if verse.round_number != last_round:
            sections.append(
                Section(
                    "break",
                    _clamp(BREAK_BARS * BAR_MS),
                    f"[Round {verse.round_number}]\n{{DJ scratch, crowd cheering}}",
                    ("instrumental break", "DJ scratch", "crowd cheering"),
                    INSTRUMENTAL_ONLY,
                )
            )
            last_round = verse.round_number
        voice, other = verse.flow.voice, OTHER_VOICE[verse.flow.voice]
        handover = (f"a new {voice} vocalist takes the mic",) if last_voice == other else ()
        sections.append(
            Section(
                "verse",
                verse_ms(verse.lyrics),
                f"[Verse]\n{verse.lyrics}",
                (
                    *verse.flow.styles,
                    f"solo {voice} vocals",
                    *handover,
                    "rap vocals",
                    "clear diction",
                    "on beat",
                ),
                (*NO_SINGING, f"{other} vocals", f"{other} rapper", f"{other} voice"),
                verse.seq_index,
            )
        )
        last_voice = voice
    sections.append(
        Section(
            "outro",
            voiced_ms(outro_speech_ms),
            "[Outro]\n{crowd goes wild}",
            ("instrumental outro", "the beat rides out", "crowd cheering"),
            INSTRUMENTAL_ONLY,
        )
    )
    total = sum(s.duration_ms for s in sections)
    if total > MAX_TRACK_MS:
        raise ValueError(f"The battle needs {total // 1000} s of music, more than one track holds")
    return sections


def plan_payload(sections: Sequence[Section]) -> dict[str, Any]:
    """The `composition_plan` of the API (v2 chunks)."""
    return {
        "chunks": [
            {
                "text": s.text,
                "duration_ms": s.duration_ms,
                "positive_styles": list(s.styles),
                "negative_styles": list(s.negative),
            }
            for s in sections
        ]
    }


def plan_key(sections: Sequence[Section]) -> str:
    payload = json.dumps(
        [plan_payload(sections), MUSIC_MODEL, OUTPUT_FORMAT, PLAN_VERSION], sort_keys=True
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def windows(sections: Sequence[Section]) -> list[tuple[int, int]]:
    """(start, end) of every section in the track."""
    out: list[tuple[int, int]] = []
    start = 0
    for s in sections:
        out.append((start, start + s.duration_ms))
        start += s.duration_ms
    return out


def track_ms(sections: Sequence[Section]) -> int:
    return sum(s.duration_ms for s in sections)


def music_usd(ms: int) -> float:
    return round(ms / 60_000 * USD_PER_MINUTE, 6)


# --- words --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class SungWord:
    word: str
    start_ms: int
    end_ms: int


def _is_lyric(word: str) -> bool:
    w = word.strip()
    return bool(w) and not (w.startswith(("{", "[")) or w.endswith(("}", "]")))


def words_between(words: Sequence[SungWord], start_ms: int, end_ms: int) -> list[TimelineWord]:
    """The rapped words of one section, relative to its start (section names and {directions}
    are not lyrics)."""
    out: list[TimelineWord] = []
    for w in words:
        if start_ms <= w.start_ms < end_ms and _is_lyric(w.word):
            s = w.start_ms - start_ms
            e = max(s + 40, min(w.end_ms, end_ms) - start_ms)
            out.append(TimelineWord(w=w.word.strip(), s=s, e=e))
    return out


def parse_words(raw: Any) -> list[SungWord]:
    out: list[SungWord] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        try:
            word = str(item.get("word") or item.get("text") or "")
            start = int(float(item.get("start_ms", 0)))
            end = int(float(item.get("end_ms", start)))
        except (TypeError, ValueError):
            continue
        if word:
            out.append(SungWord(word, start, max(start, end)))
    return out


# --- the API --------------------------------------------------------------------------------------


class MusicError(Exception):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class Track:
    audio: bytes  # mp3
    words: list[SungWord]
    song_id: str | None


def _error_message(response: httpx.Response) -> str:
    try:
        detail = response.json().get("detail")
    except ValueError:
        return f"ElevenLabs Music {response.status_code}: {response.text[:200]}"
    if isinstance(detail, dict):
        text = detail.get("message") or detail.get("status") or json.dumps(detail)[:200]
        return f"ElevenLabs Music {response.status_code}: {text}"
    return f"ElevenLabs Music {response.status_code}: {str(detail)[:300]}"


def parse_detailed(content_type: str, body: bytes) -> Track:
    """The multipart/mixed answer of `/v1/music/detailed`: a JSON part (metadata, word
    timestamps) and the audio."""
    head = f"Content-Type: {content_type}\r\n\r\n".encode()
    message = BytesParser(policy=email_policy).parsebytes(head + body)
    meta: dict[str, Any] = {}
    audio = b""
    for part in message.iter_parts():  # type: ignore[attr-defined]
        payload = part.get_payload(decode=True)
        if not isinstance(payload, bytes) or not payload:
            continue
        if part.get_content_type() == "application/json":
            meta = json.loads(payload)
        else:
            audio = payload
    if not audio:
        raise MusicError("ElevenLabs Music answered without audio")
    return Track(audio, parse_words(meta.get("words_timestamps")), meta.get("song_id"))


def compose(
    sections: Sequence[Section],
    *,
    api_key: str | None = None,
    transport: httpx.BaseTransport | None = None,
) -> Track:
    """One generation (a rate limit or a server error is tried once more: those are not
    generated, so not billed)."""
    key = api_key or settings.ELEVENLABS_API_KEY or ""
    if not key:
        raise MusicError("ElevenLabs is not configured")
    url = f"{settings.ELEVENLABS_BASE_URL.rstrip('/')}/v1/music/detailed"
    body = {
        "composition_plan": plan_payload(sections),
        "model_id": MUSIC_MODEL,
        "with_timestamps": True,
    }
    timeout = httpx.Timeout(connect=15.0, read=600.0, write=60.0, pool=15.0)
    with httpx.Client(timeout=timeout, transport=transport, headers={"xi-api-key": key}) as client:
        for attempt in range(2):
            try:
                response = client.post(url, params={"output_format": OUTPUT_FORMAT}, json=body)
            except httpx.HTTPError as e:
                raise MusicError(f"ElevenLabs Music connection error: {type(e).__name__}") from e
            if response.status_code == 200:
                track = parse_detailed(response.headers.get("content-type", ""), response.content)
                song_id = track.song_id or response.headers.get("song-id")
                return Track(track.audio, track.words, song_id)
            if attempt == 0 and (response.status_code == 429 or response.status_code >= 500):
                logger.warning("ElevenLabs Music %s, trying once more", response.status_code)
                time.sleep(3)
                continue
            raise MusicError(_error_message(response), response.status_code)
    raise MusicError("ElevenLabs Music did not answer")  # pragma: no cover


# --- cache --------------------------------------------------------------------------------------


def cached(directory: Path, key: str) -> Track | None:
    audio, meta = directory / f"{key}.mp3", directory / f"{key}.json"
    if not (audio.exists() and meta.exists()):
        return None
    data = json.loads(meta.read_text())
    return Track(audio.read_bytes(), parse_words(data.get("words")), data.get("song_id"))


def store(directory: Path, key: str, track: Track) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    audio = directory / f"{key}.mp3"
    audio.write_bytes(track.audio)
    words = [{"word": w.word, "start_ms": w.start_ms, "end_ms": w.end_ms} for w in track.words]
    (directory / f"{key}.json").write_text(json.dumps({"song_id": track.song_id, "words": words}))
    return audio
