"""Trending topics: today's news turned into debate topics, one batch per refresh.

A refresh reads the RSS feeds in FEEDS, keeps fresh headlines (at most MAX_AGE_HOURS old) that
pass the blocklist and sends a balanced pool of them (round-robin over the feeds) to
`TRENDING_MODEL`. The model merges reports about one story and writes a motion, a neutral brief
(the debaters do not know recent news; the wizard puts it into `description`) and a category per
story, citing the numbers of the headlines it used. Code keeps only topics grounded in those
headlines, ranks them by the model's heat plus the number of outlets that carry the story, and
saves the best `TRENDING_TOPIC_COUNT` with their source articles as a new `TrendingBatch`. The
newest batch is what the site shows; older batches stay as an archive.

Safety: what must never reach the site (sexual content, graphic violence, tragedies, abuse of
children, private people, hate) is filtered three times: BLOCKED_TERMS on every headline before
the model sees it, the same blocklist on the generated text, and a second, focused review call
(SAFETY_RULES) over the finished list. The batch is saved only when that review answered (fails
closed): visitors keep the previous batch. Admins can still hide a topic.

Triggers: `python -m app.scheduler` enqueues `refresh_trending_job` hourly and the API enqueues it
when the newest batch is older than TRENDING_REFRESH_HOURS. The job checks `is_due` itself and
holds a Redis lock while it builds, so extra triggers are harmless and restarts never cause extra
batches.
"""

from __future__ import annotations

import html
import json
import logging
import math
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import feedparser
import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.redis import get_sync_redis, trending_lock_key
from app.core.sync_db import get_sync_session
from app.models.models import TrendingBatch, TrendingTopic, utcnow
from app.services.media import llm
from app.services.openrouter_client import OpenRouterError

logger = logging.getLogger(__name__)

MAX_AGE_HOURS = 48  # older headlines are not news any more
MIN_POOL, MAX_POOL = 60, 400  # headlines sent to the model: 3 per wanted topic, within these
EXTRA_TOPICS = 1.2  # ask for 20% more topics than shown: filters and the review drop some
OUTLET_BONUS = 1.5  # ranking points per extra outlet that carries the story (up to 3 extra)
REFRESH_SLACK = timedelta(minutes=30)  # hourly ticks must not push the daily batch later
LOCK_TTL = 1800  # seconds; a crashed build frees the lock after this
JOB_TIMEOUT = 900
FEED_TIMEOUT = 20.0
GENERATE_TIMEOUT = 300.0

# Display order of the categories (the wizard filters by them).
TOPIC_CATEGORIES: tuple[str, ...] = (
    "politics",
    "world",
    "business",
    "tech",
    "science",
    "health",
    "culture",
    "sports",
    "lifestyle",
)
CATEGORY_ALIASES = {
    "law": "politics",
    "government": "politics",
    "elections": "politics",
    "society": "politics",
    "international": "world",
    "economy": "business",
    "money": "business",
    "finance": "business",
    "technology": "tech",
    "ai": "tech",
    "environment": "science",
    "climate": "science",
    "space": "science",
    "medicine": "health",
    "entertainment": "culture",
    "arts": "culture",
    "media": "culture",
    "sport": "sports",
    "education": "lifestyle",
    "travel": "lifestyle",
    "food": "lifestyle",
}


@dataclass(frozen=True)
class Feed:
    outlet: str
    url: str


