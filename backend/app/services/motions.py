"""Topics (motions): every debate is a version of one.

Versions are grouped only by reliable signals: the same topic after `normalize_topic` (a trending
topic and the wizard's "Use this wording" put the text in word for word, a remix copies it), and
a remix in another language, which stays in its parent's topic (a translation). Nothing guesses
by meaning: a wrong merge would show on every card, a missed one is just two cards. Admins move a
version to another topic, split it off or merge two topics in the console.

A topic stores no counters. What the gallery shows — the public versions, the cover, the title
(the first public version's text) — is computed from the public debates, so no path that
publishes, hides or deletes a debate has to remember to update its topic. The slug is random:
the key may come from a private debate's text.
"""

import re
import unicodedata
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal
from urllib.parse import urlparse

from sqlalchemy import ColumnElement, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.ids import new_slug
from app.models.models import Debate, DebateParticipant, Motion, utcnow

KEY_MAX = 600
_NOT_WORD = re.compile(r"[\W_]+")

VERSIONS_SHOWN = 12  # versions listed on a debate page; the topic page lists them all
MODELS_SHOWN = 8  # model logos of a topic's versions on a gallery card
# Similar topics for the wizard: pg_trgm similarity of the normalized texts.
SIMILAR_MIN = 0.35
SIMILAR_LIMIT = 3
SUGGEST_MIN_KEY = 4  # shorter texts match everything


def normalize_topic(topic: str) -> str:
    """The topic text that versions share: case, punctuation, quotes and spacing do not count.
    The migration that grouped the first debates (0014) keeps a frozen copy."""
    text = unicodedata.normalize("NFKC", topic).casefold()
    return _NOT_WORD.sub(" ", text).strip()[:KEY_MAX]


def joins_parent(topic: str, language: str, parent_topic: str, parent_language: str) -> bool:
    """A remix stays in its parent's topic when it asks the same question, or asks it in
    another language (a translation reads differently but is the same topic)."""
    if normalize_topic(topic) == normalize_topic(parent_topic):
        return True
    return language.strip().casefold() != parent_language.strip().casefold()


def public_clause() -> list[ColumnElement[bool]]:
    """Debates the gallery shows (published, with a share slug)."""
    return [Debate.is_public.is_(True), Debate.slug.is_not(None)]


def topic_text(debate: Debate) -> str:
    return str((debate.config_json or {}).get("topic") or debate.title or "")


def language_of(debate: Debate) -> str:
    return str((debate.config_json or {}).get("language") or "English")


# --- assigning ------------------------------------------------------------------------------------


async def resolve(db: AsyncSession, motion_id: uuid.UUID) -> uuid.UUID:
    """The topic a (possibly merged) topic stands for now."""
    current = motion_id
    for _ in range(5):  # merges are flattened, so one hop is the rule
        merged = await db.scalar(select(Motion.merged_into_id).where(Motion.id == current))
        if merged is None:
            return current
        current = merged
    return current


async def new_motion(db: AsyncSession, key: str | None = None) -> uuid.UUID:
    motion = Motion(id=uuid.uuid4(), slug=new_slug(), key=key or None, created_at=utcnow())
    db.add(motion)
    await db.flush()
    return motion.id


async def motion_for_key(db: AsyncSession, key: str, *, create: bool) -> uuid.UUID | None:
    """The topic of a normalized text; with `create`, a new one when there is none (a text that
    normalizes to nothing gets a topic of its own)."""
    if not key:
        return await new_motion(db) if create else None
    found = (
        await db.execute(select(Motion.id, Motion.merged_into_id).where(Motion.key == key))
    ).first()
    if found is not None:
        return found.merged_into_id or found.id
    if not create:
        return None
    # Two requests may create the same topic at once: the second insert does nothing and reads
    # the first one's row.
    created = await db.scalar(
        insert(Motion)
        .values(id=uuid.uuid4(), slug=new_slug(), key=key, created_at=utcnow())
        .on_conflict_do_nothing(index_elements=[Motion.key])
        .returning(Motion.id)
    )
    if created is not None:
        return created
    return await motion_for_key(db, key, create=False)


