"""The presence beacon: what a page tells the server, checked and written into `visits` and
`visit_events`.

A beacon is text/plain JSON (no CORS preflight; `navigator.sendBeacon` survives the page being
closed) with the visitor's and the visit's ids and a few events: `page` (a page shown, with the
landing's referrer and query on a visit's first page), `time` (milliseconds a shown page stayed
in front, sent while it does and when it is left) and `action` (one of ACTIONS). The visit row is
made by its first beacon; later ones add to it. A beacon naming a visit of another visitor, or
anything unreadable, is dropped without an answer the page could act on.

Each beacon also carries counts of the page's input since the previous one and, once per page
load, what the browser says about itself (`bots.ClientSignals` / `bots.ClientEnv`); with the
request's headers and the network they decide whether the visit is a person, a bot or an AI
agent, weighed again with every beacon (`bots.classify`).
"""

import logging
import re
import uuid
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal
from urllib.parse import parse_qs, urlsplit

from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import Select, distinct, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Debate, User, Visit, VisitEvent
from app.services.audience import bots
from app.services.audience.agent import parse_agent
from app.services.audience.geo import lookup, network
from app.services.views import Source, classify, host_of

logger = logging.getLogger(__name__)

MAX_BODY = 32_000
MAX_EVENTS = 40
MAX_ENGAGED_MS = 30 * 60_000  # one `time` event; a page in front longer sends more of them
CROWD_WINDOW = timedelta(days=1)  # new browsers on the same IP (bots.Facts.crowd)

#: What the site reports (frontend lib/presence.ts `track`), with the console's words.
ACTIONS: dict[str, str] = {
    "signup": "Created an account",
    "login": "Signed in",
    "logout": "Signed out",
    "video_play": "Played a video",
    "video_progress": "Watched part of a video",
    "like": "Liked a debate",
    "vote": "Voted who won",
    "share": "Opened Share",
    "copy_link": "Copied a link",
    "copy_embed": "Copied the embed code",
    "remix": "Started a remix",
    "verdict_reveal": "Revealed the verdict",
    "export_mp4": "Exported an MP4",
    "download_mp3": "Downloaded the MP3",
    "wizard_step": "Moved on in the wizard",
    "topic_pick": "Picked a trending topic",
    "topic_ideas": "Asked AI for topics",
    "debate_start": "Started a debate",
    "draft_save": "Saved a draft",
    "checkout": "Opened a top-up",
    "topup": "Topped up credits",
    "cli_login": "Approved a CLI login",
    "token_create": "Created an API token",
    "gallery_filter": "Filtered the gallery",
}

_SCREEN = re.compile(r"^\d{2,5}x\d{2,5}$")
_SAFE_TEXT = re.compile(r"[^\w .,:;/@+()\-]", re.UNICODE)
_UTM_KEYS = ("utm_source", "utm_medium", "utm_campaign")

# utm_source / utm_medium words → a source class, for links without a referrer (apps, mail).
_UTM_SOCIAL = (
    "twitter", "x", "facebook", "fb", "instagram", "ig", "threads", "linkedin", "reddit",
    "telegram", "tg", "vk", "ok", "youtube", "yt", "tiktok", "bluesky", "bsky", "mastodon",
    "discord", "whatsapp", "wa", "hn", "hackernews", "producthunt", "pikabu", "social",
)  # fmt: skip
_UTM_SEARCH = ("google", "bing", "yandex", "duckduckgo", "ddg", "baidu", "brave", "ecosia")
_UTM_AI = ("chatgpt", "openai", "perplexity", "claude", "gemini", "copilot", "deepseek", "grok")


class BeaconEvent(BaseModel):
    type: Literal["page", "time", "action"]
    # The page's id (a `page` event makes it, `time` events add to it).
    id: uuid.UUID | None = None
    path: str = Field(default="/", max_length=2000)
    # The landing's query (utm_*, ref) and referrer: only on a visit's first page.
    query: str | None = Field(default=None, max_length=2000)
    referrer: str | None = Field(default=None, max_length=2000)
    ms: int = Field(default=0, ge=0, le=MAX_ENGAGED_MS)
    name: str | None = Field(default=None, max_length=32)
    debate: uuid.UUID | None = None
    props: dict[str, str | int | float | bool | None] = Field(default_factory=dict)

    @field_validator("props")
    @classmethod
    def _small(cls, value: dict[str, Any]) -> dict[str, Any]:
        return {
            str(k)[:24]: v[:100] if isinstance(v, str) else v for k, v in list(value.items())[:8]
        }