FEEDS: tuple[Feed, ...] = (
    Feed("BBC", "https://feeds.bbci.co.uk/news/world/rss.xml"),
    Feed("BBC", "https://feeds.bbci.co.uk/news/business/rss.xml"),
    Feed("BBC", "https://feeds.bbci.co.uk/news/technology/rss.xml"),
    Feed("BBC", "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml"),
    Feed("BBC", "https://feeds.bbci.co.uk/news/health/rss.xml"),
    Feed("BBC", "https://feeds.bbci.co.uk/news/entertainment_and_arts/rss.xml"),
    Feed("BBC", "https://feeds.bbci.co.uk/sport/rss.xml"),
    Feed("The Guardian", "https://www.theguardian.com/world/rss"),
    Feed("The Guardian", "https://www.theguardian.com/technology/rss"),
    Feed("The Guardian", "https://www.theguardian.com/environment/rss"),
    Feed("The Guardian", "https://www.theguardian.com/culture/rss"),
    Feed("The Guardian", "https://www.theguardian.com/lifeandstyle/rss"),
    Feed("NPR", "https://feeds.npr.org/1001/rss.xml"),
    Feed("The New York Times", "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml"),
    Feed("Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml"),
    Feed("DW", "https://rss.dw.com/rdf/rss-en-all"),
    Feed("Google News", "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en"),
    Feed("Hacker News", "https://hnrss.org/frontpage"),
    Feed("Ars Technica", "https://feeds.arstechnica.com/arstechnica/index"),
    Feed("The Verge", "https://www.theverge.com/rss/index.xml"),
    Feed("ScienceDaily", "https://www.sciencedaily.com/rss/top.xml"),
)

# Stems that keep a headline (and a generated topic) off the site whatever its context. Strict
# on purpose: a few lost legitimate stories are cheap, one porn or gore topic on the site is not.
_BLOCKED_STEMS = (
    # sexual content
    r"porn\w*",
    r"sex(?:ual\w*|ting|tortion)?\b",
    r"rap(?:e|es|ed|ist|ists|ing)\b",
    r"incest\w*",
    r"nud(?:e|es|ity|ify|ifying|ification|ist|ists)\b",
    r"naked\b",
    r"erotic\w*",
    r"onlyfans\b",
    r"prostitut\w*",
    r"brothels?\b",
    r"pa?edo(?:phil\w*|s)?\b",
    r"groom(?:ing|ed)\b",
    r"molest\w*",
    r"fetish\w*",
    r"bdsm\b",
    r"kinky\b",
    r"strangl\w*",
    r"masturbat\w*",
    r"genital\w*",
    r"orgasm\w*",
    r"(?:explicit|intimate) (?:images?|photos?|pictures?|videos?|content)",
    r"child abuse\w*",
    # violence, gore and tragedies
    r"murder\w*",
    r"kill(?:ed|ing|ings|er|ers)\b",
    r"stab(?:bed|bing|bings)\b",
    r"shootings?\b",
    r"shot dead\b",
    r"gun(?:man|men)\b",
    r"massacre\w*",
    r"behead\w*",
    r"decapitat\w*",
    r"dismember\w*",
    r"mutilat\w*",
    r"tortur\w*",
    r"gory\b",
    r"gruesome\b",
    r"graphic (?:videos?|images?|footage|content|scenes?)",
    r"corpses?\b",
    r"dead bod(?:y|ies)\b",
    r"bodies (?:found|recovered)\b",
    r"mass graves?\b",
    r"lynch\w*",
    r"terrorists?\b",
    r"terror attacks?\b",
    r"suicid\w*",
    r"self[- ]harm\w*",
    r"overdos\w*",
    r"genocid\w*",
    r"ethnic cleansing\b",
    r"atrocit\w*",
)
BLOCKED_TERMS = re.compile(r"\b(?:" + "|".join(_BLOCKED_STEMS) + ")", re.IGNORECASE)

# Shared by the generation prompt and the review call.
SAFETY_RULES = (
    "sexual content of any kind (pornography and its regulation, sexual abuse or harassment, "
    "nudity, intimate or 'nudify' images, sex work); violence or gore (killings, shootings, "
    "stabbings, torture, executions, terrorist attacks, war casualties); deaths, disasters, "
    "accidents or other tragedies; suicide or self-harm; abuse of children; crimes of a named "
    "person; real private individuals; hatred of a group of people"
)

SYSTEM = (
    "You are the editor of Debatr, a site where AI models debate a motion on camera. You turn "
    "today's news into debate topics for a general audience."
)

