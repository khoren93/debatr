"""Pictures for "image" scenes: free photos from Wikimedia Commons or AI-generated images.

The director only describes a subject. The media build looks for it on Commons (freely
licensed files only, author and licence shown in the frame) or generates it
(`MEDIA_IMAGE_MODEL`, paid from the owner's balance). A vision model checks every picture
(the subject is there; no identifiable people, logos, gore or text) before it is used. Pictures
are re-encoded to WebP (JPEG without a WebP encoder) and cached in `MEDIA_ROOT/{debate}/visuals/`
by a hash of the subject, so rebuilds reuse them. Parsing and prompts are pure and unit-tested.
"""

import base64
import hashlib
import html
import json
import logging
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from pydantic import ValidationError

from app.core.config import settings
from app.schemas.visuals import ImageScene
from app.services.media import ffmpeg
from app.services.media.llm import complete, extract_json, generate_image
from app.services.media.paths import MediaPaths

logger = logging.getLogger(__name__)

COMMONS_API = "https://commons.wikimedia.org/w/api.php"
IMAGE_HOSTS = frozenset({"upload.wikimedia.org", "thumb.wikimedia.org"})
MAX_DOWNLOAD_BYTES = 8 * 1024 * 1024
SEARCH_LIMIT = 10
CANDIDATES = 4  # pictures the vision check compares at once
FETCH_WIDTH = 1600
_FREE_LICENSE_RE = re.compile(
    r"^(cc0|cc[- ]zero|public domain|pd\b|pd-|cc[- ]by(?:[- ]sa)?[- ]\d)", re.IGNORECASE
)
_NOT_PHOTO_RE = re.compile(
    r"\b(logo|map|flag|diagram|chart|graph|coat of arms|icon|signature|screenshot|poster|"
    r"infographic|svg|seal|emblem|banner|text)\b",
    re.IGNORECASE,
)
_MIMES = frozenset({"image/jpeg", "image/png", "image/webp"})
AI_STYLE = (
    "Editorial illustration for a debate show, cinematic light, muted colours, wide shot. "
    "No text, no letters, no logos, no recognizable people."
)


@dataclass(frozen=True)
class Candidate:
    url: str  # resized file on upload/thumb.wikimedia.org
    page_url: str  # the file page on Commons
    title: str
    author: str
    license: str
    width: int
    height: int


def strip_html(text: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", text or "")).split())


def commons_params(query: str) -> dict[str, str | int]:
    return {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": f"{query} filetype:bitmap",
        "gsrnamespace": 6,
        "gsrlimit": SEARCH_LIMIT,
        "prop": "imageinfo",
        "iiprop": "url|size|mime|extmetadata",
        "iiurlwidth": FETCH_WIDTH,
        "iiextmetadatafilter": "LicenseShortName|Artist|Credit",
    }


def _meta(info: dict[str, Any], name: str) -> str:
    value = ((info.get("extmetadata") or {}).get(name) or {}).get("value")
    return strip_html(str(value or ""))


def parse_commons(payload: Any) -> list[Candidate]:
    """Freely licensed photos from a Commons search, best match first. Skips logos, maps,
    flags, diagrams and pictures too small or oddly shaped for the stage."""
    pages = ((payload or {}).get("query") or {}).get("pages") or {}
    out: list[Candidate] = []
    for page in sorted(pages.values(), key=lambda p: int(p.get("index") or 0)):
        title = str(page.get("title") or "")
        info = (page.get("imageinfo") or [{}])[0]
        url = str(info.get("thumburl") or info.get("url") or "")
        width = int(info.get("thumbwidth") or info.get("width") or 0)
        height = int(info.get("thumbheight") or info.get("height") or 0)
        licence = _meta(info, "LicenseShortName")
        if (
            info.get("mime") not in _MIMES
            or urlparse(url).netloc not in IMAGE_HOSTS
            or not _FREE_LICENSE_RE.match(licence)
            or _NOT_PHOTO_RE.search(title)
            or width < 640
            or height < 360
            or not 0.8 <= width / max(1, height) <= 2.6
        ):
            continue
        author = _meta(info, "Artist") or _meta(info, "Credit") or "Unknown author"
        out.append(
            Candidate(
                url=url,
                page_url=str(info.get("descriptionurl") or ""),
                title=title,
                author=author[:80],
                license=licence[:40],
                width=width,
                height=height,
            )
        )
    return out


def search_queries(subject: str, attempts: int = 3) -> list[str]:
    """Commons search matches every word: retry with fewer words when nothing is found."""
    words = [w for w in re.split(r"[\s,;]+", subject) if w]
    queries: list[str] = []
    for size in (len(words), 4, 2):
        query = " ".join(words[:size])
        if query and query not in queries:
            queries.append(query)
    return queries[:attempts]


def photo_credit(candidate: Candidate) -> str:
    return f"Photo: {candidate.author} · {candidate.license} · Wikimedia Commons"


def build_pick_messages(subject: str, images: list[bytes]) -> list[dict[str, Any]]:
    """Vision check: which of the numbered pictures fits the subject and the rules."""
    text = (
        "You choose pictures for a family-friendly debate video. "
        f"Wanted: {subject}. There {'is 1 picture' if len(images) == 1 else f'are {len(images)} numbered pictures'}. "
        "A picture is acceptable only if it clearly shows the subject in good quality and has no "
        "identifiable person or face as its main subject, no nudity, gore or violence, no logo or "
        "brand as the focus, and is not a screenshot, chart, map, diagram or mostly text. "
        'Reply with JSON only: {"pick": <number of the best acceptable picture, or null>, '
        '"reason": "<a few words>"}'
    )
    content: list[dict[str, Any]] = [{"type": "text", "text": text}]
    for i, data in enumerate(images, start=1):
        content.append({"type": "text", "text": f"Picture {i}:"})
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{base64.b64encode(data).decode()}"},
            }
        )
    return [{"role": "user", "content": content}]