class Beacon(BaseModel):
    visitor: uuid.UUID
    visit: uuid.UUID
    events: list[BeaconEvent] = Field(default_factory=list, max_length=MAX_EVENTS)
    screen: str | None = Field(default=None, max_length=16)
    lang: str | None = Field(default=None, max_length=16)
    tz: str | None = Field(default=None, max_length=48)
    touch: bool = False
    # The visit began on a page opened earlier (a tab left for half an hour): no landing.
    resumed: bool = False
    # The page's input since its previous beacon, and (once per page load) the browser's facts.
    signals: bots.ClientSignals | None = None
    env: bots.ClientEnv | None = None


def parse_beacon(body: bytes) -> Beacon | None:
    if not body or len(body) > MAX_BODY:
        return None
    try:
        return Beacon.model_validate_json(body)
    except ValidationError:
        return None


def clean_path(raw: str) -> str:
    """The path alone (no query or fragment: `?code=` of the device page must not be kept)."""
    path = urlsplit(raw.strip() or "/").path or "/"
    return path[:300] if path.startswith("/") else "/"


def clean_referrer(raw: str | None) -> str | None:
    """The referring page without its query (searches and tokens stay out)."""
    if not raw:
        return None
    try:
        parts = urlsplit(raw.strip())
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    return f"{parts.scheme}://{parts.hostname}{parts.path}"[:300]


def _text(value: str | None, limit: int) -> str | None:
    cleaned = _SAFE_TEXT.sub("", (value or "").strip())[:limit]
    return cleaned or None


def campaign(query: str | None) -> dict[str, str | None]:
    """utm_source / utm_medium / utm_campaign and `ref` of the landing address."""
    params = parse_qs((query or "").lstrip("?"), keep_blank_values=False)
    out: dict[str, str | None] = {k: _text(params.get(k, [""])[0], 100) for k in _UTM_KEYS}
    out["ref"] = _text(params.get("ref", [""])[0], 40)
    return out


def utm_class(utm_source: str | None, utm_medium: str | None) -> Source | None:
    """A campaign link opened without a referrer (an app, a mail): its class from its words."""
    words = {
        w for w in re.split(r"[^a-z0-9]+", f"{utm_source or ''} {utm_medium or ''}".lower()) if w
    }
    if not words:
        return None
    if words & set(_UTM_AI):
        return "ai"
    if words & set(_UTM_SEARCH) or words & {"cpc", "ppc", "organic"}:
        return "search"
    if words & set(_UTM_SOCIAL):
        return "social"
    return "other"


def visit_source(
    referrer: str | None,
    utm: dict[str, str | None],
    *,
    site_host: str,
    site_aliases: Collection[str],
    resumed: bool,
) -> tuple[Source, str | None]:
    """(class, referring host) of a visit's landing."""
    if resumed:
        return "internal", None
    host = host_of(referrer)
    ref = utm.get("ref") or ""
    source = classify(host, site_host=site_host, site_aliases=site_aliases, ref=ref)
    if source == "direct":
        source = utm_class(utm.get("utm_source"), utm.get("utm_medium")) or "direct"
    own = host is not None and (host == site_host or host in site_aliases)
    return source, None if own else host


_DEBATE_PAGE = re.compile(r"^/d/([A-Za-z0-9_-]{4,40})(?:/|$)")
_OWNER_PAGE = re.compile(r"^/debate/([0-9a-fA-F-]{36})(?:/|$)")


def page_slug(path: str) -> str | None:
    match = _DEBATE_PAGE.match(path)
    return match.group(1) if match else None


def page_debate_id(path: str) -> uuid.UUID | None:
    match = _OWNER_PAGE.match(path)
    if not match:
        return None
    try:
        return uuid.UUID(match.group(1))
    except ValueError:
        return None


@dataclass
class Context:
    ip: str | None
    user_agent: str | None
    user: User | None
    now: datetime
    site_host: str
    site_aliases: Collection[str]
    request: bots.RequestFacts | None = None


