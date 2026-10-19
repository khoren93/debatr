"""ElevenLabs text-to-speech with word timestamps.

Primary path: /v1/text-to-speech/{voice}/with-timestamps (character alignment -> words).
Fallback for models that reject it: plain TTS + /v1/forced-alignment.
"""

import base64
import hashlib
import logging
import time
from typing import Any

import httpx

from app.core.config import settings
from app.services.media.alignment import WordTiming, chars_to_words, words_from_forced_alignment
from app.services.media.script import strip_audio_tags
from app.services.media.tts import SpeakerRef, SynthRequest, SynthResult, TTSError, VoiceInfo

logger = logging.getLogger(__name__)

OUTPUT_FORMAT = "mp3_44100_128"
MODELS: tuple[str, ...] = ("eleven_v3", "eleven_multilingual_v2", "eleven_flash_v2_5")
# Only these accept language_code; v2/v3 detect the language themselves.
LANGUAGE_CODE_MODELS = frozenset({"eleven_flash_v2_5", "eleven_turbo_v2_5"})
# Only v3 understands [audio tags]; for other models they are stripped.
TAG_MODELS = frozenset({"eleven_v3"})
# v3 rejects previous_text / next_text ("not yet supported with the 'eleven_v3' model").
NO_CONTEXT_TEXT_MODELS = frozenset({"eleven_v3"})
USD_PER_1K_CHARS: dict[str, float] = {
    "eleven_v3": 0.10,
    "eleven_multilingual_v2": 0.10,
    "eleven_flash_v2_5": 0.05,
    "eleven_turbo_v2_5": 0.05,
}

# Native voices for non-English debates come from the shared Voice Library. Free plans cannot
# use library voices through the API (402 paid_plan_required), so they get only stock voices.
LIBRARY_PAGE_SIZE = 60
_VOICES_TTL = 300.0
_voices_cache: dict[tuple[str, str], tuple[float, list[VoiceInfo]]] = {}

_ROLE_PREFERENCES: dict[str, list[str]] = {
    "moderator": ["George", "Daniel", "Brian", "Roger"],
    "debater": ["Sarah", "Charlie", "Alice", "Liam", "Jessica", "Callum", "Charlotte", "Eric"],
    "judge": ["Bill", "Lily", "Matilda", "Laura"],
}


