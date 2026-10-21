"""Views of public debates: one per IP and debate in six hours, never the owner's, and where they
came from.

A view is counted only by the page's beacon (`POST /api/debates/{id}/view`), sent by the browser
after the page has hydrated (the debate page) or when an embedded player first plays (the embed:
the frame loads with every visit of the other page). Reading a debate through the API (the page
renderer, client navigations, the CLI, agents) counts nothing, and neither do bots (by User-Agent).

Each view is kept as a count per UTC day in `view_days` by `place` (the debate's page or a player
on another site) and `source`, a class of the referring site (`classify`): search engines, AI
assistants, social networks and messengers, embeds (a player elsewhere, or its "Watch on Debatr"
link), other sites, no referrer at all (direct: typed, bookmarks, most messenger apps) and the
site's own pages (internal). Only the referrer's host reaches the server, and only counts are
stored: no IP, no address, no account. Sites that embed a debate are ranked in Redis per debate
and overall (`EMBED_KEY`), forgotten after EMBED_DAYS without a view.
"""

import logging
import re
import uuid
from collections.abc import Collection
from datetime import UTC, datetime
from typing import Literal
from urllib.parse import urlsplit

from redis.exceptions import RedisError
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import get_async_redis
from app.models.models import Debate, User, ViewDay

logger = logging.getLogger(__name__)

VIEW_COOLDOWN_SECONDS = 6 * 3600

Place = Literal["page", "embed"]
Source = Literal["search", "ai", "social", "embed", "other", "direct", "internal"]
#: In the order the console stacks and lists them (frontend components/admin/charts/palette.ts).
SOURCES: tuple[Source, ...] = ("search", "ai", "social", "embed", "other", "direct", "internal")
PLACES: tuple[Place, ...] = ("page", "embed")

#: Embedding sites, a sorted set per debate (`EMBED_KEY.format(id)`) and one for the whole site.
EMBED_KEY = "views:embeds:{}"
EMBED_ALL_KEY = "views:embeds"
EMBED_DAYS = 90

# Crawlers, previews, monitors and scripts. Bots that run JavaScript could send the beacon; the
# others never load the page's scripts at all.
_BOT = re.compile(
    r"bot\b|bot/|spider|crawl|slurp|scrape|fetch|preview|headless|lighthouse|pagespeed|"
    r"inspectiontool|facebookexternalhit|embedly|iframely|bitlybot|python|httpx|curl|wget|"
    r"go-http-client|okhttp|java/|libwww|axios|node-fetch|undici|phantomjs|selenium|puppeteer|"
    r"playwright|monitor|uptime|pingdom|validator",
    re.IGNORECASE,
)

# Referring sites by host suffix ("google.com" covers www.google.com and news.google.com).
# AI assistants come first: gemini.google.com is an assistant, not a search.
AI_HOSTS = (
    "chatgpt.com",
    "chat.openai.com",
    "perplexity.ai",
    "claude.ai",
    "gemini.google.com",
    "bard.google.com",
    "copilot.microsoft.com",
    "copilot.cloud.microsoft",
    "chat.mistral.ai",
    "chat.deepseek.com",
    "grok.com",
    "meta.ai",
    "poe.com",
    "you.com",
    "phind.com",
    "kimi.com",
    "chat.qwen.ai",
)
SEARCH_HOSTS = (
    "bing.com",
    "duckduckgo.com",
    "ya.ru",
    "search.yahoo.com",
    "baidu.com",
    "ecosia.org",
    "search.brave.com",
    "startpage.com",
    "qwant.com",
    "search.naver.com",
    "search.seznam.cz",
    "kagi.com",
    "mojeek.com",
    "yep.com",
    "sogou.com",
    "petalsearch.com",
    "search.aol.com",
    "ask.com",
)
# google.<tld>, google.co.<tld>, google.com.<tld> and yandex.<tld> (any subdomain but the apps').
_SEARCH_ENGINES = re.compile(r"(^|\.)(google|yandex)\.(com?\.)?[a-z]{2,3}$")
_NOT_SEARCH = ("mail.google.com", "docs.google.com", "drive.google.com", "mail.yandex.ru")
SOCIAL_HOSTS = (
    "t.co",
    "x.com",
    "twitter.com",
    "facebook.com",
    "fb.com",
    "messenger.com",
    "instagram.com",
    "threads.net",
    "threads.com",
    "linkedin.com",
    "lnkd.in",
    "reddit.com",
    "redd.it",
    "t.me",
    "telegram.org",
    "telegram.me",
    "vk.com",
    "vk.ru",
    "ok.ru",
    "youtube.com",
    "youtu.be",
    "tiktok.com",
    "bsky.app",
    "mastodon.social",
    "discord.com",
    "discordapp.com",
    "news.ycombinator.com",
    "lobste.rs",
    "producthunt.com",
    "pinterest.com",
    "quora.com",
    "whatsapp.com",
    "slack.com",
    "pikabu.ru",
)

