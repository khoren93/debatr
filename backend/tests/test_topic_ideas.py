import uuid
from typing import Any

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.api import routes_topics
from app.core.config import settings
from app.models.models import User
from app.schemas.schemas import TopicIdeasIn
from app.services import topic_ideas
from app.services.openrouter_client import OpenRouterClient, OpenRouterError
from app.services.topic_ideas import build_messages, parse_ideas


def test_the_prompt_follows_the_format() -> None:
    debate = build_messages("  vibe coding is dead?  ", "debate", "English")
    assert "debate a motion on camera" in debate[0]["content"]
    assert '"""vibe coding is dead?"""' in debate[1]["content"]
    assert 'usually "Should ...?" or "Is ...?"' in debate[1]["content"]
    assert "Write 3 different debate topics" in debate[1]["content"]
    battle = build_messages("vibe coding is dead?", "rap_battle", "Russian")
    assert "rap verses" in battle[0]["content"]
    assert "Write 3 different rap battle topics" in battle[1]["content"]
    assert "A or B?" in battle[1]["content"]
    assert "(Russian when that is unclear)" in battle[1]["content"]
    # An unknown format writes debate topics.
    assert build_messages("x", "court", "English") == build_messages("x", "debate", "English")


def test_parse_ideas_tidies_and_limits() -> None:
    reply = (
        "```json\n"
        '{"topics": ["1. “Is vibe coding killing programming?”", "Is vibe coding killing '
        'programming?", "Why?", "2026: the year vibe coding won?", "' + "x" * 151 + '", '
        '"- Vibe coding or real coding?", "Should juniors learn to code by hand?"]}\n```'
    )
    assert parse_ideas(reply) == [
        "Is vibe coding killing programming?",
        "2026: the year vibe coding won?",  # a number at the start is part of the topic
        "Vibe coding or real coding?",
    ]
    assert parse_ideas('{"topics": []}') == []  # refused
    with pytest.raises(ValueError):
        parse_ideas("Sorry, I cannot help with that.")
    with pytest.raises(ValueError):
        parse_ideas('{"ideas": "none"}')


def test_suggest_books_the_call_on_the_account(
    monkeypatch: pytest.MonkeyPatch, usage_rows: list
) -> None:
    asked: list[dict[str, Any]] = []

    async def chat_completion(self: Any, model: str, messages: list, **kw: Any) -> dict:
        asked.append({"model": model, **kw})
        return {
            "model": model,
            "choices": [{"message": {"content": '{"topics": ["Vibe coding or real coding?"]}'}}],
            "usage": {"prompt_tokens": 300, "completion_tokens": 40, "cost": 0.0001},
        }

    monkeypatch.setattr(OpenRouterClient, "chat_completion", chat_completion)
    user_id = str(uuid.uuid4())
    found = topic_ideas.suggest("test/writer", "vibe coding", "rap_battle", "English", user_id)
    assert found == ["Vibe coding or real coding?"]
    assert asked[0]["model"] == "test/writer"
    (row,) = usage_rows
    assert row.purpose == "topic_ideas"
    assert row.key_owner == "system"
    assert str(row.user_id) == user_id
    assert row.debate_id is None


def _request() -> Request:
    return Request({"type": "http", "method": "POST", "headers": [], "client": ("1.2.3.4", 1)})


async def test_the_route_limits_per_account_and_reports_failures(
    monkeypatch: pytest.MonkeyPatch, levers: dict
) -> None:
    user = User(id=uuid.uuid4(), email="a@example.com")
    limits: list[dict[str, Any]] = []

    async def limit(request: Request, **kw: Any) -> None:
        limits.append(kw)

    monkeypatch.setattr(routes_topics, "enforce_limit", limit)
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "sk-test")
    levers["topic_model"] = "test/writer"  # the trending lists' writer writes the ideas too
    calls: list[tuple] = []

    def suggest(*args: Any) -> list[str]:
        calls.append(args)
        return ["Vibe coding or real coding?"]

    monkeypatch.setattr(topic_ideas, "suggest", suggest)
    body = TopicIdeasIn(text="vibe coding is dead?", format="rap_battle")
    out = await routes_topics.ideas(body, _request(), user)
    assert out.format == "rap_battle"
    assert out.ideas == ["Vibe coding or real coding?"]
    assert calls == [("test/writer", "vibe coding is dead?", "rap_battle", "English", str(user.id))]
    assert limits[0]["key"] == str(user.id)
    assert limits[0]["limit"] == settings.TOPIC_IDEAS_PER_HOUR

    def broken(*args: Any) -> list[str]:
        raise OpenRouterError("upstream 500")

    monkeypatch.setattr(topic_ideas, "suggest", broken)
    with pytest.raises(HTTPException) as failed:
        await routes_topics.ideas(body, _request(), user)
    assert failed.value.status_code == 502

    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", None)
    with pytest.raises(HTTPException) as off:
        await routes_topics.ideas(body, _request(), user)
    assert off.value.status_code == 503