TOPIC_RULES = """Rules for every topic:
- question: a crisp debate motion with two reasonable sides (usually "Should ...?" or "Is ...?"), 6-15 words and at most 100 characters, understandable without reading the news. Generalise the story into the argument it raises instead of asking about details of one event.
- brief: 2-3 neutral sentences on what happened and when (the debaters are AI models that do not know recent news). No opinions.
- label: a 1-4 word chip title.
- category: one of {categories}.
- heat: 1-10, how widely discussed the story is and how good it is for a lively debate. Small, local or routine stories (a product review, a lifestyle tip, one company's quarterly numbers) get a low heat.
- sources: the numbers of the headlines about this story (at least one).
- One topic per story: merge headlines about the same story. Spread the topics over the categories when the news allows.
- Never make a topic about {safety}. Skip such headlines entirely. When in doubt, leave it out."""

TOPICS_JSON_SPEC = (
    '{"topics": [{"label": "...", "question": "...", "brief": "...", "category": "...", '
    '"heat": 7, "sources": [3, 17]}]}'
)

REVIEW_JSON_SPEC = '{"reject": [{"id": <topic number>, "reason": "<short reason>"}]}'


class TrendingError(Exception):
    """A refresh that produced nothing worth saving (feeds down, unusable model reply)."""


@dataclass
class Headline:
    outlet: str
    title: str
    summary: str
    url: str
    published_at: datetime | None = None

    def source(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "url": self.url,
            "outlet": self.outlet,
            "published_at": self.published_at.isoformat() if self.published_at else None,
        }


@dataclass
class TopicDraft:
    label: str
    question: str
    brief: str
    category: str
    heat: int
    sources: list[Headline]

    @property
    def outlets(self) -> int:
        return len({s.outlet for s in self.sources})

    @property
    def score(self) -> float:
        return self.heat + OUTLET_BONUS * min(self.outlets - 1, 3)


@dataclass
class BatchResult:
    model: str
    topics: list[TopicDraft]
    cost_usd: float
    stats: dict[str, Any] = field(default_factory=dict)


# --- headlines ----------------------------------------------------------------------------


def clean_text(text: str) -> str:
    """Plain one-line text from feed HTML."""
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def blocked_term(*texts: str) -> str | None:
    """The first blocked term found in the texts, if any."""
    for text in texts:
        match = BLOCKED_TERMS.search(text or "")
        if match:
            return match.group(0).lower()
    return None


def _entry_time(entry: Any) -> datetime | None:
    stamp = entry.get("published_parsed") or entry.get("updated_parsed")
    if not stamp:
        return None
    try:
        return datetime(*stamp[:6], tzinfo=UTC)
    except (TypeError, ValueError):
        return None


def parse_feed(content: bytes, outlet: str, *, now: datetime) -> list[Headline]:
    """Fresh headlines of one feed, newest first as the feed lists them. Google News items name
    their real outlet in <source>."""
    cutoff = now - timedelta(hours=MAX_AGE_HOURS)
    items: list[Headline] = []
    for entry in feedparser.parse(content).entries:
        published = _entry_time(entry)
        if published and published < cutoff:
            continue
        title = clean_text(str(entry.get("title") or ""))
        url = str(entry.get("link") or "").strip()
        if not title or not re.match(r"https?://", url, re.IGNORECASE):
            continue
        source = entry.get("source") or {}
        real_outlet = clean_text(str(source.get("title") or "")) if source else ""
        if real_outlet:
            # "Headline - Reuters" -> "Headline"
            title = re.sub(rf"\s+[-\u2013|]\s+{re.escape(real_outlet)}$", "", title)
        # Google News summaries are lists of links to other outlets, not text.
        summary = "" if real_outlet else clean_text(str(entry.get("summary") or ""))
        items.append(
            Headline(
                outlet=real_outlet or outlet,
                title=title[:300],
                summary=summary[:300],
                url=url[:1000],
                published_at=published,
            )
        )
    return items


def fetch_feeds(feeds: tuple[Feed, ...] = FEEDS) -> list[list[Headline]]:
    """Fresh headlines per feed (an empty list for a feed that failed)."""
    now = datetime.now(UTC)
    headers = {"User-Agent": f"Debatr/1.0 ({settings.SITE_URL}; trending topics)"}

    with httpx.Client(headers=headers, timeout=FEED_TIMEOUT, follow_redirects=True) as client:

        def fetch(feed: Feed) -> list[Headline]:
            try:
                response = client.get(feed.url)
                response.raise_for_status()
                return parse_feed(response.content, feed.outlet, now=now)
            except Exception as exc:  # one broken feed must not stop the batch
                logger.warning("Trending feed %s failed: %s", feed.url, exc)
                return []

        with ThreadPoolExecutor(max_workers=8) as pool:
            return list(pool.map(fetch, feeds))


