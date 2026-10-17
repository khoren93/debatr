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
    monkeypatch.setattr(orchestrator, "wait_for_slot", lambda _deadline: True)
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


def test_a_busy_free_quota_fails_the_turn_before_any_request(
    monkeypatch: pytest.MonkeyPatch, events
):
    _fake_stream(monkeypatch)
    monkeypatch.setattr(orchestrator, "wait_for_slot", lambda _deadline: False)
    result = _run(5)
    assert result.error and "Free models are busy" in result.error and not result.text
    assert events == []


def test_own_keys_and_paid_models_skip_the_free_quota(monkeypatch: pytest.MonkeyPatch, events):
    _fake_stream(monkeypatch)
    asked: list[float] = []
    monkeypatch.setattr(orchestrator, "wait_for_slot", lambda d: asked.append(d) or True)
    deadline = time.monotonic() + 5
    orchestrator._generate("d", 0, "A", "openrouter/free", [], "sk-or-own", deadline)
    orchestrator._generate("d", 0, "A", "openai/gpt-5", [], None, deadline)
    assert asked == []
    orchestrator._generate("d", 0, "A", "qwen/qwen3:free", [], None, deadline)
    assert asked == [deadline]


# --- retries -------------------------------------------------------------------------------


class Answers:
    """Hands out prepared results in order and records the models asked."""

    def __init__(self, *results: orchestrator.GenerationResult):
        self.results = list(results)
        self.calls: list[str] = []

    def __call__(self, model: str) -> orchestrator.GenerationResult:
        self.calls.append(model)
        return self.results.pop(0)


def _busy() -> orchestrator.GenerationResult:
    return orchestrator.GenerationResult(error="HTTP 429: rate limited", retryable=True)