class ElevenLabsProvider:
    name = "elevenlabs"

    def __init__(
        self, api_key: str | None = None, transport: httpx.BaseTransport | None = None
    ) -> None:
        self._api_key = api_key or settings.ELEVENLABS_API_KEY or ""
        self._transport = transport

    # --- plumbing ----------------------------------------------------------

    def available(self) -> bool:
        return bool(self._api_key)

    @property
    def base_url(self) -> str:
        return settings.ELEVENLABS_BASE_URL.rstrip("/")

    def _client(self) -> httpx.Client:
        return httpx.Client(
            timeout=httpx.Timeout(connect=15.0, read=180.0, write=60.0, pool=15.0),
            transport=self._transport,
            headers={"xi-api-key": self._api_key},
        )

    def _request(
        self, client: httpx.Client, method: str, url: str, *, attempts: int = 3, **kwargs: Any
    ) -> httpx.Response:
        last: httpx.Response | None = None
        for attempt in range(attempts):
            try:
                response = client.request(method, url, **kwargs)
            except httpx.HTTPError as e:
                raise TTSError(f"ElevenLabs connection error: {e}") from e
            if response.status_code != 429 and response.status_code < 500:
                return response
            last = response
            retry_after = response.headers.get("retry-after")
            wait = (
                float(retry_after) if retry_after and retry_after.isdigit() else 1.5 * (attempt + 1)
            )
            logger.warning("ElevenLabs %s, retrying in %.1fs", response.status_code, wait)
            time.sleep(wait)
        assert last is not None
        return last

    # --- voices ------------------------------------------------------------

    def list_voices(self, language_code: str) -> list[VoiceInfo]:
        """The account's voices plus, on paid plans, library voices native to the language.

        Voices verified for the language come first. Cached per key and language."""
        cache_key = (hashlib.sha256(self._api_key.encode()).hexdigest()[:16], language_code)
        cached = _voices_cache.get(cache_key)
        if cached and time.monotonic() - cached[0] < _VOICES_TTL:
            return list(cached[1])
        with self._client() as client:
            response = self._request(client, "GET", f"{self.base_url}/v1/voices")
            if response.status_code != 200:
                raise TTSError(_error_message(response), response.status_code)
            paid = self._paid_plan(client)
            voices = [
                _voice_info(v)
                for v in response.json().get("voices") or []
                # Library voices copied into "My Voices" are still library voices.
                if paid or (v.get("sharing") or {}).get("status") != "copied"
            ]
            if paid and language_code != "en":
                known = {v.id for v in voices}
                voices += [
                    v for v in self._library_voices(client, language_code) if v.id not in known
                ]
        voices.sort(key=lambda v: 0 if language_code in v.languages else 1)
        _voices_cache[cache_key] = (time.monotonic(), voices)
        return list(voices)

    def _paid_plan(self, client: httpx.Client) -> bool:
        """Whether the key's plan may use Voice Library voices (unknown counts as no)."""
        response = self._request(client, "GET", f"{self.base_url}/v1/user/subscription", attempts=1)
        if response.status_code != 200:
            return False
        tier = response.json().get("tier")
        return bool(tier) and tier != "free"

    def _library_voices(self, client: httpx.Client, language_code: str) -> list[VoiceInfo]:
        response = self._request(
            client,
            "GET",
            f"{self.base_url}/v1/shared-voices",
            params={"language": language_code, "page_size": LIBRARY_PAGE_SIZE},
            attempts=1,
        )
        if response.status_code != 200:
            logger.warning("ElevenLabs voice library: %s", _error_message(response))
            return []
        return [
            _voice_info(v)
            for v in response.json().get("voices") or []
            # Some library voices cost extra per character: keep the price predictable.
            if v.get("voice_id") and (v.get("rate") or 1.0) <= 1.0 and not v.get("fiat_rate")
        ]

    def default_voices(self, language_code: str, speakers: list[SpeakerRef]) -> dict[str, str]:
        voices = self.list_voices(language_code)
        return pick_default_voices(voices, speakers, language_code)

    # --- synthesis ---------------------------------------------------------

    def synthesize(self, request: SynthRequest) -> SynthResult:
        text = request.text if request.model_id in TAG_MODELS else strip_audio_tags(request.text)
        body: dict[str, Any] = {
            "text": text,
            "model_id": request.model_id,
            "apply_text_normalization": "auto",
        }
        if request.model_id not in NO_CONTEXT_TEXT_MODELS:
            if request.previous_text:
                body["previous_text"] = strip_audio_tags(request.previous_text)[-500:]
            if request.next_text:
                body["next_text"] = strip_audio_tags(request.next_text)[:500]
        if request.model_id in LANGUAGE_CODE_MODELS:
            body["language_code"] = request.language_code
        if request.model_id == "eleven_v3":
            body["voice_settings"] = {"stability": 0.5}

        with self._client() as client:
            url = f"{self.base_url}/v1/text-to-speech/{request.voice_id}/with-timestamps"
            response = self._request(
                client, "POST", url, params={"output_format": OUTPUT_FORMAT}, json=body
            )
            if response.status_code == 200:
                payload = response.json()
                alignment = payload.get("alignment") or payload.get("normalized_alignment")
                words = _alignment_to_words(alignment)
                return SynthResult(
                    audio=base64.b64decode(payload["audio_base64"]),
                    ext="mp3",
                    words=words,
                    char_cost=_char_cost(response, text),
                    note="timestamps: with-timestamps",
                )
            if response.status_code in (401, 402) or response.status_code >= 500:
                raise TTSError(_error_message(response), response.status_code)

            # Model without timestamp support: plain TTS + forced alignment.
            first_error = response.status_code
            url = f"{self.base_url}/v1/text-to-speech/{request.voice_id}"
            response = self._request(
                client, "POST", url, params={"output_format": OUTPUT_FORMAT}, json=body
            )
            if response.status_code != 200:
                raise TTSError(_error_message(response), response.status_code)
            audio = response.content
            note = f"with-timestamps unavailable ({first_error}); "
            words: list[WordTiming] | None = None
            try:
                words = self._forced_align(client, audio, strip_audio_tags(text))
                note += "timestamps: forced-alignment"
            except TTSError as e:
                note += f"forced-alignment failed: {e}"
            return SynthResult(
                audio=audio, ext="mp3", words=words, char_cost=_char_cost(response, text), note=note
            )

    def _forced_align(self, client: httpx.Client, audio: bytes, text: str) -> list[WordTiming]:
        response = self._request(
            client,
            "POST",
            f"{self.base_url}/v1/forced-alignment",
            files={"file": ("turn.mp3", audio, "audio/mpeg")},
            data={"text": text},
        )
        if response.status_code != 200:
            raise TTSError(_error_message(response), response.status_code)
        return words_from_forced_alignment(response.json())