def _title_key(title: str) -> str:
    return re.sub(r"\W+", " ", title.lower()).strip()


def balanced_pool(groups: list[list[Headline]], limit: int) -> list[Headline]:
    """Round-robin over the feeds (each feed's top items first), without repeated titles."""
    seen: set[str] = set()
    pool: list[Headline] = []
    for rank in range(max((len(g) for g in groups), default=0)):
        for group in groups:
            if len(pool) >= limit:
                return pool
            if rank < len(group):
                key = _title_key(group[rank].title)
                if key and key not in seen:
                    seen.add(key)
                    pool.append(group[rank])
    return pool


def pool_size(topic_count: int) -> int:
    return min(MAX_POOL, max(MIN_POOL, topic_count * 3))


# --- the model ----------------------------------------------------------------------------


def build_topic_messages(pool: list[Headline], wanted: int, *, today: str) -> list[dict[str, str]]:
    lines = []
    for i, item in enumerate(pool, 1):
        date = item.published_at.strftime("%Y-%m-%d") if item.published_at else "recent"
        summary = f" - {item.summary}" if item.summary else ""
        lines.append(f"[{i}] {item.outlet} · {date} · {item.title}{summary}")
    rules = TOPIC_RULES.format(categories=", ".join(TOPIC_CATEGORIES), safety=SAFETY_RULES)
    user = (
        f"Today is {today}. Below are {len(pool)} news headlines from the last {MAX_AGE_HOURS} "
        f"hours. Pick the {wanted} most compelling distinct stories and turn each into a debate "
        f"topic, best first.\n\n{rules}\n\nReply with JSON only: {TOPICS_JSON_SPEC}\n\n"
        "Headlines:\n" + "\n".join(lines)
    )
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]


def _json_object(text: str) -> dict[str, Any]:
    """The JSON object in a reply. A reply cut off by the token limit keeps its complete
    topics: the text is closed after the last complete object."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    text = re.sub(r"```(?:json)?", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise TrendingError("no JSON object in the reply")
    body = text[start : end + 1]
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        data = None
        closes = [m.start() for m in re.finditer("}", body)]
        for pos in reversed(closes[-300:]):
            try:
                data = json.loads(body[: pos + 1] + "]}")
                break
            except json.JSONDecodeError:
                continue
    if not isinstance(data, dict):
        raise TrendingError("the reply is not a JSON object")
    return data


def normalize_category(value: Any) -> str:
    raw = re.sub(r"[^a-z]", "", str(value or "").lower())
    if raw in TOPIC_CATEGORIES:
        return raw
    return CATEGORY_ALIASES.get(raw, "world")


def _clip(text: Any, limit: int) -> str:
    value = clean_text(str(text or "")).strip("\"' ")
    if len(value) <= limit:
        return value
    return value[:limit].rsplit(" ", 1)[0].rstrip(",;:") + "…"


def _heat(value: Any) -> int:
    try:
        return max(1, min(10, round(float(value))))
    except (TypeError, ValueError):
        return 5


def parse_topics(text: str, pool: list[Headline]) -> tuple[list[TopicDraft], list[dict[str, str]]]:
    """Topics from the model's reply plus the dropped ones with reasons. A topic must cite at
    least one headline of the pool (no invented stories) and pass the blocklist."""
    raw = _json_object(text).get("topics")
    if not isinstance(raw, list):
        raise TrendingError("the reply has no topics list")
    topics: list[TopicDraft] = []
    dropped: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        question = _clip(item.get("question"), 300)
        if len(question) < 10:
            continue
        label = _clip(item.get("label"), 80) or " ".join(question.split()[:4])
        brief = _clip(item.get("brief"), 1000)
        sources: list[Headline] = []
        for ref in item.get("sources") or []:
            digits = str(ref).strip("[] ")
            if digits.isdigit() and 0 < int(digits) <= len(pool):
                headline = pool[int(digits) - 1]
                if headline not in sources:
                    sources.append(headline)
        key = _title_key(question)
        if not sources:
            reason = "no source headline"
        elif term := blocked_term(question, label, brief):
            reason = f"blocked term: {term}"
        elif key in seen:
            reason = "duplicate"
        else:
            reason = ""
        if reason:
            dropped.append({"question": question, "reason": reason})
            continue
        seen.add(key)
        topics.append(
            TopicDraft(
                label=label,
                question=question,
                brief=brief,
                category=normalize_category(item.get("category")),
                heat=_heat(item.get("heat")),
                sources=sources,
            )
        )
    return topics, dropped


def rank_topics(topics: list[TopicDraft]) -> list[TopicDraft]:
    """Hottest first: the model's heat plus a bonus per extra outlet carrying the story."""
    order = {id(t): i for i, t in enumerate(topics)}
    return sorted(topics, key=lambda t: (-t.score, -t.heat, order[id(t)]))