_HOST = re.compile(r"^[a-z0-9.-]{1,253}$")


def is_bot(user_agent: str | None) -> bool:
    """A crawler, a link preview, a monitor or a script (no User-Agent at all counts as one)."""
    return not user_agent or _BOT.search(user_agent) is not None


def host_of(value: str | None) -> str | None:
    """A referrer's host, lowercase, without a port or `www.`: from a host or a whole URL.
    Anything that is not a plausible host name → None."""
    text = (value or "").strip().lower()
    if not text:
        return None
    try:
        host = urlsplit(text if "//" in text else f"//{text}").hostname or ""
    except ValueError:
        return None
    host = host.rstrip(".").removeprefix("www.")
    plausible = host == "localhost" or ("." in host and _HOST.match(host) is not None)
    return host if plausible else None


def _under(host: str, domains: tuple[str, ...]) -> bool:
    return any(host == d or host.endswith(f".{d}") for d in domains)


def classify(
    host: str | None,
    *,
    site_host: str,
    site_aliases: Collection[str] = (),
    place: Place = "page",
    ref: str = "",
    internal: bool = False,
) -> Source:
    """Where a view came from. `host`: the referrer's (`host_of`); `site_host`: the site's own,
    `site_aliases` its former hosts; `ref`: the page's `?ref=` (`embed` = the "Watch on Debatr"
    link of a player); `internal`: a navigation inside the site (the browser keeps the first
    page's referrer for those)."""
    own = host is not None and (host == site_host or host in site_aliases)
    if internal or (own and place == "page" and ref != "embed"):
        return "internal"
    if place == "embed":
        # The player on another site; on the site itself it is the Share menu's preview.
        return "internal" if own else "embed"
    if ref == "embed":
        return "embed"
    if host is None:
        return "direct"
    if _under(host, AI_HOSTS):
        return "ai"
    if host not in _NOT_SEARCH and (_SEARCH_ENGINES.search(host) or _under(host, SEARCH_HOSTS)):
        return "search"
    if _under(host, SOCIAL_HOSTS):
        return "social"
    return "other"


async def count_view(
    db: AsyncSession,
    debate: Debate,
    viewer: User | None,
    *,
    client: str,
    place: Place = "page",
    source: Source = "direct",
    embed_host: str | None = None,
    now: datetime | None = None,
) -> bool:
    """One view of a public debate from `client` (its IP), at most one per six hours and never
    the owner's: the debate's counter, the day's row and, for a player on another site, that
    site's rank. Returns whether it counted."""
    if not debate.is_public or (viewer is not None and viewer.id == debate.user_id):
        return False
    redis = get_async_redis()
    try:
        fresh = await redis.set(
            f"views:{debate.id}:{client}", "1", nx=True, ex=VIEW_COOLDOWN_SECONDS
        )
    except RedisError:
        logger.debug("View counter unavailable for %s", debate.id)
        return False
    if not fresh:
        return False
    day = (now or datetime.now(UTC)).date()
    await db.execute(update(Debate).where(Debate.id == debate.id).values(views=Debate.views + 1))
    row = {"day": day, "debate_id": debate.id, "place": place, "source": source, "views": 1}
    await db.execute(
        insert(ViewDay)
        .values(**row)
        .on_conflict_do_update(
            index_elements=["day", "debate_id", "place", "source"],
            set_={"views": ViewDay.views + 1},
        )
    )
    await db.commit()
    debate.views = (debate.views or 0) + 1
    if embed_host and source == "embed" and place == "embed":
        await _note_embed(debate.id, embed_host)
    return True


async def _note_embed(debate_id: uuid.UUID, host: str) -> None:
    redis = get_async_redis()
    ttl = EMBED_DAYS * 86400
    try:
        for key in (EMBED_KEY.format(debate_id), EMBED_ALL_KEY):
            await redis.zincrby(key, 1, host)
            await redis.expire(key, ttl)
    except RedisError:
        logger.debug("Embed ranking unavailable for %s", debate_id)


async def embedding_sites(
    debate_id: uuid.UUID | None = None, limit: int = 10
) -> list[dict[str, object]]:
    """The sites whose players were watched most (of one debate, or of all), last EMBED_DAYS."""
    key = EMBED_KEY.format(debate_id) if debate_id else EMBED_ALL_KEY
    try:
        rows = await get_async_redis().zrevrange(key, 0, limit - 1, withscores=True)
    except RedisError:
        return []
    return [{"host": str(host), "views": int(score)} for host, score in rows]
