import json
from typing import Any

import pytest

from app.models.models import Debate, Turn
from app.services.media import llm
from app.services.moderation import (
    FALLBACK_REASON,
    apply_check,
    build_moderation_messages,
    check_debate,
    mark_admin_decision,
    parse_moderation,
    should_auto_publish,
    wants_public,
)
from app.services.verdict import build_verdict_parse_messages, structure_verdict

CONF: dict[str, Any] = {
    "topic": "Should cities ban cars?",
    "description": "Urban planning debate",
    "auto_publish": True,
    "participants": [
        {"role": "moderator", "display_name": "Host"},
        {"role": "debater", "display_name": "Alice"},
        {"role": "debater", "display_name": "Bob"},
    ],
}


def _debate(**kwargs: Any) -> Debate:
    defaults: dict[str, Any] = {
        "status": "completed",
        "config_json": dict(CONF),
        "moderation_status": "none",
        "moderation_json": {},
        "is_public": False,
    }
    return Debate(**{**defaults, **kwargs})


def _fake_complete(reply: str):
    def complete(*_args: Any, **_kwargs: Any) -> tuple[str, dict[str, Any]]:
        return reply, {"cost": 0.0001}

    return complete


def test_parse_moderation_ok_and_flagged():
    assert parse_moderation({"flag": False, "reason": "ignored"}) == {
        "flagged": False,
        "reason": "",
    }
    assert parse_moderation({"flag": True, "reason": "Targets a private person"}) == {
        "flagged": True,
        "reason": "Targets a private person",
    }
    assert parse_moderation({"flag": "true"}) == {"flagged": True, "reason": ""}


@pytest.mark.parametrize("payload", [None, "no", {}, {"flag": None}, {"flag": 3}])
def test_parse_moderation_rejects_unusable(payload: Any):
    assert parse_moderation(payload) is None


def test_moderation_messages_include_topic_and_description():
    messages = build_moderation_messages(topic="T1", description="D1", verdict_text="V1")
    body = messages[1]["content"]
    assert "T1" in body and "D1" in body and "V1" in body
    assert '"flag"' in body


def test_verdict_prompt_asks_for_moderation():
    messages = build_verdict_parse_messages(
        topic="t",
        language="English",
        verdict_text="Alice wins",
        debaters=[{"id": "participant_1", "name": "Alice"}],
        description="about t",
    )
    assert '"moderation"' in messages[1]["content"]
    assert "about t" in messages[1]["content"]


def test_structure_verdict_returns_moderation_separately(monkeypatch: pytest.MonkeyPatch):
    reply = json.dumps(
        {
            "winner": "Alice",
            "headline": "Alice wins.",
            "feedback": [],
            "moderation": {"flag": True, "reason": "Spam"},
        }
    )
    monkeypatch.setattr(llm, "complete", _fake_complete(reply))
    verdict, mod, usage = structure_verdict(CONF, "Alice wins", model="m")
    assert verdict["winner_name"] == "Alice"
    assert "moderation" not in verdict
    assert mod == {"flagged": True, "reason": "Spam", "source": "llm"}
    assert usage["cost"] == 0.0001


def test_structure_verdict_without_moderation_key(monkeypatch: pytest.MonkeyPatch):
    reply = json.dumps({"winner": "Bob", "headline": "Bob wins.", "feedback": []})
    monkeypatch.setattr(llm, "complete", _fake_complete(reply))
    _, mod, _ = structure_verdict(CONF, "Bob wins", model="m")
    assert mod is None


def test_check_debate_fails_closed(monkeypatch: pytest.MonkeyPatch):
    def boom(*_args: Any, **_kwargs: Any) -> tuple[str, dict[str, Any]]:
        raise RuntimeError("rate limited")

    monkeypatch.setattr(llm, "complete", boom)
    result, _ = check_debate(CONF, model="m")
    assert result == {"flagged": True, "reason": FALLBACK_REASON, "source": "fallback"}


def test_check_debate_ok(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(llm, "complete", _fake_complete('{"flag": false, "reason": ""}'))
    result, _ = check_debate(CONF, model="m")
    assert result == {"flagged": False, "reason": "", "source": "llm"}


def test_apply_check_sets_status():
    debate = _debate()
    apply_check(debate, {"flagged": False, "reason": "", "source": "llm"})
    assert debate.moderation_status == "approved"
    apply_check(debate, {"flagged": True, "reason": "Hate", "source": "llm"})
    assert debate.moderation_status == "flagged"
    assert debate.moderation_json["reason"] == "Hate"


def test_admin_decision_is_not_overwritten():
    debate = _debate(is_public=True)
    mark_admin_decision(debate, approved=False)
    assert debate.moderation_status == "rejected"
    assert debate.is_public is False
    apply_check(debate, {"flagged": False, "reason": "", "source": "llm"})
    assert debate.moderation_status == "rejected"


def test_wants_public():
    assert wants_public(_debate())
    legacy = _debate(config_json={"topic": "x"})
    assert not wants_public(legacy)
    legacy.moderation_json = {"publish_requested": True}
    assert wants_public(legacy)


def _turns(*, failed: bool = False, verdict: bool = True) -> list[Turn]:
    turns = [
        Turn(turn_type="opening", text="" if failed else "Point.", error="429" if failed else None)
    ]
    if verdict:
        turns.append(Turn(turn_type="verdict", text="Alice wins."))
    return turns


def test_should_auto_publish_needs_approval_wish_and_clean_run():
    assert should_auto_publish(_debate(moderation_status="approved", turns=_turns()))
    assert not should_auto_publish(_debate(moderation_status="flagged", turns=_turns()))
    no_wish = _debate(
        moderation_status="approved", config_json={"auto_publish": False}, turns=_turns()
    )
    assert not should_auto_publish(no_wish)
    failed = _debate(moderation_status="approved", turns=_turns(failed=True))
    assert not should_auto_publish(failed)
    no_verdict = _debate(moderation_status="approved", turns=_turns(verdict=False))
    assert not should_auto_publish(no_verdict)
    already = _debate(moderation_status="approved", turns=_turns(), is_public=True)
    assert not should_auto_publish(already)
