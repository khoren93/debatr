"""Public debates on other sites: the player page `/embed/{slug}` (drawn by the site's renderer,
frontend routes/embed.tsx) and oEmbed (`GET /api/oembed`, app/api/routes_oembed).

Pure functions: which page a pasted link names, the player's size within a consumer's limits and
its iframe. Only public debates are embedded; nothing here tells who won (the audience votes
blind). The query of an embed (`format=short`, `t=`) mirrors frontend lib/embed.ts.
"""

import math
import re
from dataclasses import dataclass
from html import escape
from typing import Any, Literal
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit

from app.services import seo

EmbedFormat = Literal["long", "short"]
PageKind = Literal["debate", "topic"]

PROVIDER_NAME = "Debatr"
#: The player's size when the consumer gives no limit: the 16:9 episode, the 9:16 Short.
DEFAULT_WIDTH: dict[EmbedFormat, int] = {"long": 640, "short": 360}
#: The widest player a consumer's `maxwidth` gets (a Short stays phone-sized).
MAX_WIDTH: dict[EmbedFormat, int] = {"long": 1280, "short": 405}
RATIO: dict[EmbedFormat, tuple[int, int]] = {"long": (16, 9), "short": (9, 16)}
#: Seconds a consumer may keep an answer (the page's title and picture change rarely).
CACHE_AGE = 3600
#: What the player may do inside the frame: start with sound on a click (full screen comes with
#: `allowfullscreen`: next to `fullscreen` in `allow` Chrome warns on the consumer's page).
ALLOW = "autoplay; picture-in-picture"
#: The link preview picture (`seo.debate_image_path`), 1200 by 630.
THUMBNAIL_SIZE = (1200, 630)
#: Longest start offset taken from `t=` (seconds): no debate runs this long.
MAX_START = 6 * 3600

_SLUG = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_START = re.compile(r"^(\d{1,5})s?$")
_PAGES: dict[str, PageKind] = {"d": "debate", "t": "topic", "embed": "debate"}


@dataclass(frozen=True)
class EmbedTarget:
    """What a link names: a debate or a topic by slug, and how to play it."""

    kind: PageKind
    slug: str
    format: EmbedFormat = "long"
    start: int = 0  # seconds into the video


def _host(netloc: str) -> str:
    host = netloc.rsplit("@", 1)[-1].split(":", 1)[0].lower()
    return host.removeprefix("www.")


def parse_start(value: str) -> int:
    """`t=83` or `t=83s` → 83; anything else (or past MAX_START) → 0."""
    match = _START.match(value.strip())
    seconds = int(match.group(1)) if match else 0
    return seconds if seconds <= MAX_START else 0


def parse_url(url: str, site_url: str) -> EmbedTarget | None:
    """The page a link of this site names: `/d/{slug}[/{words}]`, `/t/{slug}[/{words}]` or
    `/embed/{slug}`, with its `format=short` and `t=` kept. Other hosts (the port and a `www.`
    do not count) and other pages → None."""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None
    if _host(parts.netloc) != _host(urlsplit(site_url).netloc):
        return None
    segments = [unquote(s) for s in parts.path.split("/") if s]
    if len(segments) < 2 or segments[0] not in _PAGES or not _SLUG.match(segments[1]):
        return None
    # Pages end in the topic's words (any spelling: the site redirects it); the player has none.
    if len(segments) > (2 if segments[0] == "embed" else 3):
        return None
    query: dict[str, str] = {}
    for key, value in parse_qsl(parts.query):
        query.setdefault(key, value)
    return EmbedTarget(
        kind=_PAGES[segments[0]],
        slug=segments[1],
        format="short" if query.get("format") == "short" else "long",
        start=parse_start(query.get("t", "")),
    )


def fit(
    fmt: EmbedFormat, maxwidth: int | None = None, maxheight: int | None = None
) -> tuple[int, int]:
    """The player's width and height in the video's proportions: as wide as the consumer allows
    (up to MAX_WIDTH; DEFAULT_WIDTH without a limit), never past `maxwidth` / `maxheight`."""
    rw, rh = RATIO[fmt]
    width = float(min(maxwidth, MAX_WIDTH[fmt]) if maxwidth else DEFAULT_WIDTH[fmt])
    if maxheight and width * rh / rw > maxheight:
        width = maxheight * rw / rh
    w = max(1, math.floor(width))
    return w, max(1, math.floor(w * rh / rw))


def embed_path(slug: str, fmt: EmbedFormat = "long", start: int = 0) -> str:
    """`/embed/{slug}` with the Short (`format=short`) and the start (`t=` seconds) when asked."""
    query = {
        **({"format": "short"} if fmt == "short" else {}),
        **({"t": str(start)} if start > 0 else {}),
    }
    return f"/embed/{quote(slug, safe='')}" + (f"?{urlencode(query)}" if query else "")


def iframe_html(src: str, title: str, width: int, height: int) -> str:
    """The player's iframe: sized for the consumer, sound and full screen allowed, lazy."""
    return (
        f'<iframe src="{escape(src)}" width="{width}" height="{height}" title="{escape(title)}" '
        f'style="border:0" allow="{ALLOW}" allowfullscreen loading="lazy"></iframe>'
    )


def embed_title(topic: str, debaters: list[str]) -> str:
    """The player's name on the consumer's page: "{topic} — A vs B"."""
    topic = " ".join(topic.split()) or "AI debate"
    versus = " vs ".join(name for name in debaters if name)
    return f"{topic} — {versus}" if versus else topic


def oembed_payload(
    *,
    site_url: str,
    slug: str,
    title: str,
    author: str | None,
    playable: bool,
    fmt: EmbedFormat = "long",
    start: int = 0,
    maxwidth: int | None = None,
    maxheight: int | None = None,
) -> dict[str, Any]:
    """The oEmbed 1.0 answer for one public debate. `playable` (its audio is ready): a `video`;
    otherwise the frame shows a card that links to the transcript, a `rich` embed."""
    width, height = fit(fmt, maxwidth, maxheight)
    src = seo.absolute(site_url, embed_path(slug, fmt, start))
    thumb_w, thumb_h = THUMBNAIL_SIZE
    payload: dict[str, Any] = {
        "version": "1.0",
        "type": "video" if playable else "rich",
        "provider_name": PROVIDER_NAME,
        "provider_url": f"{site_url.rstrip('/')}/",
        "title": title,
        "html": iframe_html(seo.encoded(src), title, width, height),
        "width": width,
        "height": height,
        "thumbnail_url": seo.encoded(seo.absolute(site_url, seo.debate_image_path(slug))),
        "thumbnail_width": thumb_w,
        "thumbnail_height": thumb_h,
        "cache_age": CACHE_AGE,
    }
    if author:
        payload["author_name"] = author
    return payload
