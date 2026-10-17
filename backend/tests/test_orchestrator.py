import asyncio
import time
from collections.abc import AsyncIterator
from typing import Any

import pytest

from app.models.models import Debate, DebateParticipant
from app.services import orchestrator
from app.services.openrouter_client import OpenRouterClient, StreamChunk


@pytest.fixture
def events(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    sent: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        orchestrator, "publish_event", lambda _id, kind, data: sent.append((kind, data))
    )
    monkeypatch.setattr(orchestrator, "_stop_requested", lambda _id: False)
    return sent


def _fake_stream(monkeypatch: pytest.MonkeyPatch, *, hang_after: int | None = None) -> None:
    async def stream(
        self: OpenRouterClient, model: str, *args: Any, **kwargs: Any
    ) -> AsyncIterator[StreamChunk]:
        for i, word in enumerate(["Spaces ", "win."]):
            if hang_after is not None and i >= hang_after:
                await asyncio.sleep(30)  # a provider that only sends keep-alive comments
            yield StreamChunk(delta=word, model="qwen/qwen3:free")
        yield StreamChunk(usage={"completion_tokens": 2, "cost": 0})

    monkeypatch.setattr(OpenRouterClient, "stream_chat_completion", stream)


def _run(deadline_s: float) -> orchestrator.GenerationResult:
    return orchestrator._generate(
        "debate", 3, "Free Router A", "openrouter/free", [], None, time.monotonic() + deadline_s
    )


def test_generate_streams_the_answer(monkeypatch: pytest.MonkeyPatch, events):
    _fake_stream(monkeypatch)
    result = _run(5)
    assert result.text == "Spaces win." and result.error is None and not result.timed_out
    assert result.model == "qwen/qwen3:free"
    assert result.usage["completion_tokens"] == 2
    assert [kind for kind, _ in events] == ["turn_delta", "turn_delta"]


def test_generate_gives_up_at_the_deadline(monkeypatch: pytest.MonkeyPatch, events):
    _fake_stream(monkeypatch, hang_after=1)
    started = time.monotonic()
    result = _run(0.2)
    assert time.monotonic() - started < 5
    assert result.timed_out and result.error and "No complete answer" in result.error
    assert result.text == "Spaces "  # what was said before the stall is kept


def test_timed_out_pinned_model_does_not_fall_back(monkeypatch: pytest.MonkeyPatch):
    debate = Debate(participants=[DebateParticipant(role="moderator", model_id="qwen/qwen3:free")])
    calls: list[str] = []

    def generate(model: str) -> orchestrator.GenerationResult:
        calls.append(model)
        return orchestrator.GenerationResult(error="No complete answer", timed_out=True)

    speaker = {"role": "moderator", "model_id": "openrouter/free"}
    result, used = orchestrator._generate_as(debate, 0, speaker, generate)
    assert calls == ["qwen/qwen3:free"]  # the turn's time is used up
    assert result.timed_out and used == "qwen/qwen3:free"


def test_an_empty_answer_counts_as_a_failure(monkeypatch: pytest.MonkeyPatch, events):
    async def stream(
        self: OpenRouterClient, *args: Any, **kwargs: Any
    ) -> AsyncIterator[StreamChunk]:
        yield StreamChunk(usage={"completion_tokens": 0, "cost": 0}, model="liquid/lfm:free")

    monkeypatch.setattr(OpenRouterClient, "stream_chat_completion", stream)
    result = _run(5)
    assert result.error == "The model returned an empty answer"


def test_failure_message_names_speaker_and_model():
    message = orchestrator._failure("Free Router A", "qwen/qwen3:free", "HTTP 429: rate limited")
    assert message == "Free Router A (qwen/qwen3:free) could not answer: HTTP 429: rate limited"