@pytest.fixture
def no_pauses(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    slept: list[float] = []
    monkeypatch.setattr(orchestrator.time, "sleep", slept.append)
    monkeypatch.setattr(orchestrator, "_stop_requested", lambda _id: False)
    return slept


def _speaker(model: str) -> dict[str, Any]:
    return {"role": "debater", "model_id": model}


def test_passing_failures_are_tried_again(no_pauses):
    answers = Answers(_busy(), _busy(), orchestrator.GenerationResult(text="Finally.", model="m"))
    debate = Debate(participants=[])
    result, used = orchestrator._generate_as(debate, 0, _speaker("openai/gpt-5"), answers)
    assert result.text == "Finally." and used == "openai/gpt-5"
    assert answers.calls == ["openai/gpt-5"] * 3
    assert no_pauses == list(orchestrator.RETRY_PAUSES)


def test_lasting_failures_and_partial_answers_are_not_retried(no_pauses):
    for failed in (
        orchestrator.GenerationResult(error="HTTP 400: bad model"),  # not retryable
        orchestrator.GenerationResult(text="Half a", error="died", retryable=True),
    ):
        answers = Answers(failed)
        orchestrator._generate_as(Debate(participants=[]), 0, _speaker("openai/gpt-5"), answers)
        assert len(answers.calls) == 1
    assert no_pauses == []


def test_retries_stop_at_the_deadline(no_pauses):
    answers = Answers(_busy(), _busy(), _busy())
    deadline = time.monotonic() + 5  # room for the 3 s pause, not for the 10 s one
    result, _ = orchestrator._generate_as(
        Debate(participants=[]), 0, _speaker("openai/gpt-5"), answers, deadline
    )
    assert len(answers.calls) == 2 and result.error
    assert no_pauses == [orchestrator.RETRY_PAUSES[0]]


LONG = "Spaces render the same in every editor, so reviews never fight over alignment. " * 3


def test_free_router_retries_the_router_not_the_pin(no_pauses):
    debate = Debate(participants=[DebateParticipant(role="debater", model_id="qwen/qwen3:free")])
    answers = Answers(_busy(), _busy(), orchestrator.GenerationResult(text=LONG, model="z/m:free"))
    result, used = orchestrator._generate_as(debate, 0, _speaker("openrouter/free"), answers)
    assert answers.calls == ["qwen/qwen3:free", "openrouter/free", "openrouter/free"]
    assert result.text == LONG and used == "z/m:free"


# --- Free Router picks that cannot debate ----------------------------------------------------


def test_a_classifier_pick_is_dropped_before_any_text(monkeypatch: pytest.MonkeyPatch, events):
    async def stream(
        self: OpenRouterClient, *args: Any, **kwargs: Any
    ) -> AsyncIterator[StreamChunk]:
        yield StreamChunk(
            delta="User Safety: safe", model="nvidia/nemotron-3.5-content-safety:free"
        )

    monkeypatch.setattr(OpenRouterClient, "stream_chat_completion", stream)
    result = _run(5)
    assert result.rerouted and result.retryable and "cannot debate" in (result.error or "")
    assert result.text == "" and events == []  # nobody saw "User Safety: safe"


def test_a_chosen_classifier_is_not_second_guessed(monkeypatch: pytest.MonkeyPatch, events):
    async def stream(
        self: OpenRouterClient, *args: Any, **kwargs: Any
    ) -> AsyncIterator[StreamChunk]:
        yield StreamChunk(delta="User Safety: safe", model="meta-llama/llama-guard-4-12b:free")

    monkeypatch.setattr(OpenRouterClient, "stream_chat_completion", stream)
    deadline = time.monotonic() + 5
    result = orchestrator._generate(
        "d", 0, "A", "meta-llama/llama-guard-4-12b:free", [], None, deadline
    )
    assert result.text == "User Safety: safe" and not result.error


def test_the_router_is_asked_again_at_once_after_a_classifier(no_pauses):
    debate = Debate(participants=[DebateParticipant(role="debater", model_id="openrouter/free")])
    dropped = orchestrator.GenerationResult(error="cannot debate", retryable=True, rerouted=True)
    answers = Answers(dropped, orchestrator.GenerationResult(text=LONG, model="z/m:free"))
    result, used = orchestrator._generate_as(debate, 0, _speaker("openrouter/free"), answers)
    assert result.text == LONG and used == "z/m:free"
    assert no_pauses == []  # not a busy provider: no waiting
    assert debate.participants[0].model_id == "z/m:free"


def test_short_router_answers_are_asked_again(no_pauses):
    debate = Debate(participants=[DebateParticipant(role="debater", model_id="openrouter/free")])
    answers = Answers(
        orchestrator.GenerationResult(text="Hello there!", model="tiny/model:free"),
        orchestrator.GenerationResult(text=LONG, model="z/m:free"),
    )
    result, used = orchestrator._generate_as(debate, 0, _speaker("openrouter/free"), answers)
    assert len(answers.calls) == 2 and result.text == LONG and used == "z/m:free"


def test_the_last_short_answer_stands_when_none_is_better(no_pauses):
    shorts = [
        orchestrator.GenerationResult(text="Hi.", model="tiny/model:free")
    ] * orchestrator.ROUTER_TRIES
    answers = Answers(*shorts)
    debate = Debate(participants=[DebateParticipant(role="debater", model_id="openrouter/free")])
    result, used = orchestrator._generate_as(debate, 0, _speaker("openrouter/free"), answers)
    assert len(answers.calls) == orchestrator.ROUTER_TRIES and result.text == "Hi."
    assert used == "tiny/model:free"  # the transcript names the model that wrote it
    assert debate.participants[0].model_id == "openrouter/free"  # not pinned


def test_a_retry_after_streamed_text_restarts_the_turn_for_viewers(events):
    started = {"seq_index": 3, "speaker_name": "A"}
    results = iter(
        [
            orchestrator.GenerationResult(error="HTTP 429", retryable=True),  # nothing streamed
            orchestrator.GenerationResult(text="Hello there!"),  # streamed, then dropped
            orchestrator.GenerationResult(text=LONG),
        ]
    )
    attempt = orchestrator._announcing("d", started, lambda _model: next(results))
    attempt("m")
    attempt("m")
    assert events == []
    attempt("m")
    assert events == [("turn_started", started)]