def drop_same_story(
    ranked: list[TopicDraft],
) -> tuple[list[TopicDraft], list[dict[str, str]]]:
    """One topic per story: a topic citing an article that a higher-ranked topic already cites
    is the same story told again (models sometimes split one story into several motions)."""
    kept: list[TopicDraft] = []
    dropped: list[dict[str, str]] = []
    owner: dict[str, TopicDraft] = {}
    for topic in ranked:
        first = next((owner[s.url] for s in topic.sources if s.url in owner), None)
        if first is not None:
            dropped.append(
                {"question": topic.question, "reason": f"same story as: {first.question}"}
            )
            continue
        kept.append(topic)
        owner.update({s.url: topic for s in topic.sources})
    return kept, dropped


def build_review_messages(topics: list[TopicDraft]) -> list[dict[str, str]]:
    system = (
        "You are a strict content moderator for the front page of a debate site for a general "
        "audience aged 13 and up. Reply with a single JSON object and nothing else."
    )
    lines = [f"[{i}] {t.label} | {t.question} | {t.brief}" for i, t in enumerate(topics, 1)]
    user = (
        "JOB: decide which of these debate topics must NOT be shown on the site. Reject a topic "
        f"if its label, question or brief touches: {SAFETY_RULES}. Controversial political, "
        "economic or social questions argued in general terms are fine. When in doubt, reject."
        f"\n\nTopics:\n" + "\n".join(lines) + f"\n\nReturn JSON: {REVIEW_JSON_SPEC} "
        "(an empty list when every topic is fine)."
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def parse_review(text: str, count: int) -> dict[int, str]:
    """{topic index (0-based): reason} to reject. Raises TrendingError on an unusable reply, so
    an unreviewed batch is never saved."""
    reject = _json_object(text).get("reject")
    if not isinstance(reject, list):
        raise TrendingError("the review has no reject list")
    result: dict[int, str] = {}
    for item in reject:
        ref = item.get("id") if isinstance(item, dict) else item
        digits = str(ref).strip("[] ")
        if digits.isdigit() and 0 < int(digits) <= count:
            reason = str(item.get("reason") or "") if isinstance(item, dict) else ""
            result[int(digits) - 1] = reason[:200] or "rejected by the review"
    return result


def _cost(usage: dict[str, Any]) -> float:
    try:
        return float(usage.get("cost") or 0)
    except (TypeError, ValueError):
        return 0.0


def build_batch(model: str, topic_count: int) -> BatchResult:
    """Fetch, filter, generate, rank and review one batch (nothing is saved here)."""
    groups = fetch_feeds()
    feeds_ok = sum(1 for g in groups if g)
    if not feeds_ok:
        raise TrendingError("every feed failed")
    blocked: list[dict[str, str]] = []
    allowed: list[list[Headline]] = []
    for group in groups:
        kept_headlines: list[Headline] = []
        for headline in group:
            if term := blocked_term(headline.title, headline.summary):
                blocked.append({"title": headline.title, "term": term})
            else:
                kept_headlines.append(headline)
        allowed.append(kept_headlines)
    pool = balanced_pool(allowed, pool_size(topic_count))
    if not pool:
        raise TrendingError("no usable headlines")

    wanted = min(len(pool), math.ceil(topic_count * EXTRA_TOPICS))
    today = datetime.now(UTC).strftime("%A, %d %B %Y")
    text, _, usage = llm.complete_message(
        model,
        build_topic_messages(pool, wanted, today=today),
        max_tokens=min(64000, 4000 + wanted * 400),
        read_timeout=GENERATE_TIMEOUT,
    )
    cost = _cost(usage)
    topics, dropped = parse_topics(text, pool)
    topics, repeats = drop_same_story(rank_topics(topics))
    dropped += repeats
    topics = topics[: max(topic_count, 1) + 10]  # a few spares for the review
    if not topics:
        raise TrendingError("the model returned no usable topics")

    review_text, _, review_usage = llm.complete_message(
        model, build_review_messages(topics), max_tokens=8000, read_timeout=GENERATE_TIMEOUT
    )
    cost += _cost(review_usage)
    rejected = parse_review(review_text, len(topics))
    dropped += [{"question": topics[i].question, "reason": r} for i, r in rejected.items()]
    kept = [t for i, t in enumerate(topics) if i not in rejected][:topic_count]
    if not kept:
        raise TrendingError("the review rejected every topic")

    stats = {
        "feeds_ok": feeds_ok,
        "feeds_total": len(groups),
        "headlines_fresh": sum(len(g) for g in groups),
        "headlines_blocked": len(blocked),
        "blocked": blocked[:200],  # to spot false positives of the blocklist
        "headlines_sent": len(pool),
        "topics_asked": wanted,
        "dropped": dropped,
    }
    return BatchResult(model=model, topics=kept, cost_usd=cost, stats=stats)


# --- storage and scheduling ---------------------------------------------------------------


def save_batch(db: Session, result: BatchResult) -> TrendingBatch:
    batch = TrendingBatch(
        model=result.model,
        topic_count=len(result.topics),
        cost_usd=Decimal(str(round(result.cost_usd, 6))),
        stats_json=result.stats,
    )
    batch.topics = [
        TrendingTopic(
            rank=rank,
            label=t.label,
            question=t.question,
            brief=t.brief,
            category=t.category,
            heat=t.heat,
            outlets=t.outlets,
            sources_json=[s.source() for s in t.sources],
        )
        for rank, t in enumerate(result.topics, 1)
    ]
    db.add(batch)
    return batch


def latest_batch_time(db: Session) -> datetime | None:
    stmt = select(TrendingBatch.created_at).order_by(TrendingBatch.created_at.desc()).limit(1)
    return db.execute(stmt).scalar_one_or_none()


def is_due(latest: datetime | None, now: datetime, hours: int) -> bool:
    """Whether a new batch should be built: none yet, or the newest one is `hours` old (0 turns
    automatic refreshes off)."""
    if hours <= 0:
        return False
    if latest is None:
        return True
    return now - latest >= timedelta(hours=hours) - REFRESH_SLACK


def refresh_trending_job(force: bool = False) -> None:
    """RQ job: build and save a new batch when one is due (`force`: now, from the admin)."""
    if not settings.OPENROUTER_API_KEY or not settings.TRENDING_MODEL:
        logger.info("Trending topics are off: no OPENROUTER_API_KEY or TRENDING_MODEL")
        return
    if not force:
        with get_sync_session() as db:
            latest = latest_batch_time(db)
        if not is_due(latest, utcnow(), settings.TRENDING_REFRESH_HOURS):
            return
    redis = get_sync_redis()
    if not redis.set(trending_lock_key(), "1", nx=True, ex=LOCK_TTL):
        logger.info("A trending refresh is already running")
        return
    try:
        result = build_batch(settings.TRENDING_MODEL, settings.TRENDING_TOPIC_COUNT)
        with get_sync_session() as db:
            save_batch(db, result)
            db.commit()
        logger.info(
            "Trending batch saved: %d topics, %d dropped, $%.4f",
            len(result.topics),
            len(result.stats.get("dropped", [])),
            result.cost_usd,
        )
    except (TrendingError, OpenRouterError) as exc:
        logger.warning("Trending refresh failed, keeping the previous batch: %s", exc)
    finally:
        redis.delete(trending_lock_key())
