"""IndexNow: tell Bing, Yandex, Seznam, Naver and Yep at once that a public page changed.

Publishing, unpublishing, deleting, an admin's approval or topic move note the debate's page and
its topic in a Redis set (`announce` / `announce_sync`, never failing the caller); the scheduler's
`flush_job` (every FLUSH_SECONDS, background queue) sends what gathered in one POST to
api.indexnow.org, which shares it with every engine of the protocol. Topics are noted by id and
get their address when sent: their title (the first public version) may change meanwhile, and a
topic with no public version left is sent as its short address, which answers 404.

Only in production with an https SITE_URL and a valid INDEXNOW_KEY (served at /{key}.txt by
app/api/routes_seo); elsewhere nothing is noted. Free: no provider_usage rows.
"""

import logging
import re
import uuid
from collections.abc import Iterable
from typing import Any
from urllib.parse import urlsplit

import httpx
from redis import Redis
from redis.asyncio import Redis as AsyncRedis
from redis.exceptions import RedisError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.redis import get_async_redis, get_sync_redis
from app.models.models import Debate, Motion
from app.services import seo
from app.services.motions import (
    indexed_topics_query,
    public_clause,
    published_sql,
    topic_sql,
    topic_text,
)

logger = logging.getLogger(__name__)

ENDPOINT = "https://api.indexnow.org/indexnow"
PENDING_KEY = "indexnow:pending"
PENDING_TTL = 86_400  # nothing sends them (scheduler down): dropped after a day
LOCK_KEY = "indexnow:flush:lock"
FLUSH_SECONDS = 60
JOB_TIMEOUT = 60
BATCH_LIMIT = 10_000  # URLs per POST (the protocol's limit)
TIMEOUT_S = 15
MOTION_PREFIX = "motion:"
KEY_RE = re.compile(r"^[A-Za-z0-9-]{8,128}$")
# Answers worth another try next minute; any other refusal (400 bad request, 403 key not
# found, 422 URL of another host) would fail again.
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


def key_valid() -> bool:
    return bool(KEY_RE.match(settings.INDEXNOW_KEY))


def enabled() -> bool:
    return settings.is_production and settings.SITE_URL.startswith("https://") and key_valid()


def debate_url(slug: str, topic: str) -> str:
    return seo.encoded(seo.absolute(settings.SITE_URL, seo.debate_path(slug, topic)))


def refs_of(slug: str | None, topic: str, motion_id: uuid.UUID | None) -> list[str]:
    """What a change of this debate's visibility touches: its page and its topic's page."""
    refs = [debate_url(slug, topic)] if slug else []
    if motion_id is not None:
        refs.append(f"{MOTION_PREFIX}{motion_id}")
    return refs


def debate_refs(debate: Debate) -> list[str]:
    return refs_of(debate.slug, topic_text(debate), debate.motion_id)


async def public_refs(db: AsyncSession, user_id: uuid.UUID) -> list[str]:
    """The pages of an account's public debates (before the console hides or deletes them)."""
    if not enabled():
        return []
    rows = await db.execute(
        select(Debate.slug, Debate.config_json, Debate.title, Debate.motion_id).where(
            Debate.user_id == user_id, *public_clause()
        )
    )
    refs: list[str] = []
    for slug, conf, title, motion_id in rows.all():
        topic = str((conf or {}).get("topic") or title or "")
        refs += [r for r in refs_of(slug, topic, motion_id) if r not in refs]
    return refs


def _note(redis: Redis, refs: list[str]) -> None:
    pipe = redis.pipeline()
    pipe.sadd(PENDING_KEY, *refs)
    pipe.expire(PENDING_KEY, PENDING_TTL)
    pipe.execute()


def announce_sync(refs: Iterable[str]) -> None:
    """Note pages to send with the next flush (worker side)."""
    items = list(refs)
    if not items or not enabled():
        return
    try:
        _note(get_sync_redis(), items)
    except RedisError as e:
        logger.warning("IndexNow: could not note %d pages: %s", len(items), e.__class__.__name__)


async def _note_async(redis: AsyncRedis, refs: list[str]) -> None:
    pipe = redis.pipeline()
    pipe.sadd(PENDING_KEY, *refs)
    pipe.expire(PENDING_KEY, PENDING_TTL)
    await pipe.execute()


async def announce(refs: Iterable[str]) -> None:
    """API-side twin of `announce_sync`."""
    items = list(refs)
    if not items or not enabled():
        return
    try:
        await _note_async(get_async_redis(), items)
    except RedisError as e:
        logger.warning("IndexNow: could not note %d pages: %s", len(items), e.__class__.__name__)


