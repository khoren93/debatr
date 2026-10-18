"""Statistics data (A2): provider usage booking, error kinds, the debate context, turn timing
and daily activity. Pure: `usage_rows` (conftest) keeps booked rows in memory."""

import time
import uuid
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import inspect

from app.models.models import ProviderUsage, User
from app.schemas.media import MediaOptions
from app.services import activity, orchestrator, usage
from app.services.media import jobs, llm
from app.services.openrouter_client import OpenRouterClient, OpenRouterError, StreamChunk

DEBATE = str(uuid.uuid4())


# --- error kinds and rows ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "flags", "kind"),
    [
        (429, {}, "rate_limit"),
        (502, {}, "provider_5xx"),
        (None, {}, "connection"),
        (401, {}, "auth"),
        (402, {}, "credits"),
        (400, {}, "bad_request"),
        (None, {"timed_out": True}, "timeout"),
        (None, {"empty": True}, "empty"),
        (200, {"classifier": True}, "classifier"),
        (None, {"free_quota": True}, "free_quota"),
    ],
)
def test_classify_error(status: int | None, flags: dict[str, bool], kind: str) -> None:
    assert usage.classify_error(status, **flags) == kind


def test_usage_row_reads_openrouter_usage() -> None:
    row = usage.usage_row(
        "director",
        model="google/gemini-2.5-flash",
        key="system",
        usage={"prompt_tokens": 1200, "completion_tokens": 300, "cost": 0.00123456789},
        duration_ms=1500,
        debate_id=DEBATE,
    )
    assert (row.purpose, row.key_owner, row.tokens_in, row.tokens_out) == (
        "director",
        "system",
        1200,
        300,
    )
    assert row.cost_usd == Decimal("0.001235") and row.debate_id == uuid.UUID(DEBATE)
    assert row.ok and row.error_kind is None


def test_usage_row_edge_cases() -> None:
    failed = usage.usage_row("turn", model="", key="user", ok=False, error_kind="rate_limit")
    assert failed.model == "unknown" and failed.error_kind == "rate_limit" and failed.cost_usd == 0
    kept = usage.usage_row("turn", model="m", key="user", ok=True, error_kind="rate_limit")
    assert kept.error_kind is None  # only failures carry a kind
    tts = usage.usage_row("tts", model="m", key="system", cost_usd=-1, usage={"cost": 5}, chars=-3)
    assert tts.cost_usd == 0 and tts.chars == 0  # an explicit cost wins, never negative
    assert usage.key_owner(None) == "system" and usage.key_owner("sk-or-…") == "user"


def test_record_never_raises(usage_rows: list[ProviderUsage]) -> None:
    usage.record("turn", model="m", key="system", debate_id="not-a-uuid")
    assert usage_rows == []  # dropped and logged, the caller goes on


# --- the debate context -----------------------------------------------------------------------


def test_jobs_book_their_debate_even_in_threads() -> None:
    @usage.attributed
    def job(debate_id: str) -> tuple[str | None, str | None, str | None]:
        with usage.ContextThreadPool(max_workers=1) as pool:
            carried = pool.submit(usage.current_debate).result()
        with ThreadPoolExecutor(max_workers=1) as pool:
            plain = pool.submit(usage.current_debate).result()
        return usage.current_debate(), carried, plain

    assert job(DEBATE) == (DEBATE, DEBATE, None)  # a plain pool would lose it
    assert job(debate_id=DEBATE)[0] == DEBATE
    assert usage.current_debate() is None  # reset after the job


# --- worker LLM helpers -----------------------------------------------------------------------


def _stream(monkeypatch: pytest.MonkeyPatch, *chunks: StreamChunk, error: Exception | None = None):
    async def stream(
        self: OpenRouterClient, *args: Any, **kwargs: Any
    ) -> AsyncIterator[StreamChunk]:
        for chunk in chunks:
            yield chunk
        if error is not None:
            raise error

    monkeypatch.setattr(OpenRouterClient, "stream_chat_completion", stream)