async def assign_motion(
    db: AsyncSession, debate: Debate, topic: str, language: str, parent: Debate | None
) -> None:
    """Make `debate` a version of its topic. `parent`: the debate it was remixed from, when the
    user may see it (the caller checks)."""
    if (
        parent is not None
        and parent.motion_id is not None
        and joins_parent(topic, language, topic_text(parent), language_of(parent))
    ):
        debate.motion_id = await resolve(db, parent.motion_id)
        return
    debate.motion_id = await motion_for_key(db, normalize_topic(topic), create=True)


# --- reading --------------------------------------------------------------------------------------


@dataclass
class MotionInfo:
    """A topic as the gallery sees it: its public versions only."""

    id: uuid.UUID
    slug: str
    title: str
    versions: int
    models: list[str] = field(default_factory=list)  # debater models across the versions


async def motion_infos(
    db: AsyncSession, motion_ids: Iterable[uuid.UUID | None]
) -> dict[uuid.UUID, MotionInfo]:
    """Topics with at least one public version (others are left out: they do not exist for the
    gallery). Three small queries, for a whole gallery page at once."""
    ids = {m for m in motion_ids if m is not None}
    if not ids:
        return {}
    versions = (
        await db.execute(
            select(Debate.id, Debate.motion_id, Debate.title, Debate.config_json)
            .where(Debate.motion_id.in_(ids), *public_clause())
            .order_by(func.coalesce(Debate.published_at, Debate.created_at), Debate.created_at)
        )
    ).all()
    if not versions:
        return {}
    slugs = dict((await db.execute(select(Motion.id, Motion.slug).where(Motion.id.in_(ids)))).all())
    models_of: dict[uuid.UUID, list[str]] = {}
    rows = await db.execute(
        select(DebateParticipant.debate_id, DebateParticipant.model_id)
        .where(
            DebateParticipant.debate_id.in_([v.id for v in versions]),
            DebateParticipant.role == "debater",
        )
        .order_by(DebateParticipant.id)
    )
    for debate_id, model_id in rows.all():
        models_of.setdefault(debate_id, []).append(model_id)

    out: dict[uuid.UUID, MotionInfo] = {}
    for v in versions:
        info = out.get(v.motion_id)
        if info is None:
            title = str((v.config_json or {}).get("topic") or v.title or "")
            info = out[v.motion_id] = MotionInfo(v.motion_id, slugs.get(v.motion_id, ""), title, 0)
        info.versions += 1
        for model in models_of.get(v.id, []):
            if model not in info.models and len(info.models) < MODELS_SHOWN:
                info.models.append(model)
    return out


async def public_versions(
    db: AsyncSession, motion_id: uuid.UUID, *, limit: int | None = None
) -> Sequence[Debate]:
    """A topic's public versions, most liked first (the debate page and the topic page)."""
    query = (
        select(Debate)
        .options(selectinload(Debate.participants), selectinload(Debate.user))
        .where(Debate.motion_id == motion_id, *public_clause())
        .order_by(
            Debate.likes_count.desc(),
            Debate.votes_count.desc(),
            Debate.views.desc(),
            func.coalesce(Debate.published_at, Debate.created_at).desc(),
        )
    )
    if limit is not None:
        query = query.limit(limit)
    return (await db.scalars(query)).all()


async def motion_by_slug(db: AsyncSession, slug: str) -> Motion | None:
    """The topic behind a slug; a merged topic's slug leads to the topic it went into."""
    motion = await db.scalar(select(Motion).where(Motion.slug == slug))
    if motion is None or motion.merged_into_id is None:
        return motion
    return await db.get(Motion, await resolve(db, motion.id))


@dataclass
class Suggestions:
    match: MotionInfo | None  # the topic this text would join (only one with public versions)
    similar: list[MotionInfo]


