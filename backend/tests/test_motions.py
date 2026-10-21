"""Topics (services/motions): which debates are versions of one topic, the gallery's grouped
query, the version strip and the console's move / merge. Pure: queries are compiled, not run;
the database parts are replaced by small fakes.
"""

import importlib.util
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql
from starlette.requests import Request

from app.admin.access import AdminContext
from app.api import routes_gallery, serializers
from app.api.admin import routes_debates as admin_routes
from app.models.models import AdminAuditLog, Debate, DebateParticipant, User
from app.schemas.admin import MotionMoveRequest
from app.schemas.schemas import DebateConfig
from app.services import motions, ranking
from app.services.admin.sessions import AdminSession
from app.services.media.languages import LANGUAGE_CODES, language_code
from app.services.motions import MotionInfo, joins_parent, normalize_topic, parse_target

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)


def _sql(statement: Any) -> str:
    return str(
        statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )


def _debate(**fields: Any) -> Debate:
    defaults: dict[str, Any] = {
        "id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "status": "completed",
        "title": "Tabs or spaces?",
        "config_json": {"topic": "Tabs or spaces?", "language": "English"},
        "is_public": False,
        "slug": None,
        "motion_id": None,
        "remix_of_id": None,
        "views": 0,
        "likes_count": 0,
        "votes_count": 0,
        "media_status": "none",
        "media_json": {},
        "published_at": None,
        "participants": [],
        "user": None,
    }
    return Debate(**{**defaults, **fields})


# --- grouping rules ---------------------------------------------------------------------------


def test_normalized_text_ignores_case_punctuation_and_spacing() -> None:
    key = normalize_topic("Is AI dangerous?")
    assert key == "is ai dangerous"
    for same in (
        "is ai dangerous",
        "  IS AI — DANGEROUS!!",
        "«Is AI dangerous»?",
        "Is_AI dangerous",
    ):
        assert normalize_topic(same) == key
    assert normalize_topic("Is AI dangerous for jobs?") != key
    # NFKC folds look-alike forms (full-width letters), casefold handles other scripts.
    assert normalize_topic("\uff29\uff53 \uff21\uff29 dangerous") == key
    assert normalize_topic("Опасен ли ИИ?") == "опасен ли ии"
    assert normalize_topic("Straße") == normalize_topic("STRASSE")
    assert normalize_topic("?!…") == ""
    assert len(normalize_topic("word " * 400)) <= motions.KEY_MAX


