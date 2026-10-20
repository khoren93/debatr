"""Filesystem layout of generated media for one debate."""

import uuid
from dataclasses import dataclass
from pathlib import Path

from app.core.config import settings


def safe_debate_id(debate_id: str) -> str:
    return str(uuid.UUID(debate_id))


@dataclass(frozen=True)
class MediaPaths:
    debate_id: str

    @property
    def root(self) -> Path:
        return settings.media_root_path

    @property
    def dir(self) -> Path:
        return self.root / safe_debate_id(self.debate_id)

    @property
    def turns_dir(self) -> Path:
        return self.dir / "turns"

    def turn_raw(self, seq_index: int, chunk: int, ext: str) -> Path:
        return self.turns_dir / f"{seq_index:03d}.{chunk}.raw.{ext}"

    def turn_chunk_wav(self, seq_index: int, chunk: int) -> Path:
        return self.turns_dir / f"{seq_index:03d}.{chunk}.wav"

    def turn_wav(self, seq_index: int) -> Path:
        return self.turns_dir / f"{seq_index:03d}.wav"

    def turn_meta(self, seq_index: int) -> Path:
        return self.turns_dir / f"{seq_index:03d}.json"

    @property
    def visuals_dir(self) -> Path:
        """Pictures of the image scenes (`visuals/<hash>.webp` + `.json` metadata)."""
        return self.dir / "visuals"

    @property
    def covers_dir(self) -> Path:
        """AI covers: per version `<id>.webp` (1536 wide), `<id>-768.webp`, `<id>-yt.jpg`
        (1280x720) and `<id>-og.jpg` (1200x630); JPEG where ffmpeg has no WebP encoder."""
        return self.dir / "covers"

    @property
    def music_dir(self) -> Path:
        """Generated battle tracks (`music/<plan hash>.mp3` + `.json` with the word times)."""
        return self.dir / "music"

    @property
    def music_wav(self) -> Path:
        """The battle's track, loudness-normalized, before the MC and the judge go on it."""
        return self.dir / "music.wav"

    @property
    def timeline(self) -> Path:
        return self.dir / "timeline.json"

    @property
    def highlights(self) -> Path:
        """The host model's Short picks for the current transcript (`jobs.highlights_key`)."""
        return self.dir / "highlights.json"

    @property
    def full_wav(self) -> Path:
        return self.dir / "full.wav"

    @property
    def full_mp3(self) -> Path:
        return self.dir / "full.mp3"

    def rel(self, path: Path) -> str:
        return path.relative_to(self.dir).as_posix()


def public_url(debate_id: str, rel: str, version: str | None = None) -> str:
    base = f"/api/media/files/{safe_debate_id(debate_id)}/{rel}"
    return f"{base}?v={version}" if version else base
