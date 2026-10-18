import uuid
from typing import Any

from app.api.serializers import router_of
from app.models.models import Debate, DebateParticipant
from app.services.free_router import (
    FREE_ROUTER_ID,
    participant_row,
    pinned_model,
    resolved_participants,
    routed_model,
    worth_pinning,
)
from app.services.orchestrator import GenerationResult, _generate_as


def _row(role: str, model_id: str) -> DebateParticipant:
    return DebateParticipant(role=role, model_id=model_id)


def _debate(rows: list[DebateParticipant]) -> Debate:
    return Debate(id=uuid.uuid4(), participants=rows)


class FakeModels:
    """Answers per requested model; records the order of requests."""

    def __init__(self, answers: dict[str, GenerationResult]):
        self.answers = answers
        self.calls: list[str] = []

    def __call__(self, model: str) -> GenerationResult:
        self.calls.append(model)
        return self.answers[model]


ARGUMENT = "Spaces render the same in every editor, so reviews never fight over alignment. " * 3


def _ok(model: str | None, text: str = ARGUMENT) -> GenerationResult:
    return GenerationResult(text=text, model=model)


def _host(model: str = FREE_ROUTER_ID) -> dict[str, Any]:
    return {"role": "moderator", "model_id": model, "display_name": "The Host"}


# --- rules -----------------------------------------------------------------


def test_routed_model_accepts_only_concrete_free_models():
    assert routed_model("upstage/solar-pro-3:free") == "upstage/solar-pro-3:free"
    assert routed_model(" meta-llama/llama-3.3-70b-instruct:free ") == (
        "meta-llama/llama-3.3-70b-instruct:free"
    )
    for value in (
        None,
        "",
        FREE_ROUTER_ID,
        "meta-llama/llama-3.3-70b-instruct",  # the paid variant would cost money
        "solar-pro-3:free",
        "a/b c:free",
        "a/" + "x" * 300 + ":free",
    ):
        assert routed_model(value) is None, value


def test_worth_pinning_skips_classifiers_and_stubs():
    assert worth_pinning("upstage/solar-pro-3:free", ARGUMENT)
    assert not worth_pinning("upstage/solar-pro-3:free", "User Safety: safe")
    assert not worth_pinning("nvidia/nemotron-3.5-content-safety:free", ARGUMENT)
    assert not worth_pinning("meta-llama/llama-guard-4-12b:free", ARGUMENT)


def test_participant_row_needs_matching_index_and_role():
    rows = [_row("moderator", "m"), _row("debater", "d")]
    assert participant_row(rows, 1, "debater") is rows[1]
    assert participant_row(rows, 1, "moderator") is None
    assert participant_row(rows, 2, "debater") is None
    assert participant_row(rows, -1, "moderator") is None


def test_pinned_model_only_for_router_participants():
    assert pinned_model(FREE_ROUTER_ID, _row("debater", "qwen/qwen3:free")) == "qwen/qwen3:free"
    assert pinned_model(FREE_ROUTER_ID, _row("debater", FREE_ROUTER_ID)) is None
    assert pinned_model(FREE_ROUTER_ID, None) is None
    assert pinned_model("openai/gpt-4o", _row("debater", "qwen/qwen3:free")) is None


def test_resolved_participants_swaps_pinned_routers_only():
    participants = [
        _host(),
        {"role": "debater", "model_id": FREE_ROUTER_ID},
        {"role": "debater", "model_id": "openai/gpt-4o"},
    ]
    rows = [_row("moderator", "z-ai/glm-4.5-air:free"), _row("debater", FREE_ROUTER_ID)]
    resolved = resolved_participants(participants, rows)
    assert [p["model_id"] for p in resolved] == [
        "z-ai/glm-4.5-air:free",
        FREE_ROUTER_ID,  # not pinned yet
        "openai/gpt-4o",  # no row: unchanged
    ]
    assert participants[0]["model_id"] == FREE_ROUTER_ID  # the config stays untouched


def test_router_of_names_the_router_once_a_model_is_pinned():
    assert router_of({"model_id": FREE_ROUTER_ID}, "qwen/qwen3:free") == FREE_ROUTER_ID
    assert router_of({"model_id": FREE_ROUTER_ID}, FREE_ROUTER_ID) is None
    assert router_of({"model_id": "openai/gpt-4o"}, "openai/gpt-4o") is None
    assert router_of({}, "openai/gpt-4o") is None


# --- the worker ------------------------------------------------------------


def test_regular_models_are_used_as_configured():
    debate = _debate([_row("moderator", "openai/gpt-4o")])
    models = FakeModels({"openai/gpt-4o": _ok("openai/gpt-4o-2024-08-06")})
    result, used = _generate_as(debate, 0, _host("openai/gpt-4o"), models)
    assert used == "openai/gpt-4o"  # not the dated id the response names
    assert models.calls == ["openai/gpt-4o"]
    assert result.text


def test_first_router_answer_pins_the_model():
    debate = _debate([_row("moderator", FREE_ROUTER_ID)])
    models = FakeModels({FREE_ROUTER_ID: _ok("upstage/solar-pro-3:free")})
    _, used = _generate_as(debate, 0, _host(), models)
    assert used == "upstage/solar-pro-3:free"
    assert debate.participants[0].model_id == "upstage/solar-pro-3:free"


def test_pinned_model_answers_later_turns():
    debate = _debate([_row("moderator", "upstage/solar-pro-3:free")])
    models = FakeModels({"upstage/solar-pro-3:free": _ok("upstage/solar-pro-3:free")})
    _, used = _generate_as(debate, 0, _host(), models)
    assert used == "upstage/solar-pro-3:free"
    assert models.calls == ["upstage/solar-pro-3:free"]