def test_the_migration_grouped_with_the_same_rule() -> None:
    """0014 keeps a frozen copy of the rule. If this fails, normalize_topic changed: existing
    keys were made with the old rule and need a migration that re-keys them."""
    path = Path(__file__).parents[1] / "migrations" / "versions" / "000000000014_motions.py"
    spec = importlib.util.spec_from_file_location("migration_0014", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for text in (
        "Is AI dangerous?",
        "  Tabs — or SPACES?!",
        "Опасен ли ИИ?",
        "\uff29\uff53 \uff21\uff29",
        "a_b-c",
    ):
        assert module._normalize(text) == normalize_topic(text)


def test_a_remix_joins_its_parent_when_it_asks_the_same_or_translates() -> None:
    assert joins_parent("Is AI dangerous!", "English", "is ai dangerous?", "English")
    # A translation reads differently but is the same topic.
    assert joins_parent("Опасен ли ИИ?", "Russian", "Is AI dangerous?", "English")
    assert joins_parent("Опасен ли ИИ?", "russian", "Is AI dangerous?", "English")
    # Another question in the same language is a new topic, remix or not.
    assert not joins_parent("Is AI dangerous for jobs?", "English", "Is AI dangerous?", "english")


class _Ids:
    def __init__(self) -> None:
        self.parent_topic = uuid.uuid4()
        self.merged_into = uuid.uuid4()
        self.by_key = uuid.uuid4()
        self.keys: list[str] = []


@pytest.fixture
def ids(monkeypatch: pytest.MonkeyPatch) -> _Ids:
    ids = _Ids()

    async def resolve(_db: Any, motion_id: uuid.UUID) -> uuid.UUID:
        return ids.merged_into if motion_id == ids.parent_topic else motion_id

    async def motion_for_key(_db: Any, key: str, *, create: bool) -> uuid.UUID:
        assert create
        ids.keys.append(key)
        return ids.by_key

    monkeypatch.setattr(motions, "resolve", resolve)
    monkeypatch.setattr(motions, "motion_for_key", motion_for_key)
    return ids


async def test_assign_prefers_the_parents_topic_through_merges(ids: _Ids) -> None:
    parent = _debate(motion_id=ids.parent_topic)
    debate = _debate()
    await motions.assign_motion(None, debate, "TABS or spaces", "English", parent)  # type: ignore[arg-type]
    assert debate.motion_id == ids.merged_into and ids.keys == []
    translated = _debate()
    await motions.assign_motion(None, translated, "Табы или пробелы?", "Russian", parent)  # type: ignore[arg-type]
    assert translated.motion_id == ids.merged_into


async def test_assign_falls_back_to_the_text(ids: _Ids) -> None:
    parent = _debate(motion_id=ids.parent_topic)
    other = _debate()
    await motions.assign_motion(None, other, "Tabs or spaces in 2030?", "English", parent)  # type: ignore[arg-type]
    assert other.motion_id == ids.by_key and ids.keys == ["tabs or spaces in 2030"]
    plain = _debate()
    await motions.assign_motion(None, plain, "Tabs or spaces?", "English", None)  # type: ignore[arg-type]
    assert plain.motion_id == ids.by_key and ids.keys[-1] == "tabs or spaces"
    # A parent without a topic (a row from before topics) counts as no parent.
    orphan_parent = _debate(motion_id=None)
    late = _debate()
    await motions.assign_motion(None, late, "Tabs or spaces?", "Russian", orphan_parent)  # type: ignore[arg-type]
    assert late.motion_id == ids.by_key


def test_remix_of_is_never_stored_in_the_config() -> None:
    config = DebateConfig.model_validate(
        {
            "topic": "Tabs or spaces?",
            "participants": [{"role": "debater", "model_id": "a/b", "display_name": "A"}],
            "remix_of": str(uuid.uuid4()),
        }
    )
    assert "remix_of" not in config.persisted()


# --- admin: naming a topic ----------------------------------------------------------------------


def test_admins_name_a_topic_by_link_id_or_slug() -> None:
    debate_id = str(uuid.uuid4())
    assert parse_target(debate_id) == ("debate_id", debate_id)
    assert parse_target(f"  {debate_id.upper()} ") == ("debate_id", debate_id)
    assert parse_target("https://ai-debates.net/t/abc234") == ("motion_slug", "abc234")
    assert parse_target("/t/abc234/") == ("motion_slug", "abc234")
    assert parse_target("https://ai-debates.net/d/xyz789?x=1") == ("debate_slug", "xyz789")
    # Canonical links carry the topic's words after the slug.
    assert parse_target("https://ai-debates.net/d/xyz789/tabs-or-spaces") == (
        "debate_slug",
        "xyz789",
    )
    assert parse_target("/t/abc234/лучше-ли-офис/") == ("motion_slug", "abc234")
    assert parse_target(f"https://admin.example/admin/debates/{debate_id}") == (
        "debate_id",
        debate_id,
    )
    assert parse_target(f"http://localhost/debate/{debate_id}") == ("debate_id", debate_id)
    assert parse_target("abc234") == ("slug", "abc234")
    assert parse_target("/debate/not-an-id") is None
    assert parse_target("https://example.com/") is None
    assert parse_target("https://example.com/library/abc") is None
    assert parse_target("   ") is None


# --- gallery ------------------------------------------------------------------------------------


def test_versions_lift_a_topic_only_a_little() -> None:
    assert ranking.topic_trending_score(2.0, 1) == 2.0
    assert ranking.topic_trending_score(2.0, 0) == 2.0
    two, five, twenty = (ranking.topic_trending_score(1.0, n) for n in (2, 5, 20))
    assert 1.1 < two < five < twenty < 1.7
    # A liked single version still beats a pile of versions nobody liked.
    assert ranking.topic_trending_score(3.0, 1) > ranking.topic_trending_score(1.0, 50)


def test_grouped_gallery_picks_one_cover_per_topic() -> None:
    conditions = routes_gallery._public()
    trending = _sql(routes_gallery.covers_query(conditions, "trending"))
    assert "row_number() OVER (PARTITION BY coalesce(debates.motion_id, debates.id)" in trending
    assert "count(*) OVER (PARTITION BY coalesce(debates.motion_id, debates.id))" in trending
    assert "rn = 1" in trending and "ln(CAST(anon_1.versions AS FLOAT))" in trending
    assert "debates.is_public IS true" in trending and "debates.slug IS NOT NULL" in trending
    top = _sql(routes_gallery.covers_query(conditions, "top"))
    assert "ORDER BY debates.likes_count DESC NULLS LAST" in top and "ln(" not in top
    assert "anon_1.likes DESC NULLS LAST, anon_1.votes DESC NULLS LAST" in top
    new = _sql(routes_gallery.covers_query(conditions, "new"))
    assert "coalesce(debates.published_at, debates.created_at) DESC NULLS LAST" in new


def test_gallery_language_mirrors_language_code() -> None:
    sql = _sql(routes_gallery.language_sql() == "ru")
    key = "lower(trim(coalesce(CAST((debates.config_json ->> 'language') AS VARCHAR), '')))"
    assert sql.startswith(f"CASE {key} WHEN '' THEN 'en' WHEN 'english' THEN 'en'")
    for name, code in LANGUAGE_CODES.items():
        assert f"WHEN '{name}' THEN '{code}'" in sql
    # Codes ("ru", "pt-BR") keep their first two letters; any other name counts as English.
    assert f"char_length({key}) IN (2, 5)" in sql and "~ '^[[:alpha:]]{2}$'" in sql
    assert sql.endswith("ELSE 'en' END END = 'ru'")
    assert [language_code(v) for v in ("", "Russian", "pt-BR", "ru", "Swahili")] == [
        "en",
        "ru",
        "pt",
        "ru",
        "en",
    ]


# --- the debate page ----------------------------------------------------------------------------


def test_only_a_public_parent_is_named() -> None:
    assert serializers.remix_parent_out(None) is None
    assert serializers.remix_parent_out(_debate()) is None
    assert serializers.remix_parent_out(_debate(is_public=True, slug=None)) is None
    named = serializers.remix_parent_out(_debate(is_public=True, slug="abc"))
    assert named is not None and (named.slug, named.topic) == ("abc", "Tabs or spaces?")


def test_version_strip() -> None:
    current = _debate(is_public=True, slug="cur")
    other = _debate(
        is_public=True,
        slug="oth",
        config_json={"topic": "Табы или пробелы?", "language": "Russian"},
        participants=[
            DebateParticipant(role="moderator", model_id="m/host", persona_name="The Host"),
            DebateParticipant(role="debater", model_id="a/claude", persona_name="Claude"),
            DebateParticipant(role="debater", model_id="b/gpt", persona_name="GPT"),
        ],
        user=User(display_name="Ann"),
        likes_count=4,
        views=10,
    )
    info = MotionInfo(uuid.uuid4(), "topic1", "Tabs or spaces?", 2, ["a/claude", "b/gpt"])
    assert serializers.motion_out(None, [current], current) is None
    assert serializers.motion_out(info, [], current) is None
    strip = serializers.motion_out(info, [other, current], current)
    assert strip is not None and (strip.slug, strip.title, strip.versions) == (
        "topic1",
        info.title,
        2,
    )
    first, second = strip.items
    assert (first.slug, first.current, second.current) == ("oth", False, True)
    assert (first.language, first.language_code, first.author_name) == ("Russian", "ru", "Ann")
    assert [p.model for p in first.participants] == ["m/host", "a/claude", "b/gpt"]
    ref = serializers.motion_ref_out(info)
    assert ref is not None and ref.models == ["a/claude", "b/gpt"]


def test_news_goes_with_the_public_settings() -> None:
    conf = {"news": {"brief": "What happened.", "outlet": "BBC", "url": "https://bbc.co.uk/x"}}
    news = serializers.news_out(conf)
    assert news is not None and news.outlet == "BBC"
    assert serializers.news_out({}) is None
    assert serializers.news_out({"news": {"brief": ""}}) is None
    assert serializers.news_out({"news": {"brief": "x", "url": "javascript:alert(1)"}}) is None


# --- admin: moving versions -------------------------------------------------------------------------


class _FakeDB:
    def __init__(self, debate: Debate) -> None:
        self.debate = debate
        self.added: list[Any] = []
        self.commits = 0

    async def scalar(self, _statement: Any) -> Any:
        return self.debate

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1

    def audit(self) -> list[AdminAuditLog]:
        return [row for row in self.added if isinstance(row, AdminAuditLog)]


class _Topics:
    """The motions functions the move route calls, over an in-memory map of topics."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.source = uuid.uuid4()
        self.target = uuid.uuid4()
        self.created = uuid.uuid4()
        self.sizes = {self.source: 3, self.target: 2}
        self.merged: list[tuple[uuid.UUID, uuid.UUID]] = []

        async def resolve(_db: Any, motion_id: uuid.UUID) -> uuid.UUID:
            return motion_id

        async def summary(_db: Any, motion_id: uuid.UUID | None) -> dict[str, Any] | None:
            if motion_id is None:
                return None
            return {"slug": f"s-{str(motion_id)[:4]}", "debates": self.sizes.get(motion_id, 1)}

        async def find_target(_db: Any, raw: str) -> uuid.UUID | None:
            return {"/t/target": self.target, "/t/source": self.source}.get(raw.strip())

        async def merge(_db: Any, source: uuid.UUID, target: uuid.UUID) -> int:
            self.merged.append((source, target))
            return self.sizes[source]

        async def new_motion(_db: Any, key: str | None = None) -> uuid.UUID:
            return self.created

        monkeypatch.setattr(motions, "resolve", resolve)
        monkeypatch.setattr(motions, "motion_summary", summary)
        monkeypatch.setattr(motions, "find_target", find_target)
        monkeypatch.setattr(motions, "merge_motions", merge)
        monkeypatch.setattr(motions, "new_motion", new_motion)


def _ctx() -> AdminContext:
    admin = User(id=uuid.uuid4(), email="root@x.co", display_name="root", admin_role="admin")
    session = AdminSession(
        user_id=str(admin.id),
        csrf="c",
        created_at=time.time(),
        last_seen_at=time.time(),
        ip="",
        user_agent="",
        epoch=0,
    )
    return AdminContext(user=admin, session=session, session_hash="h", ip=None, user_agent=None)


def _request() -> Request:
    return Request({"type": "http", "method": "POST", "path": "/", "headers": [], "client": None})


async def _move(db: _FakeDB, **body: Any) -> Any:
    request = MotionMoveRequest(reason="same question", **body)
    return await admin_routes.move_motion(str(db.debate.id), request, _request(), _ctx(), db)  # type: ignore[arg-type]


async def test_admin_moves_a_version_to_another_topic(monkeypatch: pytest.MonkeyPatch) -> None:
    topics = _Topics(monkeypatch)
    db = _FakeDB(_debate(motion_id=topics.source))
    out = await _move(db, target="/t/target")
    assert out.status == "moved" and db.debate.motion_id == topics.target and not topics.merged
    [entry] = db.audit()
    assert entry.action == "debate.motion_changed" and entry.reason == "same question"
    assert db.commits == 1


async def test_admin_merges_a_whole_topic(monkeypatch: pytest.MonkeyPatch) -> None:
    topics = _Topics(monkeypatch)
    db = _FakeDB(_debate(motion_id=topics.source))
    out = await _move(db, target="/t/target", whole=True)
    assert topics.merged == [(topics.source, topics.target)] and "3 debates" in out.message
    assert db.debate.motion_id == topics.target


async def test_admin_splits_a_version_off(monkeypatch: pytest.MonkeyPatch) -> None:
    topics = _Topics(monkeypatch)
    db = _FakeDB(_debate(motion_id=topics.source))
    await _move(db)
    assert db.debate.motion_id == topics.created


async def test_admin_move_refusals(monkeypatch: pytest.MonkeyPatch) -> None:
    topics = _Topics(monkeypatch)
    cases: list[tuple[dict[str, Any], uuid.UUID, int]] = [
        ({"target": "/t/nowhere"}, topics.source, 404),
        ({"target": "/t/source"}, topics.source, 409),  # already there
        ({"whole": True}, topics.source, 400),  # a merge needs a target
        ({}, uuid.uuid4(), 409),  # alone in its topic: nothing to split off
    ]
    for body, motion_id, code in cases:
        db = _FakeDB(_debate(motion_id=motion_id))
        with pytest.raises(HTTPException) as caught:
            await _move(db, **body)
        assert caught.value.status_code == code, body
        assert not db.audit() and db.commits == 0