def _voice_info(v: dict[str, Any]) -> VoiceInfo:
    """VoiceInfo from a /v1/voices entry (fields in `labels`) or a shared library voice
    (fields at the top level)."""
    labels = v.get("labels") or v
    langs = [str(item.get("language")) for item in v.get("verified_languages") or []]
    if isinstance(labels.get("language"), str):
        langs.append(labels["language"])
    description = " · ".join(
        str(labels[k]).replace("_", " ")
        for k in ("gender", "accent", "descriptive", "description", "use_case")
        # A library voice's `description` is a long blurb, not a label.
        if isinstance(labels.get(k), str) and labels[k] and len(labels[k]) <= 40
    )
    return VoiceInfo(
        id=str(v.get("voice_id")),
        name=str(v.get("name") or v.get("voice_id")),
        description=description or None,
        preview_url=v.get("preview_url"),
        gender=labels.get("gender") if isinstance(labels.get("gender"), str) else None,
        languages=tuple(dict.fromkeys(lang for lang in langs if lang and lang != "None")),
    )


def _alignment_to_words(alignment: dict[str, Any] | None) -> list[WordTiming] | None:
    if not alignment:
        return None
    chars = alignment.get("characters") or []
    starts = alignment.get("character_start_times_seconds") or []
    ends = alignment.get("character_end_times_seconds") or []
    if not chars or len(chars) != len(starts) or len(chars) != len(ends):
        return None
    words = chars_to_words(
        [str(c) for c in chars], [float(s) for s in starts], [float(e) for e in ends]
    )
    return words or None


def _char_cost(response: httpx.Response, text: str) -> int:
    raw = response.headers.get("character-cost")
    if raw and raw.isdigit():
        return int(raw)
    return len(strip_audio_tags(text))


def _error_message(response: httpx.Response) -> str:
    try:
        detail = response.json().get("detail")
        if isinstance(detail, dict):
            return f"ElevenLabs {response.status_code}: {detail.get('message') or detail.get('status')}"
        if isinstance(detail, str):
            return f"ElevenLabs {response.status_code}: {detail}"
    except ValueError:
        pass
    return f"ElevenLabs {response.status_code}: {response.text[:200]}"


def pick_default_voices(
    voices: list[VoiceInfo], speakers: list[SpeakerRef], language_code: str = "en"
) -> dict[str, str]:
    """Assign distinct voices by role preference, falling back to unused voices (pure).

    For non-English debates with native voices only those are used, alternating genders so
    neighbouring speakers are easy to tell apart."""
    native = [v for v in voices if language_code in v.languages]
    pool = native if language_code != "en" and native else voices
    by_name = {v.name.split(" - ")[0].lower(): v.id for v in pool}
    gender = {v.id: (v.gender or "").lower() for v in voices}
    used: set[str] = set()
    out: dict[str, str] = {}
    last_gender = ""
    for speaker in speakers:
        prefs = _ROLE_PREFERENCES.get(speaker.role, _ROLE_PREFERENCES["debater"])
        if speaker.role == "debater":
            prefs = prefs[speaker.index % len(prefs) :] + prefs[: speaker.index % len(prefs)]
        chosen = next(
            (
                by_name[p.lower()]
                for p in prefs
                if p.lower() in by_name and by_name[p.lower()] not in used
            ),
            None,
        )
        if chosen is None:
            unused = [v.id for v in pool if v.id not in used]
            contrast = [i for i in unused if last_gender and gender[i] and gender[i] != last_gender]
            chosen = next(
                iter(contrast or unused or [v.id for v in voices if v.id not in used]),
                voices[0].id if voices else "",
            )
        used.add(chosen)
        last_gender = gender.get(chosen, "")
        out[speaker.id] = chosen
    return out


