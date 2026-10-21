"""IndexNow announcements (services/indexnow): when it is on, what is noted, what is sent."""

import json
import uuid
from contextlib import contextmanager
from typing import Any

import httpx
import pytest

from app.core.config import settings
from app.models.models import Debate
from app.services import indexnow

KEY = "0123456789abcdef0123456789abcdef"


class FakePipeline:
    def __init__(self, redis: "FakeRedis") -> None:
        self.redis = redis

    def sadd(self, key: str, *members: str) -> None:
        self.redis.sadd(key, *members)

    def expire(self, key: str, seconds: int) -> None:
        self.redis.ttl[key] = seconds

    def execute(self) -> list[Any]:
        return []


class FakeRedis:
    def __init__(self) -> None:
        self.sets: dict[str, set[str]] = {}
        self.data: dict[str, str] = {}
        self.ttl: dict[str, int] = {}

    def pipeline(self) -> FakePipeline:
        return FakePipeline(self)

    def sadd(self, key: str, *members: str) -> int:
        self.sets.setdefault(key, set()).update(members)
        return len(members)

    def spop(self, key: str, count: int) -> list[bytes]:
        found = sorted(self.sets.pop(key, set()))
        self.sets[key] = set(found[count:])
        return [m.encode() for m in found[:count]]

    def set(self, key: str, value: str, ex: int | None = None, nx: bool = False) -> bool:
        if nx and key in self.data:
            return False
        self.data[key] = value
        return True

    def delete(self, key: str) -> None:
        self.data.pop(key, None)


@pytest.fixture
def production(monkeypatch: pytest.MonkeyPatch) -> FakeRedis:
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "SITE_URL", "https://debatr.example")
    monkeypatch.setattr(settings, "INDEXNOW_KEY", KEY)
    redis = FakeRedis()
    monkeypatch.setattr(indexnow, "get_sync_redis", lambda: redis)
    return redis


def test_enabled_only_in_production_over_https_with_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "SITE_URL", "https://debatr.example")
    monkeypatch.setattr(settings, "INDEXNOW_KEY", KEY)
    assert indexnow.enabled()
    monkeypatch.setattr(settings, "INDEXNOW_KEY", "short")
    assert not indexnow.enabled() and not indexnow.key_valid()
    monkeypatch.setattr(settings, "INDEXNOW_KEY", KEY)
    monkeypatch.setattr(settings, "SITE_URL", "http://debatr.example")
    assert not indexnow.enabled()
    monkeypatch.setattr(settings, "SITE_URL", "https://debatr.example")
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    assert not indexnow.enabled()


def test_refs_name_the_page_and_its_topic(production: FakeRedis) -> None:
    motion = uuid.uuid4()
    debate = Debate(slug="abc123", title="x", config_json={"topic": "Дом или офис?"})
    debate.motion_id = motion
    assert indexnow.debate_refs(debate) == [
        "https://debatr.example/d/abc123/%D0%B4%D0%BE%D0%BC-%D0%B8%D0%BB%D0%B8-%D0%BE%D1%84%D0%B8%D1%81",
        f"motion:{motion}",
    ]
    assert indexnow.refs_of(None, "", motion) == [f"motion:{motion}"]
    assert indexnow.refs_of("abc", "?", None) == ["https://debatr.example/d/abc"]


def test_announce_is_silent_when_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")

    def no_redis() -> None:
        raise AssertionError("Redis must not be touched")

    monkeypatch.setattr(indexnow, "get_sync_redis", no_redis)
    indexnow.announce_sync(["https://debatr.example/d/x"])


def test_announce_notes_refs(production: FakeRedis) -> None:
    indexnow.announce_sync(["https://debatr.example/d/x", "motion:1"])
    indexnow.announce_sync([])
    assert production.sets[indexnow.PENDING_KEY] == {"https://debatr.example/d/x", "motion:1"}
    assert production.ttl[indexnow.PENDING_KEY] == indexnow.PENDING_TTL


def test_submit_posts_the_protocol_payload(production: FakeRedis) -> None:
    seen: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(202)

    status = indexnow.submit(["https://debatr.example/d/x"], transport=httpx.MockTransport(answer))
    assert status == 202
    assert str(seen[0].url) == indexnow.ENDPOINT
    assert json.loads(seen[0].content) == {
        "host": "debatr.example",
        "key": KEY,
        "keyLocation": f"https://debatr.example/{KEY}.txt",
        "urlList": ["https://debatr.example/d/x"],
    }

    def broken(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    assert (
        indexnow.submit(["https://debatr.example/d/x"], transport=httpx.MockTransport(broken)) == 0
    )


@contextmanager
def _session() -> Any:
    yield object()


@pytest.mark.parametrize(("status", "kept"), [(200, False), (422, False), (429, True), (0, True)])
def test_flush_sends_once_and_keeps_what_may_pass_later(
    production: FakeRedis, monkeypatch: pytest.MonkeyPatch, status: int, kept: bool
) -> None:
    sent: list[list[str]] = []
    monkeypatch.setattr("app.core.sync_db.get_sync_session", _session)
    monkeypatch.setattr(indexnow, "resolve", lambda db, refs: [r.upper() for r in refs])

    def submit(urls: list[str]) -> int:
        sent.append(urls)
        return status

    monkeypatch.setattr(indexnow, "submit", submit)
    production.sadd(indexnow.PENDING_KEY, "a", "b")
    indexnow.flush_job()
    assert sent == [["A", "B"]]
    assert production.sets[indexnow.PENDING_KEY] == ({"a", "b"} if kept else set())
    assert indexnow.LOCK_KEY not in production.data

    # Nothing noted: nothing sent.
    sent.clear()
    production.sets[indexnow.PENDING_KEY] = set()
    indexnow.flush_job()
    assert sent == []


def test_submit_all_sends_batches(production: FakeRedis, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(indexnow, "BATCH_LIMIT", 2)
    batches: list[list[str]] = []
    statuses = iter([202, 200, 429])

    def answer(request: httpx.Request) -> httpx.Response:
        batches.append(json.loads(request.content)["urlList"])
        return httpx.Response(next(statuses))

    urls = [f"https://debatr.example/d/{i}" for i in range(5)]
    assert indexnow.submit_all(urls, transport=httpx.MockTransport(answer)) is False
    assert batches == [urls[:2], urls[2:4], urls[4:]]


class _Rows:
    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows

    def all(self) -> list[Any]:
        return self.rows


class _Topic:
    def __init__(self, slug: str, title: str) -> None:
        self.slug = slug
        self.title = title


def test_all_urls_lists_listings_topics_and_debates(production: FakeRedis) -> None:
    answers = iter(
        [
            _Rows([_Topic("t0p1c", "Cats or dogs?")]),
            _Rows([("abc123", "Дом или офис?"), (None, "draft"), ("abc123", "Дом или офис?")]),
        ]
    )

    class Db:
        def execute(self, statement: Any) -> _Rows:
            return next(answers)

    urls = indexnow.all_urls(Db())  # type: ignore[arg-type]
    assert urls[0] == "https://debatr.example/"
    assert "https://debatr.example/gallery?format=rap_battle" in urls
    assert "https://debatr.example/t/t0p1c/cats-or-dogs" in urls
    assert (
        urls[-1]
        == "https://debatr.example/d/abc123/%D0%B4%D0%BE%D0%BC-%D0%B8%D0%BB%D0%B8-%D0%BE%D1%84%D0%B8%D1%81"
    )
    assert len(urls) == len(set(urls))