def visit_facts(
    visit: Visit,
    *,
    at: datetime,
    crowd: int = 0,
    pageviews: int | None = None,
    engaged_ms: int | None = None,
    signals: dict[str, Any] | None = None,
    signed_in: bool | None = None,
) -> bots.Facts:
    """The verdict's view of a visit at `at` (its last beacon); the keywords are the values the
    beacon being written is about to store."""
    agent = parse_agent(visit.user_agent) if visit.user_agent else None
    return bots.Facts(
        user_agent=visit.user_agent,
        browser=visit.browser or (agent.browser if agent else None),
        os=visit.os or (agent.os if agent else None),
        device=visit.device or "desktop",
        screen=visit.screen,
        timezone=visit.timezone,
        pageviews=visit.pageviews if pageviews is None else pageviews,
        engaged_ms=visit.engaged_ms if engaged_ms is None else engaged_ms,
        duration_ms=max(0, int((at - visit.started_at).total_seconds() * 1000)),
        returning=not visit.new_visitor,
        signed_in=visit.user_id is not None if signed_in is None else signed_in,
        place=", ".join(p for p in (visit.city, visit.country) if p) or None,
        network=visit.network,
        network_kind=visit.network_kind,
        crowd=crowd,
        signals=(visit.signals or {}) if signals is None else signals,
        now=at,
    )


def crowd_query(visit: Visit, now: datetime) -> Select[int]:
    """Other browsers new to the site on this visit's IP in the day before `now`."""
    return select(func.count(distinct(Visit.visitor_id))).where(
        Visit.ip == visit.ip,
        Visit.started_at >= now - CROWD_WINDOW,
        Visit.started_at <= now,
        Visit.new_visitor.is_(True),
        Visit.visitor_id != visit.visitor_id,
    )


async def crowd_of(db: AsyncSession, visit: Visit, now: datetime) -> int:
    return int(await db.scalar(crowd_query(visit, now)) or 0) if visit.ip else 0


async def _debates(db: AsyncSession, beacon: Beacon) -> tuple[dict[str, uuid.UUID], set[uuid.UUID]]:
    """Debate ids of the beacon's pages (by slug) and the action ids that exist."""
    slugs = {s for e in beacon.events if e.type == "page" and (s := page_slug(clean_path(e.path)))}
    wanted = {e.debate for e in beacon.events if e.debate}
    wanted |= {
        d for e in beacon.events if e.type == "page" and (d := page_debate_id(clean_path(e.path)))
    }
    by_slug: dict[str, uuid.UUID] = {}
    if slugs:
        rows = await db.execute(select(Debate.slug, Debate.id).where(Debate.slug.in_(slugs)))
        by_slug = {slug: debate_id for slug, debate_id in rows.all() if slug}
    known: set[uuid.UUID] = set()
    if wanted:
        known = set((await db.scalars(select(Debate.id).where(Debate.id.in_(wanted)))).all())
    return by_slug, known