# --- system key probe ------------------------------------------------------

_PROBE_OK_TTL = 600.0
_PROBE_FAIL_TTL = 60.0
_probe_cache: tuple[float, bool, str | None] | None = None


def system_key_status(*, force: bool = False) -> tuple[bool, str | None]:
    """Whether the system ElevenLabs key actually works: (ok, reason).

    Restricted keys are accepted by the API only for the permissions they were created with,
    so the key is probed with the voice list (needs `voices_read`). Cached per process.
    """
    global _probe_cache
    if not settings.ELEVENLABS_API_KEY:
        return False, "No ElevenLabs key is configured on this server"
    now = time.monotonic()
    if not force and _probe_cache is not None:
        stamp, ok, reason = _probe_cache
        if now - stamp < (_PROBE_OK_TTL if ok else _PROBE_FAIL_TTL):
            return ok, reason
    provider = ElevenLabsProvider()
    try:
        with provider._client() as client:
            response = provider._request(
                client, "GET", f"{provider.base_url}/v1/voices", attempts=1
            )
        ok = response.status_code == 200
        reason = None if ok else _error_message(response)
    except TTSError as e:
        ok, reason = False, str(e)
    if not ok:
        logger.warning("System ElevenLabs key rejected: %s", reason)
    _probe_cache = (now, ok, reason)
    return ok, reason


_PLAN_TTL = 600.0
_plan_cache: dict[str, tuple[float, bool]] = {}


def music_allowed(api_key: str, *, transport: httpx.BaseTransport | None = None) -> bool:
    """Whether a user's key may generate music (the Music API is for paid plans only): its plan
    is a paid one. Unknown (no answer, no "User read" permission) counts as no. Cached by key."""
    digest = hashlib.sha256(api_key.encode()).hexdigest()[:16]
    now = time.monotonic()
    cached = _plan_cache.get(digest)
    if cached and now - cached[0] < _PLAN_TTL:
        return cached[1]
    provider = ElevenLabsProvider(api_key, transport=transport)
    try:
        with provider._client() as client:
            allowed = provider._paid_plan(client)
    except TTSError:
        allowed = False
    _plan_cache[digest] = (now, allowed)
    return allowed


_QUOTA_TTL = 300.0
_quota_cache: tuple[float, dict[str, Any] | None] | None = None


def system_quota() -> dict[str, Any] | None:
    """The system key's plan and character quota ({tier, used, limit, resets_at}), or None when
    there is no key or ElevenLabs does not answer (needs the "User read" permission). Cached
    per process for a few minutes; for the admin console."""
    global _quota_cache
    if not settings.ELEVENLABS_API_KEY:
        return None
    now = time.monotonic()
    if _quota_cache is not None and now - _quota_cache[0] < _QUOTA_TTL:
        return _quota_cache[1]
    provider = ElevenLabsProvider()
    quota: dict[str, Any] | None = None
    try:
        with provider._client() as client:
            response = provider._request(
                client, "GET", f"{provider.base_url}/v1/user/subscription", attempts=1
            )
        if response.status_code == 200:
            data = response.json()
            quota = {
                "tier": str(data.get("tier") or ""),
                "used": int(data.get("character_count") or 0),
                "limit": int(data.get("character_limit") or 0),
                "resets_at": data.get("next_character_count_reset_unix"),
            }
    except (TTSError, ValueError):
        quota = None
    _quota_cache = (now, quota)
    return quota


def estimate_usd(model_id: str, chars: int) -> float | None:
    rate = USD_PER_1K_CHARS.get(model_id)
    return round(chars / 1000 * rate, 4) if rate else None