def test_complete_books_the_answering_model(
    monkeypatch: pytest.MonkeyPatch, usage_rows: list[ProviderUsage]
) -> None:
    _stream(
        monkeypatch,
        StreamChunk(delta="{}", model="openai/gpt-4o-mini-2024-07-18"),
        StreamChunk(usage={"prompt_tokens": 10, "completion_tokens": 2, "cost": 0.0001}),
    )
    text, _ = usage.attributed(
        lambda debate_id: llm.complete("openai/gpt-4o-mini", [], purpose="verdict_structure")
    )(DEBATE)
    (row,) = usage_rows
    assert text == "{}" and row.purpose == "verdict_structure" and row.ok
    assert row.model == "openai/gpt-4o-mini-2024-07-18" and row.debate_id == uuid.UUID(DEBATE)
    assert row.key_owner == "system" and row.duration_ms is not None


def test_complete_books_failures_too(
    monkeypatch: pytest.MonkeyPatch, usage_rows: list[ProviderUsage]
) -> None:
    _stream(monkeypatch, error=OpenRouterError("busy", status_code=429))
    with pytest.raises(OpenRouterError):
        llm.complete("m", [], purpose="sketch", api_key="sk-or-own")
    _stream(monkeypatch, StreamChunk(usage={"cost": 0.0002}))
    llm.complete("m", [], purpose="sketch")
    assert [(r.ok, r.error_kind, r.key_owner) for r in usage_rows] == [
        (False, "rate_limit", "user"),
        (False, "empty", "system"),
    ]
    assert usage_rows[1].cost_usd == Decimal("0.0002")  # an empty answer still cost money


def test_complete_message_and_images(
    monkeypatch: pytest.MonkeyPatch, usage_rows: list[ProviderUsage]
) -> None:
    async def chat(self: OpenRouterClient, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return {
            "model": "perplexity/sonar",
            "choices": [{"message": {"content": "ok", "annotations": [{"url": "x"}]}}],
            "usage": {"cost": 0.005},
        }

    async def image(self: OpenRouterClient, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"data": [{"b64_json": "aGk="}], "usage": {}}

    monkeypatch.setattr(OpenRouterClient, "chat_completion", chat)
    monkeypatch.setattr(OpenRouterClient, "generate_image", image)
    text, annotations, _ = llm.complete_message("perplexity/sonar", [], purpose="factcheck")
    data, _ = llm.generate_image("flux", "a cat", fallback_cost=0.009)
    assert (text, annotations, data) == ("ok", [{"url": "x"}], b"hi")
    assert [(r.purpose, r.model, float(r.cost_usd)) for r in usage_rows] == [
        ("factcheck", "perplexity/sonar", 0.005),
        ("image", "flux", 0.009),  # no cost in the response: the price table
    ]


# --- turns ------------------------------------------------------------------------------------


@pytest.fixture
def quiet_turns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(orchestrator, "publish_event", lambda *args: None)
    monkeypatch.setattr(orchestrator, "_stop_requested", lambda _id: False)
    monkeypatch.setattr(orchestrator, "wait_for_slot", lambda _deadline: True)


def _turn(model: str = "openrouter/free", api_key: str | None = None, purpose: str = "turn"):
    return orchestrator._generate(
        DEBATE, 4, "A", model, [], api_key, time.monotonic() + 5, purpose=purpose
    )


def test_every_try_of_a_turn_is_booked_with_its_timing(
    monkeypatch: pytest.MonkeyPatch, usage_rows: list[ProviderUsage], quiet_turns: None
) -> None:
    _stream(
        monkeypatch,
        StreamChunk(delta="Spaces ", model="qwen/qwen3:free"),
        StreamChunk(delta="win.", model="qwen/qwen3:free"),
        StreamChunk(usage={"prompt_tokens": 50, "completion_tokens": 2, "cost": 0}),
    )
    result = _turn()
    assert result.ttft_ms is not None and result.duration_ms is not None
    assert result.duration_ms >= result.ttft_ms
    (row,) = usage_rows
    assert (row.purpose, row.model, row.ok, row.tokens_in) == ("turn", "qwen/qwen3:free", True, 50)
    assert row.meta_json["seq_index"] == 4 and "ttft_ms" in row.meta_json
    saved = orchestrator.turn_usage(result)
    assert saved["completion_tokens"] == 2 and saved["ttft_ms"] == result.ttft_ms
    assert "error_kind" not in saved


def test_failed_tries_carry_their_kind(
    monkeypatch: pytest.MonkeyPatch, usage_rows: list[ProviderUsage], quiet_turns: None
) -> None:
    _stream(monkeypatch, StreamChunk(delta="User Safety: safe", model="x/content-safety:free"))
    assert _turn().error_kind == "classifier"
    _stream(monkeypatch, error=OpenRouterError("rate limited", status_code=429))
    assert _turn("openai/gpt-5", api_key="sk-or-own", purpose="verdict").error_kind == "rate_limit"
    _stream(monkeypatch, StreamChunk(usage={"cost": 0.001}))
    empty = _turn("openai/gpt-5")
    assert empty.error_kind == "empty" and orchestrator.turn_usage(empty)["error_kind"] == "empty"
    assert [(r.purpose, r.ok, r.error_kind, r.key_owner) for r in usage_rows] == [
        ("turn", False, "classifier", "system"),
        ("verdict", False, "rate_limit", "user"),
        ("turn", False, "empty", "system"),
    ]
    assert usage_rows[0].model == "x/content-safety:free"  # the router's pick, not the router


def test_a_busy_free_quota_books_nothing(
    monkeypatch: pytest.MonkeyPatch, usage_rows: list[ProviderUsage], quiet_turns: None
) -> None:
    monkeypatch.setattr(orchestrator, "wait_for_slot", lambda _deadline: False)
    assert _turn().error_kind == "free_quota"
    assert usage_rows == []  # no request was made


# --- TTS --------------------------------------------------------------------------------------


def test_tts_books_characters_and_an_estimate(usage_rows: list[ProviderUsage]) -> None:
    task = jobs.TurnTask(
        seq_index=2,
        speaker=None,  # type: ignore[arg-type]
        round_id="round_1",
        turn_type="opening",
        text="hello",
        previous_text=None,
        next_text=None,
        voice_id="v",
    )
    eleven = MediaOptions(provider="elevenlabs", model_id="eleven_v3")
    jobs._book_tts(eleven, task, "system", chars=2000, started=time.monotonic())
    jobs._book_tts(
        MediaOptions(provider="edge"), task, "system", chars=900, started=time.monotonic()
    )
    jobs._book_tts(eleven, task, "user", chars=0, started=time.monotonic(), error=OSError("x"))
    assert [(r.provider, r.model, r.chars, float(r.cost_usd), r.ok) for r in usage_rows] == [
        ("elevenlabs", "eleven_v3", 2000, 0.2, True),
        ("edge", "edge-tts", 900, 0.0, True),
        ("elevenlabs", "eleven_v3", 0, 0.0, False),
    ]
    assert usage_rows[0].meta_json == {"seq_index": 2, "estimated": True}


# --- activity ---------------------------------------------------------------------------------


NOON = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("last_seen", "due"),
    [
        (None, (True, True)),
        (NOON - timedelta(minutes=3), (False, False)),
        (NOON - timedelta(minutes=10), (True, False)),
        (NOON.replace(hour=0, minute=1) - timedelta(minutes=3), (True, True)),  # new UTC day
    ],
)
def test_activity_due(last_seen: datetime | None, due: tuple[bool, bool]) -> None:
    assert activity.activity_due(last_seen, NOON) == due