# --- sending --------------------------------------------------------------------------------------


def topic_url(db: Session, motion_id: uuid.UUID) -> str | None:
    """A topic's address now: canonical while it has a public version, else the short one."""
    motion = db.get(Motion, motion_id)
    if motion is not None and motion.merged_into_id is not None:
        motion = db.get(Motion, motion.merged_into_id)
    if motion is None:
        return None
    first = db.execute(
        select(Debate.config_json, Debate.title)
        .where(Debate.motion_id == motion.id, *public_clause())
        .order_by(func.coalesce(Debate.published_at, Debate.created_at), Debate.created_at)
        .limit(1)
    ).first()
    if first is None:
        return seo.encoded(seo.absolute(settings.SITE_URL, f"/t/{motion.slug}"))
    title = str((first.config_json or {}).get("topic") or first.title or "")
    return seo.encoded(seo.absolute(settings.SITE_URL, seo.topic_path(motion.slug, title)))


def resolve(db: Session, refs: Iterable[str]) -> list[str]:
    urls: list[str] = []
    for ref in refs:
        url: str | None = ref
        if ref.startswith(MOTION_PREFIX):
            try:
                url = topic_url(db, uuid.UUID(ref.removeprefix(MOTION_PREFIX)))
            except ValueError:
                url = None
        if url and url not in urls:
            urls.append(url)
    return urls


def all_urls(db: Session) -> list[str]:
    """Every page the sitemaps list, at its address now: the listings, the topics worth a search
    result and every public debate (a move to a new domain announces them all at once)."""
    site = settings.SITE_URL.rstrip("/")
    urls = [seo.encoded(seo.absolute(site, path)) for path in seo.LISTING_PATHS]
    urls += [
        seo.encoded(seo.absolute(site, seo.topic_path(row.slug, row.title)))
        for row in db.execute(indexed_topics_query()).all()
    ]
    debates = db.execute(
        select(Debate.slug, topic_sql())
        .where(*public_clause())
        .order_by(published_sql().desc(), Debate.id)
    ).all()
    urls += [debate_url(slug, topic) for slug, topic in debates if slug]
    return list(dict.fromkeys(urls))


def submit_all(urls: list[str], *, transport: httpx.BaseTransport | None = None) -> bool:
    """Send every URL in batches of BATCH_LIMIT; True when each batch was accepted."""
    accepted = True
    for start in range(0, len(urls), BATCH_LIMIT):
        status = submit(urls[start : start + BATCH_LIMIT], transport=transport)
        accepted = accepted and status in (200, 202)
    return accepted


def payload(urls: list[str]) -> dict[str, Any]:
    site = settings.SITE_URL.rstrip("/")
    return {
        "host": urlsplit(site).hostname,
        "key": settings.INDEXNOW_KEY,
        "keyLocation": f"{site}/{settings.INDEXNOW_KEY}.txt",
        "urlList": urls,
    }


def submit(urls: list[str], *, transport: httpx.BaseTransport | None = None) -> int:
    """POST the URLs; the answer's status (0 when the request failed)."""
    try:
        with httpx.Client(timeout=TIMEOUT_S, transport=transport) as client:
            response = client.post(ENDPOINT, json=payload(urls))
    except httpx.HTTPError as e:
        logger.warning("IndexNow: request failed: %s", e.__class__.__name__)
        return 0
    if response.status_code in (200, 202):
        logger.info("IndexNow: sent %d URLs (%d)", len(urls), response.status_code)
    else:
        logger.warning("IndexNow: %d URLs refused with %d", len(urls), response.status_code)
    return response.status_code


def flush_job() -> None:
    """RQ job (scheduler, every FLUSH_SECONDS): send the noted pages in one request; a passing
    failure puts them back for the next minute."""
    if not enabled():
        return
    redis = get_sync_redis()
    if not redis.set(LOCK_KEY, "1", nx=True, ex=JOB_TIMEOUT):
        return
    try:
        raw: Any = redis.spop(PENDING_KEY, BATCH_LIMIT)
        refs = [r.decode() if isinstance(r, bytes) else str(r) for r in (raw or [])]
        if not refs:
            return
        from app.core.sync_db import get_sync_session

        with get_sync_session() as db:
            urls = resolve(db, refs)
        status = submit(urls) if urls else 200
        if status == 0 or status in RETRY_STATUSES:
            _note(redis, refs)
    finally:
        redis.delete(LOCK_KEY)
