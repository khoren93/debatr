"""Search engines: canonical addresses of the public pages, robots.txt and the sitemaps.

Pure functions (no database): the serializers (`path` fields, share links), the SEO routes
(app/api/routes_seo) and IndexNow (services/indexnow) all take a page's address from here, so a
page has exactly one.

A canonical address carries its topic as words (as StackOverflow does): `/d/{slug}/{kebab}` for a
debate, `/t/{slug}/{kebab}` for a topic. The kebab keeps the letters, marks and digits of every
script ("лучше-ли-удалённая-работа") and nothing else, at most KEBAB_MAX characters, cut between
words; the site answers any other spelling of the address (no kebab, an older topic text) with a
301 to this one. Paths are Unicode, the way browsers and messengers show them (IRIs); `encoded`
percent-encodes them for sitemaps, IndexNow and HTTP headers.
"""

import math
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import quote
from xml.sax.saxutils import escape

KEBAB_MAX = 60
SITEMAP_PAGE_SIZE = 10_000  # URLs per sitemap file (the protocol allows 50 000)
SITEMAP_CACHE_SECONDS = 3600
# Topics with a single public version are thin copies of that debate's page: they stay out of
# the index (noindex, follow on the page) and out of the sitemap.
TOPIC_INDEX_MIN_VERSIONS = 2

# Pages nobody should find through a search engine (they are noindex as well).
PRIVATE_PREFIXES = ("/api/", "/library", "/account", "/create", "/device", "/debate/")
# Crawlers that collect pages for AI models and assistants; refused only when
# SEO_ALLOW_AI_CRAWLERS is off (by default answers in assistants are part of the point).
AI_CRAWLERS = (
    "GPTBot",
    "OAI-SearchBot",
    "ChatGPT-User",
    "ClaudeBot",
    "Claude-SearchBot",
    "Claude-User",
    "anthropic-ai",
    "PerplexityBot",
    "Perplexity-User",
    "Google-Extended",
    "Applebot-Extended",
    "meta-externalagent",
    "Amazonbot",
    "CCBot",
    "Bytespider",
    "cohere-ai",
)
# The listing pages in pages.xml: home, gallery and ranking (and their rap-battle views).
LISTING_PATHS = (
    "/",
    "/gallery",
    "/gallery?format=rap_battle",
    "/leaderboard",
    "/leaderboard?format=rap_battle",
)


APOSTROPHES = frozenset("'\u2019\u02bc")  # apostrophes: "don't" stays one word


def _word_char(char: str) -> bool:
    # Letters, combining marks (Devanagari vowel signs, Arabic harakat) and digits of any script.
    return unicodedata.category(char)[0] in "LMN"


def kebab(text: str, limit: int = KEBAB_MAX) -> str:
    """ "Isn't remote work better?" → "isnt-remote-work-better"; "" when nothing is left."""
    normalized = unicodedata.normalize("NFKC", text).lower()
    kept = (c if _word_char(c) else " " for c in normalized if c not in APOSTROPHES)
    words = "".join(kept).split()
    out = ""
    for word in words:
        candidate = f"{out}-{word}" if out else word
        if len(candidate) > limit:
            # A single word longer than the limit (scripts without spaces) is cut as it is.
            return out or word[:limit]
        out = candidate
    return out


def _with_kebab(prefix: str, slug: str, text: str) -> str:
    words = kebab(text)
    return f"{prefix}/{slug}/{words}" if words else f"{prefix}/{slug}"


def debate_path(slug: str, topic: str) -> str:
    """The canonical path of a public debate."""
    return _with_kebab("/d", slug, topic)


def topic_path(slug: str, title: str) -> str:
    """The canonical path of a topic (its title: the first public version's text)."""
    return _with_kebab("/t", slug, title)


def debate_image_path(slug: str) -> str:
    """The link preview picture of a public debate, drawn by the site's renderer (frontend
    lib/og.ts `OG_PATHS`). Pages add its version (`?v=`); sitemaps name the stable address."""
    return f"/og/d/{slug}.png"


def topic_image_path(slug: str) -> str:
    """The link preview picture of a topic page (see `debate_image_path`)."""
    return f"/og/t/{slug}.png"


def absolute(site_url: str, path: str) -> str:
    return f"{site_url.rstrip('/')}{path}"


def encoded(url: str) -> str:
    """A URL with its non-ASCII characters percent-encoded (sitemaps, IndexNow, Location)."""
    return quote(url, safe=":/?&=#%~+,;@!$'()*[]")


# --- robots.txt -----------------------------------------------------------------------------------


def robots_txt(*, site_url: str, production: bool, allow_ai: bool) -> str:
    """Production: every public page, nothing private; elsewhere (staging, local stacks)
    nothing at all, so a test copy never competes with the site."""
    if not production:
        return "User-agent: *\nDisallow: /\n"
    lines = ["User-agent: *", "Allow: /", *(f"Disallow: {p}" for p in PRIVATE_PREFIXES), ""]
    if not allow_ai:
        lines += [*(f"User-agent: {bot}" for bot in AI_CRAWLERS), "Disallow: /", ""]
    lines.append(f"Sitemap: {absolute(site_url, '/sitemap.xml')}")
    return "\n".join(lines) + "\n"


# --- sitemaps -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class SitemapUrl:
    loc: str  # absolute URL (Unicode is fine: it is encoded here)
    lastmod: datetime | None = None
    images: Sequence[str] = field(default_factory=tuple)


def _w3c(moment: datetime) -> str:
    aware = moment if moment.tzinfo else moment.replace(tzinfo=UTC)
    return aware.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _loc(url: str) -> str:
    return escape(encoded(url))


def urlset(urls: Iterable[SitemapUrl]) -> str:
    """A sitemap file; `<image:image>` entries only when a page names its pictures."""
    items = list(urls)
    with_images = any(u.images for u in items)
    ns = 'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"'
    if with_images:
        ns += ' xmlns:image="http://www.google.com/schemas/sitemap-image/1.1"'
    out = ['<?xml version="1.0" encoding="UTF-8"?>', f"<urlset {ns}>"]
    for u in items:
        parts = [f"<loc>{_loc(u.loc)}</loc>"]
        if u.lastmod is not None:
            parts.append(f"<lastmod>{_w3c(u.lastmod)}</lastmod>")
        parts += [f"<image:image><image:loc>{_loc(i)}</image:loc></image:image>" for i in u.images]
        out.append(f"<url>{''.join(parts)}</url>")
    out.append("</urlset>")
    return "\n".join(out) + "\n"


def sitemap_index(files: Iterable[SitemapUrl]) -> str:
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for f in files:
        lastmod = f"<lastmod>{_w3c(f.lastmod)}</lastmod>" if f.lastmod is not None else ""
        out.append(f"<sitemap><loc>{_loc(f.loc)}</loc>{lastmod}</sitemap>")
    out.append("</sitemapindex>")
    return "\n".join(out) + "\n"


def debate_sitemap_count(public_debates: int) -> int:
    """How many `debates-{n}.xml` files the index lists (none without public debates)."""
    return math.ceil(public_debates / SITEMAP_PAGE_SIZE)


def latest(*moments: datetime | None) -> datetime | None:
    known = [m for m in moments if m is not None]
    return max(known) if known else None
