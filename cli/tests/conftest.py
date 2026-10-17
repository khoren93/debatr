"""A fake Debatr server on httpx.MockTransport, and an isolated config dir for every test."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from functools import partial
from typing import Any

import httpx
import pytest

from debatr.api import DebatrClient

DEBATE_ID = "0b6f7c1e-2a7d-4c43-9a43-6d7c4a7f1a11"
SITE = "https://debatr.test"
TOKEN = "debatr_" + "t" * 43


def participants() -> list[dict[str, Any]]:
    return [
        {
            "id": "participant_0",
            "name": "The Host",
            "role": "moderator",
            "model": "openrouter/free",
        },
        {"id": "participant_1", "name": "Nova", "role": "debater", "model": "acme/alpha"},
        {"id": "participant_2", "name": "Atlas", "role": "debater", "model": "acme/beta"},
    ]


def turn(seq: int, speaker_id: str, name: str, text: str, **extra: Any) -> dict[str, Any]:
    kind = {"participant_0": "moderator_intro", "judge": "verdict"}.get(speaker_id, "argument")
    return {
        "seq_index": seq,
        "round_id": "verdict" if speaker_id == "judge" else "round_1",
        "turn_type": kind,
        "speaker_role": "moderator" if speaker_id in ("participant_0", "judge") else "debater",
        "speaker_id": speaker_id,
        "speaker_name": name,
        "text": text,
        "error": None,
        "model_used": "acme/model",
        **extra,
    }


FINAL_TURNS = [
    turn(0, "participant_0", "The Host", "Welcome! Nova, please begin."),
    turn(1, "participant_1", "Nova", "Cats are independent."),
    turn(2, "participant_2", "Atlas", "Dogs are loyal."),
    turn(3, "judge", "⚖️ Verdict", "Nova wins on clarity."),
]

VERDICT = {
    "winner_id": "participant_1",
    "winner_name": "Nova",
    "is_draw": False,
    "headline": "Nova argued more clearly.",
    "feedback": [{"speaker_id": "participant_2", "name": "Atlas", "text": "Needed evidence."}],
}


def detail(
    status: str = "running", turns: list[dict[str, Any]] | None = None, **extra: Any
) -> dict[str, Any]:
    done = status == "completed"
    return {
        "id": DEBATE_ID,
        "status": status,
        "title": "Cats or dogs?",
        "error_message": None,
        "created_at": "2026-10-17T10:00:00Z",
        "settings": {
            "topic": "Cats or dogs?",
            "language": "English",
            "num_rounds": 1,
            "length_preset": "short",
            "intensity": 5,
            "output_style": "markdown",
        },
        "totals": {"cost": 0.0012 if done else 0, "tokens_in": 10, "tokens_out": 20},
        "participants": participants(),
        "turns": FINAL_TURNS if turns is None and done else (turns or []),
        "verdict": VERDICT if done else None,
        "share_url": None,
        "is_public": False,
        "media_plan": None,
        **extra,
    }


def sse(*events: tuple[str, dict[str, Any]]) -> bytes:
    lines = [": ping"]
    for name, data in events:
        lines += [f"event: {name}", f"data: {json.dumps(data)}", ""]
    return ("\n".join(lines) + "\n").encode()


LIVE_EVENTS = sse(
    ("connected", {"debate_id": DEBATE_ID, "status": "running"}),
    (
        "turn_started",
        {
            "seq_index": 0,
            "speaker_name": "The Host",
            "turn_type": "moderator_intro",
            "round_id": "round_1",
        },
    ),
    ("turn_delta", {"seq_index": 0, "delta": "Welcome! "}),
    ("turn_delta", {"seq_index": 0, "delta": "Nova, please begin."}),
    ("turn_completed", FINAL_TURNS[0]),
    (
        "turn_started",
        {"seq_index": 1, "speaker_name": "Nova", "turn_type": "argument", "round_id": "round_1"},
    ),
    ("turn_delta", {"seq_index": 1, "delta": "Cats are independent. [vis"}),
    ("turn_delta", {"seq_index": 1, "delta": "ual: a cat alone]"}),
    ("turn_completed", FINAL_TURNS[1]),
    (
        "turn_started",
        {"seq_index": 2, "speaker_name": "Atlas", "turn_type": "argument", "round_id": "round_1"},
    ),
    ("turn_delta", {"seq_index": 2, "delta": "Dogs are loyal."}),
    ("turn_completed", FINAL_TURNS[2]),
    (
        "turn_started",
        {
            "seq_index": 3,
            "speaker_name": "⚖️ Verdict",
            "turn_type": "verdict",
            "round_id": "verdict",
        },
    ),
    ("turn_delta", {"seq_index": 3, "delta": "Nova wins on clarity."}),
    ("turn_completed", FINAL_TURNS[3]),
    ("verdict_ready", {"debate_id": DEBATE_ID, "verdict": VERDICT}),
    ("debate_completed", {"debate_id": DEBATE_ID, "status": "completed"}),
)

Handler = Callable[[httpx.Request], httpx.Response]


class FakeServer:
    """Routes by "METHOD /path" (under /api). A route maps to a response or a handler; a list of
    responses is served in order, repeating the last."""

    def __init__(self) -> None:
        self.routes: dict[str, Any] = {}
        self.requests: list[httpx.Request] = []

    def on(self, route: str, response: Any) -> None:
        self.routes[route] = response

    def calls(self, route: str) -> list[httpx.Request]:
        method, path = route.split(" ", 1)
        return [r for r in self.requests if r.method == method and r.url.path == f"/api{path}"]

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        key = f"{request.method} {request.url.path.removeprefix('/api')}"
        if key not in self.routes:
            return httpx.Response(404, json={"detail": f"no route {key}"})
        route = self.routes[key]
        if isinstance(route, list):
            route = route.pop(0) if len(route) > 1 else route[0]
        if callable(route):
            return route(request)
        if isinstance(route, httpx.Response):
            return route
        if isinstance(route, bytes):
            return httpx.Response(200, content=route, headers={"content-type": "text/event-stream"})
        return httpx.Response(200, json=route)

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def client_factory(self) -> Callable[..., DebatrClient]:
        return partial(DebatrClient, transport=self.transport)


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch) -> Iterator[None]:
    monkeypatch.setenv("DEBATR_CONFIG_DIR", str(tmp_path / "config"))
    for name in (
        "DEBATR_TOKEN",
        "DEBATR_URL",
        "DEBATR_OPENROUTER_KEY",
        "DEBATR_ELEVENLABS_KEY",
        "DEBATR_MAX_COST_USD",
    ):
        monkeypatch.delenv(name, raising=False)
    yield


@pytest.fixture
def server() -> FakeServer:
    return FakeServer()


def free_estimate(**extra: Any) -> dict[str, Any]:
    return {
        "turns": 4,
        "duration_ms": 90_000,
        "credits_cost_usd": 0.0,
        "own_key": False,
        "credits_before": 5.0,
        "credits_after": 5.0,
        "token_budget_usd": None,
        "paid_models": [],
        "sufficient": True,
        **extra,
    }