async def suggest(
    db: AsyncSession, topic: str, language: str, parent: Debate | None
) -> Suggestions:
    """For the wizard: the topic a debate with this text would join, and similar topics whose
    wording the user may take. Only topics with public versions: private ones stay unknown."""
    key = normalize_topic(topic)
    match_id: uuid.UUID | None = None
    if (
        parent is not None
        and parent.motion_id is not None
        and joins_parent(topic, language, topic_text(parent), language_of(parent))
    ):
        match_id = await resolve(db, parent.motion_id)
    if match_id is None and key:
        match_id = await motion_for_key(db, key, create=False)

    similar_ids: list[uuid.UUID] = []
    if len(key) >= SUGGEST_MIN_KEY:
        similarity = func.similarity(Motion.key, key)
        rows = await db.execute(
            select(func.coalesce(Motion.merged_into_id, Motion.id), similarity)
            .where(Motion.key.is_not(None), Motion.key.op("%")(key), similarity >= SIMILAR_MIN)
            .order_by(similarity.desc())
            .limit(20)
        )
        for motion_id, _score in rows.all():
            if motion_id != match_id and motion_id not in similar_ids:
                similar_ids.append(motion_id)

    infos = await motion_infos(db, [match_id, *similar_ids])
    similar = [infos[m] for m in similar_ids if m in infos][:SIMILAR_LIMIT]
    return Suggestions(match=infos.get(match_id) if match_id else None, similar=similar)


# --- admin: moving versions -------------------------------------------------------------------------


TargetKind = Literal["debate_id", "debate_slug", "motion_slug", "slug"]


def parse_target(raw: str) -> tuple[TargetKind, str] | None:
    """What an admin pasted to name a topic: a topic link (/t/…), a debate link (/d/…,
    /debate/…, /admin/debates/…), a debate id or a bare slug (topic first, then debate)."""
    text = raw.strip()
    if not text:
        return None
    try:
        return "debate_id", str(uuid.UUID(text))
    except ValueError:
        pass
    path = urlparse(text).path if "://" in text else text
    parts = [p for p in path.split("/") if p]
    if not parts:
        return None
    if len(parts) >= 2:
        kind, value = parts[-2], parts[-1]
        if kind == "t":
            return "motion_slug", value
        if kind == "d":
            return "debate_slug", value
        if kind in ("debate", "debates"):
            try:
                return "debate_id", str(uuid.UUID(value))
            except ValueError:
                return None
        return None
    return "slug", parts[0]


async def find_target(db: AsyncSession, raw: str) -> uuid.UUID | None:
    """The topic an admin named (see `parse_target`), resolved through merges."""
    parsed = parse_target(raw)
    if parsed is None:
        return None
    kind, value = parsed
    motion_id: Any = None
    if kind == "debate_id":
        motion_id = await db.scalar(select(Debate.motion_id).where(Debate.id == uuid.UUID(value)))
    elif kind == "debate_slug":
        motion_id = await db.scalar(select(Debate.motion_id).where(Debate.slug == value))
    else:
        motion_id = await db.scalar(select(Motion.id).where(Motion.slug == value))
        if motion_id is None and kind == "slug":
            motion_id = await db.scalar(select(Debate.motion_id).where(Debate.slug == value))
    return await resolve(db, motion_id) if motion_id is not None else None


async def merge_motions(db: AsyncSession, source: uuid.UUID, target: uuid.UUID) -> int:
    """Move every version of `source` into `target`; `source`'s text and slug lead to `target`
    from now on. Returns the number of debates moved."""
    moved = await db.execute(
        update(Debate).where(Debate.motion_id == source).values(motion_id=target)
    )
    # Keep merges one hop deep: topics merged into `source` now point at `target` directly.
    await db.execute(
        update(Motion).where(Motion.merged_into_id == source).values(merged_into_id=target)
    )
    await db.execute(update(Motion).where(Motion.id == source).values(merged_into_id=target))
    return int(getattr(moved, "rowcount", 0) or 0)


async def motion_summary(db: AsyncSession, motion_id: uuid.UUID | None) -> dict[str, Any] | None:
    """The admin card's topic block: slug, title (the first public version), how many debates it
    holds, public and in all, and its page on the site while it has a public version."""
    if motion_id is None:
        return None
    motion = await db.get(Motion, motion_id)
    if motion is None:
        return None
    total = await db.scalar(select(func.count(Debate.id)).where(Debate.motion_id == motion_id))
    info = (await motion_infos(db, [motion_id])).get(motion_id)
    return {
        "slug": motion.slug,
        "title": info.title if info else None,
        "public_versions": info.versions if info else 0,
        "debates": int(total or 0),
        "url": f"{settings.SITE_URL.rstrip('/')}/t/{motion.slug}" if info else None,
    }
