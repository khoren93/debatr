"""Thin wrappers around the ffmpeg / ffprobe CLIs (worker only)."""

import json
import logging
import struct
import subprocess
from collections.abc import Callable
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger(__name__)


class FfmpegError(RuntimeError):
    def __init__(self, message: str, returncode: int | None = None) -> None:
        super().__init__(message)
        # Exit status of the process; None when it never ran or timed out.
        self.returncode = returncode


def run(bin_name: str, args: list[str], *, timeout_s: int = 600) -> bytes:
    try:
        proc = subprocess.run(
            [bin_name, *args],
            capture_output=True,
            timeout=timeout_s,
            check=False,
        )
    except FileNotFoundError as e:
        raise FfmpegError(f"{bin_name} is not installed") from e
    except subprocess.TimeoutExpired as e:
        raise FfmpegError(f"{bin_name} timed out after {timeout_s}s") from e
    if proc.returncode != 0:
        tail = proc.stderr.decode(errors="replace")[-800:]
        raise FfmpegError(f"{bin_name} exited with {proc.returncode}: {tail}", proc.returncode)
    return proc.stdout


def ffmpeg(args: list[str], *, timeout_s: int = 600) -> bytes:
    return run(settings.FFMPEG_BIN, ["-y", "-v", "error", *args], timeout_s=timeout_s)


def ffmpeg_available() -> bool:
    try:
        run(settings.FFMPEG_BIN, ["-version"], timeout_s=10)
        run(settings.FFPROBE_BIN, ["-version"], timeout_s=10)
        return True
    except FfmpegError:
        return False


def parse_ffprobe_duration_ms(payload: bytes) -> int:
    data = json.loads(payload.decode() or "{}")
    return round(float((data.get("format") or {}).get("duration") or 0) * 1000)