def parse_pick(text: str, count: int) -> int | None:
    """0-based index of the chosen picture, None when none is acceptable."""
    try:
        payload = extract_json(text)
    except (ValueError, json.JSONDecodeError):
        return None
    pick = payload.get("pick") if isinstance(payload, dict) else None
    if isinstance(pick, bool) or pick is None:
        return None
    try:
        number = int(pick)
    except (TypeError, ValueError):
        return None
    return number - 1 if 1 <= number <= count else None


def ai_prompt(subject: str) -> str:
    return f"{subject.strip().rstrip('.')}. {AI_STYLE}"


def image_digest(kind: str, subject: str) -> str:
    return hashlib.sha256(f"{kind}|{' '.join(subject.lower().split())}".encode()).hexdigest()[:24]


@dataclass
class Picture:
    src: str
    kind: str  # photo | ai
    credit: str
    source_url: str = ""


class ImageStudio:
    """Finds or generates the pictures of one media build and counts what AI images cost."""

    def __init__(self, paths: MediaPaths, *, mode: str, allow_ai: bool) -> None:
        self.paths = paths
        self.mode = mode  # stock | ai
        self.allow_ai = allow_ai and mode == "ai"
        self.check_model = settings.MEDIA_VISUALS_MODEL or settings.VERDICT_MODEL
        self.ai_usd = 0.0  # provider cost of pictures generated in this build
        self.ai_count = 0
        self.check_usd = 0.0  # vision checks and other system-key calls (not billed)
        self.paths.visuals_dir.mkdir(parents=True, exist_ok=True)

    # --- cache -------------------------------------------------------------------------

    def _cached(self, digest: str) -> Picture | None:
        meta = self.paths.visuals_dir / f"{digest}.json"
        if not meta.exists():
            return None
        try:
            data = json.loads(meta.read_text())
            name = str(data["file"])
            if not (self.paths.visuals_dir / name).exists():
                return None
            return Picture(
                src=f"visuals/{name}",
                kind=str(data["kind"]),
                credit=str(data.get("credit") or ""),
                source_url=str(data.get("source_url") or ""),
            )
        except (OSError, ValueError, KeyError):
            return None

    def _store(self, digest: str, raw: Path, picture: Picture) -> Picture:
        written = ffmpeg.to_web_image(raw, self.paths.visuals_dir / digest)
        meta = {"file": written.name, "kind": picture.kind, "credit": picture.credit}
        meta["source_url"] = picture.source_url
        (self.paths.visuals_dir / f"{digest}.json").write_text(json.dumps(meta))
        picture.src = f"visuals/{written.name}"
        return picture

    # --- checks ------------------------------------------------------------------------

    def _pick(self, subject: str, files: list[Path], tmp: Path) -> int | None:
        thumbs: list[bytes] = []
        for i, f in enumerate(files):
            thumb = tmp / f"thumb{i}.jpg"
            ffmpeg.to_jpeg(f, thumb)
            thumbs.append(thumb.read_bytes())
        text, usage = complete(
            self.check_model,
            build_pick_messages(subject, thumbs),
            purpose="image_check",
            max_tokens=200,
        )
        self.check_usd += float((usage or {}).get("cost") or 0.0)
        return parse_pick(text, len(files))

    # --- sources -----------------------------------------------------------------------

    def _generate(self, subject: str, tmp: Path) -> Picture | None:
        digest = image_digest("ai", subject)
        if cached := self._cached(digest):
            return cached
        data, usage = generate_image(
            settings.MEDIA_IMAGE_MODEL,
            ai_prompt(subject),
            fallback_cost=settings.MEDIA_IMAGE_PRICE_USD,
        )
        self.ai_usd += float((usage or {}).get("cost") or settings.MEDIA_IMAGE_PRICE_USD)
        self.ai_count += 1
        raw = tmp / "ai.bin"
        raw.write_bytes(data)
        if self._pick(subject, [raw], tmp) is None:
            logger.info("AI picture of %r rejected by the check", subject)
            return None
        picture = Picture(src="", kind="ai", credit="AI-generated image")
        return self._store(digest, raw, picture)

    def _photo(self, subject: str, tmp: Path) -> Picture | None:
        digest = image_digest("photo", subject)
        if cached := self._cached(digest):
            return cached
        headers = {"User-Agent": f"Debatr/1.0 ({settings.SITE_URL}; media worker)"}
        with httpx.Client(timeout=30.0, headers=headers, follow_redirects=False) as client:
            candidates: list[Candidate] = []
            for query in search_queries(subject):
                response = client.get(COMMONS_API, params=commons_params(query))
                response.raise_for_status()
                candidates = parse_commons(response.json())[:CANDIDATES]
                if candidates:
                    break
            files: list[Path] = []
            kept: list[Candidate] = []
            for i, candidate in enumerate(candidates):
                try:
                    data = client.get(candidate.url)
                    data.raise_for_status()
                except httpx.HTTPError as e:
                    logger.info("Could not fetch %s: %s", candidate.url, e)
                    continue
                if len(data.content) > MAX_DOWNLOAD_BYTES:
                    continue
                path = tmp / f"photo{i}.bin"
                path.write_bytes(data.content)
                files.append(path)
                kept.append(candidate)
        if not files:
            return None
        pick = self._pick(subject, files, tmp)
        if pick is None:
            logger.info("No acceptable photo of %r among %d", subject, len(files))
            return None
        chosen = kept[pick]
        picture = Picture(
            src="",
            kind="photo",
            credit=photo_credit(chosen),
            source_url=chosen.page_url,
        )
        return self._store(digest, files[pick], picture)

    def resolve(self, scene: ImageScene) -> ImageScene | None:
        """The scene with its picture filled in, or None when no acceptable picture exists.
        AI mode falls back to a free photo when generation fails or is not allowed."""
        with tempfile.TemporaryDirectory(dir=self.paths.visuals_dir) as raw_dir:
            tmp = Path(raw_dir)
            picture: Picture | None = None
            if self.allow_ai:
                try:
                    picture = self._generate(scene.subject, tmp)
                except Exception as e:
                    logger.warning("AI picture of %r failed: %s", scene.subject, e)
            if picture is None:
                try:
                    picture = self._photo(scene.subject, tmp)
                except Exception as e:
                    logger.warning("Photo search for %r failed: %s", scene.subject, e)
        if picture is None:
            return None
        data = {**scene.model_dump(), "src": picture.src, "kind": picture.kind}
        data["credit"] = picture.credit
        try:
            return ImageScene.model_validate({**data, "source_url": picture.source_url})
        except ValidationError:
            return ImageScene.model_validate(data)  # an odd source link: keep the picture