def test_failed_pinned_model_falls_back_to_the_router_and_keeps_the_pin():
    debate = _debate([_row("moderator", "upstage/solar-pro-3:free")])
    models = FakeModels(
        {
            "upstage/solar-pro-3:free": GenerationResult(error="HTTP 429: rate limited"),
            FREE_ROUTER_ID: _ok("qwen/qwen3:free"),
        }
    )
    result, used = _generate_as(debate, 0, _host(), models)
    assert models.calls == ["upstage/solar-pro-3:free", FREE_ROUTER_ID]
    assert used == "qwen/qwen3:free" and not result.error
    assert debate.participants[0].model_id == "upstage/solar-pro-3:free"


def test_partial_text_is_not_retried():
    debate = _debate([_row("moderator", "upstage/solar-pro-3:free")])
    broken = GenerationResult(text="Half a sen", error="provider died")
    models = FakeModels({"upstage/solar-pro-3:free": broken})
    result, used = _generate_as(debate, 0, _host(), models)
    assert result is broken and used == "upstage/solar-pro-3:free"
    assert models.calls == ["upstage/solar-pro-3:free"]


def test_no_pin_from_failed_or_unusual_answers():
    for answer in (
        GenerationResult(error="HTTP 503", model="qwen/qwen3:free"),
        _ok("qwen/qwen3:free", text="  "),
        _ok("qwen/qwen3:free", text="User Safety: safe"),
        _ok("nvidia/nemotron-3.5-content-safety:free"),
        _ok("qwen/qwen3"),  # not a free variant
        _ok(None),
    ):
        debate = _debate([_row("moderator", FREE_ROUTER_ID)])
        _, used = _generate_as(debate, 0, _host(), FakeModels({FREE_ROUTER_ID: answer}))
        assert debate.participants[0].model_id == FREE_ROUTER_ID
        assert used == (routed_model(answer.model) or FREE_ROUTER_ID)


def test_router_without_a_row_still_answers():
    debate = _debate([])  # legacy debate without normalized rows
    models = FakeModels({FREE_ROUTER_ID: _ok("qwen/qwen3:free")})
    _, used = _generate_as(debate, 0, _host(), models)
    assert used == "qwen/qwen3:free"


# --- fallback when the router keeps picking classifiers ---------------------------------------


def test_pick_fallbacks_prefers_steady_chat_models() -> None:
    from app.services.free_router import pick_fallbacks

    rows = [
        ("meta-llama/llama-4-maverick:free", 18, 20),  # 90 %
        ("deepseek/deepseek-r1:free", 9, 10),  # 90 %, fewer answers
        ("qwen/qwen3-coder:free", 5, 5),  # 100 %
        ("nvidia/nemotron-3.5-content-safety:free", 30, 30),  # a classifier
        ("x-ai/grok-4.2", 40, 40),  # not free
        ("mistral/flaky:free", 6, 10),  # 60 %: too unreliable
        ("one/lucky:free", 1, 1),  # too little evidence
    ]
    assert pick_fallbacks(rows) == [
        "qwen/qwen3-coder:free",
        "meta-llama/llama-4-maverick:free",
        "deepseek/deepseek-r1:free",
    ]
    assert pick_fallbacks(rows, exclude=["qwen/qwen3-coder:free"], limit=1) == [
        "meta-llama/llama-4-maverick:free"
    ]


def _classifier_pick() -> GenerationResult:
    return GenerationResult(
        error="The Free Router picked nvidia/x-content-safety:free, which cannot debate",
        error_kind="classifier",
        model="nvidia/x-content-safety:free",
        retryable=True,
        rerouted=True,
    )


def test_classifier_picks_hand_the_turn_to_a_proven_free_model(monkeypatch: Any) -> None:
    from app.services import orchestrator

    monkeypatch.setattr(orchestrator, "_stop_requested", lambda debate_id: False)
    monkeypatch.setattr(
        orchestrator, "fallback_models", lambda exclude=(): ["a/broken:free", "b/steady:free"]
    )
    row = _row("debater", FREE_ROUTER_ID)
    debate = _debate([_row("moderator", "openai/gpt-4o"), row])
    models = FakeModels(
        {
            FREE_ROUTER_ID: _classifier_pick(),
            "a/broken:free": GenerationResult(error="429", error_kind="rate_limited"),
            "b/steady:free": _ok(None),
        }
    )
    speaker = {"role": "debater", "model_id": FREE_ROUTER_ID, "display_name": "Free Router A"}
    result, used = _generate_as(debate, 1, speaker, models)
    assert models.calls == [FREE_ROUTER_ID] * 3 + ["a/broken:free", "b/steady:free"]
    assert (result.error, used, row.model_id) == (None, "b/steady:free", "b/steady:free")


def test_without_fallbacks_the_classifier_failure_stands(monkeypatch: Any) -> None:
    from app.services import orchestrator

    monkeypatch.setattr(orchestrator, "_stop_requested", lambda debate_id: False)
    monkeypatch.setattr(orchestrator, "fallback_models", lambda exclude=(): [])
    debate = _debate([_row("moderator", FREE_ROUTER_ID)])
    result, used = _generate_as(
        debate, 0, _host(), FakeModels({FREE_ROUTER_ID: _classifier_pick()})
    )
    # As before the fallback: the turn fails, named after the classifier the router picked.
    assert result.error_kind == "classifier" and used == "nvidia/x-content-safety:free"
    assert debate.participants[0].model_id == FREE_ROUTER_ID  # nothing pinned