def probe_duration_ms(path: Path) -> int:
    out = run(
        settings.FFPROBE_BIN,
        ["-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        timeout_s=60,
    )
    return parse_ffprobe_duration_ms(out)


_PCM_ARGS = ["-ar", "44100", "-ac", "1", "-c:a", "pcm_s16le"]
# Trailing-silence trim: reverse, strip leading silence, reverse back, so word timestamps
# measured from the start of the clip stay valid.
_TRIM_FILTERS = (
    "areverse",
    "silenceremove=start_periods=1:start_duration=0:start_threshold=-45dB:start_silence=0.15",
    "areverse",
)


def _loudnorm_filter(lufs: float) -> str:
    return f"loudnorm=I={lufs}:TP=-1.5:LRA=11"


def _transcode(src: Path, dst: Path, audio_filter: str | None) -> None:
    args = ["-i", str(src)]
    if audio_filter:
        args += ["-af", audio_filter]
    ffmpeg([*args, *_PCM_ARGS, str(dst)])


def _normalize_two_pass(src: Path, dst: Path, loudnorm: str) -> None:
    trimmed = dst.with_name(f"{dst.stem}.trim.wav")
    try:
        _transcode(src, trimmed, ",".join(_TRIM_FILTERS))
        _transcode(trimmed, dst, loudnorm)
    finally:
        trimmed.unlink(missing_ok=True)


def normalize_turn(src: Path, dst: Path, *, target_lufs: float | None = None) -> None:
    """Trim trailing silence, normalize loudness and write 44.1 kHz mono 16-bit WAV.

    ffmpeg 7.1 (e.g. Debian trixie) sometimes aborts on the combined filter chain with
    "Assertion best_input >= 0 failed at fftools/ffmpeg_filter.c" depending on the input;
    ffmpeg 8 does not. When ffmpeg fails we retry with progressively simpler graphs rather
    than failing the whole build over a single turn.
    """
    lufs = settings.MEDIA_LOUDNESS_LUFS if target_lufs is None else target_lufs
    loudnorm = _loudnorm_filter(lufs)
    attempts: list[tuple[str, Callable[[], None]]] = [
        ("trim+loudnorm", lambda: _transcode(src, dst, ",".join([*_TRIM_FILTERS, loudnorm]))),
        ("two-pass trim then loudnorm", lambda: _normalize_two_pass(src, dst, loudnorm)),
        ("loudnorm only", lambda: _transcode(src, dst, loudnorm)),
    ]
    for i, (name, attempt) in enumerate(attempts):
        try:
            attempt()
            return
        except FfmpegError as e:
            # Missing binary / timeout: retrying cannot help.
            if e.returncode is None or i == len(attempts) - 1:
                raise
            logger.warning(
                "ffmpeg %s failed for %s (%s); retrying with a simpler filter graph",
                name,
                src.name,
                str(e).strip().splitlines()[-1][-200:],
            )


def envelope_from_pcm(pcm: bytes, *, rate: int, window_ms: int) -> list[float]:
    """RMS per window, normalized to 0..1 (pure)."""
    count = len(pcm) // 2
    if count == 0:
        return []
    samples = struct.unpack(f"<{count}h", pcm[: count * 2])
    win = max(1, round(rate * window_ms / 1000))
    levels: list[float] = []
    for i in range(0, count, win):
        chunk = samples[i : i + win]
        acc = sum((s / 32768.0) ** 2 for s in chunk)
        levels.append((acc / len(chunk)) ** 0.5)
    peak = max(0.05, max(levels))
    return [round(v / peak, 2) for v in levels]


def envelope(path: Path, *, window_ms: int = 50) -> list[float]:
    rate = 8000
    pcm = ffmpeg(["-i", str(path), "-f", "s16le", "-ac", "1", "-ar", str(rate), "-"], timeout_s=120)
    return envelope_from_pcm(pcm, rate=rate, window_ms=window_ms)


def concat_wavs(files: list[Path], dst: Path) -> None:
    """Concatenate WAV chunks of one turn back to back."""
    if len(files) == 1:
        ffmpeg(["-i", str(files[0]), "-c:a", "pcm_s16le", str(dst)])
        return
    args: list[str] = []
    filters: list[str] = []
    labels: list[str] = []
    for i, f in enumerate(files):
        args += ["-i", str(f)]
        filters.append(f"[{i}:a]aformat=sample_rates=44100:channel_layouts=mono[a{i}]")
        labels.append(f"[a{i}]")
    filters.append(f"{''.join(labels)}concat=n={len(labels)}:v=0:a=1[out]")
    ffmpeg(
        [
            *args,
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[out]",
            "-c:a",
            "pcm_s16le",
            str(dst),
        ]
    )


def concat_offsets(durations_ms: list[int], gap_ms: int) -> list[int]:
    """Start offset of each item when concatenated with `gap_ms` of silence between (pure)."""
    offsets: list[int] = []
    cursor = 0
    for i, d in enumerate(durations_ms):
        offsets.append(cursor)
        cursor += d + (gap_ms if i < len(durations_ms) - 1 else 0)
    return offsets


def concat_with_gaps(files: list[Path], gap_ms: int, dst_wav: Path, dst_mp3: Path) -> None:
    """Join turn WAVs with silence between them into full.wav and full.mp3."""
    args: list[str] = []
    filters: list[str] = []
    labels: list[str] = []
    idx = 0
    for i, f in enumerate(files):
        args += ["-i", str(f)]
        filters.append(f"[{idx}:a]aformat=sample_rates=44100:channel_layouts=mono[a{idx}]")
        labels.append(f"[a{idx}]")
        idx += 1
        if i < len(files) - 1:
            args += ["-f", "lavfi", "-t", f"{gap_ms / 1000:.3f}", "-i", "anullsrc=r=44100:cl=mono"]
            filters.append(f"[{idx}:a]aformat=sample_rates=44100:channel_layouts=mono[a{idx}]")
            labels.append(f"[a{idx}]")
            idx += 1
    filters.append(f"{''.join(labels)}concat=n={len(labels)}:v=0:a=1[out]")
    ffmpeg(
        [
            *args,
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[out]",
            "-ar",
            "44100",
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            str(dst_wav),
        ],
        timeout_s=900,
    )
    ffmpeg(["-i", str(dst_wav), "-c:a", "libmp3lame", "-b:a", "160k", str(dst_mp3)], timeout_s=900)


# --- the rap battle's track --------------------------------------------------------------------


def normalize_music(src: Path, dst: Path, *, target_lufs: float | None = None) -> None:
    """Loudness-normalize a generated track into 44.1 kHz stereo WAV (no silence trimming: the
    sections' timing is the timeline)."""
    lufs = settings.MEDIA_LOUDNESS_LUFS if target_lufs is None else target_lufs
    ffmpeg(
        [
            "-i",
            str(src),
            "-af",
            _loudnorm_filter(lufs),
            "-ar",
            "44100",
            "-ac",
            "2",
            "-c:a",
            "pcm_s16le",
            str(dst),
        ],
        timeout_s=900,
    )


def duck_filter(voices: list[tuple[int, int]], duck: float) -> str:
    """`volume` that lowers the music while a voice talks (start, end in ms; pure)."""
    if not voices:
        return "anull"
    spans = "+".join(f"between(t,{s / 1000:.3f},{e / 1000:.3f})" for s, e in voices)
    return f"volume={duck}:enable='{spans}'"


def mix_over(
    music: Path,
    voices: list[tuple[Path, int, int]],
    dst_wav: Path,
    dst_mp3: Path,
    *,
    duck: float = 0.3,
) -> None:
    """Put the voices (wav, start ms, length ms) on the music, which ducks under them, into
    stereo full.wav and full.mp3 as long as the music."""
    args = ["-i", str(music)]
    filters = [
        "[0:a]aformat=sample_rates=44100:channel_layouts=stereo,"
        f"{duck_filter([(s, s + d) for _, s, d in voices], duck)}[m]"
    ]
    labels = ["[m]"]
    for i, (wav, start, _length) in enumerate(voices, start=1):
        args += ["-i", str(wav)]
        filters.append(
            f"[{i}:a]aformat=sample_rates=44100:channel_layouts=stereo,adelay={start}|{start}[v{i}]"
        )
        labels.append(f"[v{i}]")
    filters.append(
        f"{''.join(labels)}amix=inputs={len(labels)}:duration=first:normalize=0,"
        "alimiter=limit=0.95[out]"
    )
    ffmpeg(
        [
            *args,
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[out]",
            "-ar",
            "44100",
            "-ac",
            "2",
            "-c:a",
            "pcm_s16le",
            str(dst_wav),
        ],
        timeout_s=900,
    )
    ffmpeg(["-i", str(dst_wav), "-c:a", "libmp3lame", "-b:a", "192k", str(dst_mp3)], timeout_s=900)


# --- pictures for the visual scenes ------------------------------------------------------


def to_webp(src: Path, dst: Path, *, max_width: int = 1600, quality: int = 80) -> None:
    """Re-encode a picture as WebP, at most `max_width` wide (also strips its metadata)."""
    scale = f"scale=w='min({max_width},iw)':h=-2"
    ffmpeg(
        [
            *["-i", str(src), "-frames:v", "1", "-vf", scale],
            *["-c:v", "libwebp", "-quality", str(quality), "-map_metadata", "-1", str(dst)],
        ],
        timeout_s=60,
    )


def to_jpeg(src: Path, dst: Path, *, width: int = 512, quality: int = 5) -> None:
    """JPEG of a picture, at most `width` wide (the vision check looks at a small one)."""
    scale = f"scale=w='min({width},iw)':h=-2"
    ffmpeg(
        [
            "-i",
            str(src),
            "-frames:v",
            "1",
            "-vf",
            scale,
            "-q:v",
            str(quality),
            "-map_metadata",
            "-1",
            str(dst),
        ],
        timeout_s=60,
    )


def to_web_image(src: Path, stem: Path, *, max_width: int = 1600) -> Path:
    """WebP next to `stem` (stem + ".webp"); JPEG when this ffmpeg has no WebP encoder (e.g.
    a Homebrew build without libwebp). Returns the written file."""
    webp = stem.with_suffix(".webp")
    try:
        to_webp(src, webp, max_width=max_width)
        return webp
    except FfmpegError as e:
        if e.returncode is None:
            raise
        logger.warning("No WebP encoder (%s), writing JPEG", str(e).strip()[-120:])
        webp.unlink(missing_ok=True)
    jpeg = stem.with_suffix(".jpg")
    to_jpeg(src, jpeg, width=max_width, quality=3)
    return jpeg