class _FakeSession:
    def __init__(self, fail: bool = False) -> None:
        self.statements: list[str] = []
        self.fail = fail

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    async def execute(self, statement: Any) -> None:
        if self.fail:
            raise RuntimeError("database down")
        self.statements.append(str(statement).split()[0])

    async def commit(self) -> None:
        return None


async def test_note_activity_writes_once_per_window(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _FakeSession()
    monkeypatch.setattr(activity, "AsyncSessionLocal", lambda: session)
    user = User(id=uuid.uuid4(), email="a@b.co", display_name="A", last_seen_at=None)
    await activity.note_activity(user, NOON)
    assert session.statements == ["INSERT", "UPDATE"] and user.last_seen_at == NOON
    # The request's copy learns the value without a pending change to flush.
    assert not inspect(user).attrs.last_seen_at.history.has_changes()
    await activity.note_activity(user, NOON + timedelta(minutes=5))
    assert session.statements == ["INSERT", "UPDATE"]  # nothing new within the window
    await activity.note_activity(user, NOON + timedelta(minutes=11))
    assert session.statements == ["INSERT", "UPDATE", "UPDATE"]  # same day: no new row


async def test_note_activity_never_fails_the_request(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(activity, "AsyncSessionLocal", lambda: _FakeSession(fail=True))
    user = User(id=uuid.uuid4(), email="a@b.co", display_name="A", last_seen_at=None)
    await activity.note_activity(user, NOON)
    assert user.last_seen_at is None