async def _open_visit(db: AsyncSession, beacon: Beacon, ctx: Context) -> Visit | None:
    """The beacon's visit, made by its first beacon; None when it is another visitor's."""
    visit = await db.get(Visit, beacon.visit)
    if visit is not None:
        return visit if visit.visitor_id == beacon.visitor else None
    first = next((e for e in beacon.events if e.type == "page"), None)
    utm = campaign(first.query if first else None)
    source, host = visit_source(
        first.referrer if first else None,
        utm,
        site_host=ctx.site_host,
        site_aliases=ctx.site_aliases,
        resumed=beacon.resumed,
    )
    agent = parse_agent(ctx.user_agent, touch=beacon.touch)
    place = lookup(ctx.ip)
    net = network(ctx.ip)
    earlier = await db.scalar(select(Visit.id).where(Visit.visitor_id == beacon.visitor).limit(1))
    landing = clean_path(first.path) if first else "/"
    row = {
        "id": beacon.visit,
        "visitor_id": beacon.visitor,
        "started_at": ctx.now,
        "last_at": ctx.now,
        "ip": (ctx.ip or "")[:64] or None,
        "user_agent": (ctx.user_agent or "")[:300] or None,
        "country": place.country if place else None,
        "region": place.region if place else None,
        "city": place.city if place else None,
        "source": source,
        "referrer_host": host,
        "referrer": None
        if source == "internal"
        else clean_referrer(first.referrer if first else None),
        "utm_source": utm["utm_source"],
        "utm_medium": utm["utm_medium"],
        "utm_campaign": utm["utm_campaign"],
        "ref": utm["ref"],
        "landing": landing,
        "exit_path": landing,
        "device": agent.device,
        "browser": agent.browser,
        "os": agent.os,
        "screen": beacon.screen if beacon.screen and _SCREEN.match(beacon.screen) else None,
        "language": _text(beacon.lang, 16),
        "timezone": _text(beacon.tz, 48),
        "new_visitor": earlier is None,
        # The IP's longitude stays with the request facts: the verdict compares the clock with it.
        "signals": {"srv": {"lon": round(place.longitude, 1)}}
        if place and place.longitude is not None
        else {},
        "network": net.org if net else None,
        "network_kind": bots.network_kind(net.asn, net.org) if net else None,
    }
    await db.execute(insert(Visit).values(**row).on_conflict_do_nothing(index_elements=["id"]))
    visit = await db.get(Visit, beacon.visit, populate_existing=True)
    return visit if visit is not None and visit.visitor_id == beacon.visitor else None


async def record(db: AsyncSession, beacon: Beacon, ctx: Context) -> bool:
    """Write the beacon; False when it was dropped."""
    visit = await _open_visit(db, beacon, ctx)
    if visit is None:
        return False
    by_slug, known = await _debates(db, beacon)
    pages = actions = engaged = 0
    last_path: str | None = None
    for i, event in enumerate(beacon.events):
        at = ctx.now + timedelta(microseconds=i)  # keeps the beacon's order
        path = clean_path(event.path)
        if event.type == "page":
            slug = page_slug(path)
            owner_page = page_debate_id(path)
            debate_id = by_slug.get(slug) if slug else owner_page if owner_page in known else None
            result = await db.execute(
                insert(VisitEvent)
                .values(
                    id=event.id or uuid.uuid4(),
                    visit_id=visit.id,
                    at=at,
                    kind="page",
                    name="page",
                    path=path,
                    debate_id=debate_id,
                    engaged_ms=0,
                    props={},
                )
                .on_conflict_do_nothing(index_elements=["id"])
            )
            pages += getattr(result, "rowcount", 0) or 0
            last_path = path
        elif event.type == "time" and event.id and event.ms:
            result = await db.execute(
                update(VisitEvent)
                .where(VisitEvent.id == event.id, VisitEvent.visit_id == visit.id)
                .values(engaged_ms=VisitEvent.engaged_ms + event.ms)
            )
            if getattr(result, "rowcount", 0):
                engaged += event.ms
        elif event.type == "action" and event.name in ACTIONS:
            db.add(
                VisitEvent(
                    visit_id=visit.id,
                    at=at,
                    kind="action",
                    name=event.name,
                    path=path,
                    debate_id=event.debate if event.debate in known else None,
                    props=event.props,
                )
            )
            actions += 1
    user = ctx.user
    signals = bots.merge(visit.signals, beacon.signals, beacon.env, ctx.request)
    assessment = bots.classify(
        visit_facts(
            visit,
            at=ctx.now,
            crowd=await crowd_of(db, visit, ctx.now),
            pageviews=visit.pageviews + pages,
            engaged_ms=visit.engaged_ms + engaged,
            signals=signals,
            signed_in=visit.user_id is not None or user is not None,
        )
    )
    values: dict[str, Any] = {
        "last_at": ctx.now,
        "pageviews": Visit.pageviews + pages,
        "actions": Visit.actions + actions,
        "engaged_ms": Visit.engaged_ms + engaged,
        "signals": signals,
        "verdict": assessment.verdict,
        "bot_score": assessment.score,
        "bot_reasons": assessment.stored_reasons(),
    }
    if last_path:
        values["exit_path"] = last_path
    if user is not None:
        values["user_id"] = user.id
        if user.admin_role:
            values["staff"] = True
    await db.execute(update(Visit).where(Visit.id == visit.id).values(**values))
    await db.commit()
    return True
