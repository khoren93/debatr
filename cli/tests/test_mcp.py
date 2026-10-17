"""The MCP server over the SDK's in-process client, against the fake Debatr server."""

import json
from typing import Any

import httpx
import pytest
from conftest import DEBATE_ID, LIVE_EVENTS, SITE, TOKEN, FakeServer, detail, free_estimate
from mcp import Client

from debatr import mcp_server
from debatr.config import Settings
from debatr.mcp_server import Clients, create_server


def make(server: FakeServer, monkeypatch, token: str | None = TOKEN, cap: float = 1.0):
    monkeypatch.setattr(mcp_server, "DebatrClient", server.client_factory())
    clients = Clients(
        lambda: Settings(url=SITE, token=token, token_source="env" if token else None)
    )
    return create_server(clients, cap=cap, website=SITE)


def structured(result: Any) -> dict[str, Any]:
    assert not result.is_error, result.content
    return result.structured_content


async def test_tools_are_described(server: FakeServer, monkeypatch):
    async with Client(make(server, monkeypatch)) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    assert set(tools) == {
        "get_account",
        "list_models",
        "estimate_debate",
        "start_debate",
        "get_debate",
        "stop_debate",
        "list_my_debates",
        "search_gallery",
        "get_leaderboard",
        "publish_debate",
    }
    assert tools["get_debate"].annotations.read_only_hint is True
    assert tools["start_debate"].annotations.read_only_hint is False
    schema = tools["start_debate"].input_schema
    assert schema["required"] == ["topic"]
    assert "ctx" not in tools["get_debate"].input_schema["properties"]


async def test_start_debate_is_private_and_capped(server: FakeServer, monkeypatch):
    server.on("POST /debates/estimate", free_estimate(credits_cost_usd=0.3))
    server.on("POST /debates", {"debate_id": DEBATE_ID})
    server.on(f"GET /debates/{DEBATE_ID}", detail("queued"))
    async with Client(make(server, monkeypatch, cap=1.0)) as client:
        out = structured(
            await client.call_tool(
                "start_debate",
                {
                    "topic": "Cats or dogs?",
                    "debaters": [{"model": "acme/alpha", "name": "Kit"}, {"model": "acme/beta"}],
                },
            )
        )
        assert out["debate_id"] == DEBATE_ID and out["turns_total"] == 4
        assert out["url"] == f"{SITE}/debate/{DEBATE_ID}"
        body = json.loads(server.calls("POST /debates")[0].content)
        assert body["auto_publish"] is False
        assert [p["display_name"] for p in body["participants"]] == ["The Host", "Kit", "Nova"]

        refused = await client.call_tool("start_debate", {"topic": "Q?", "max_cost_usd": 0.1})
        assert refused.is_error and "above the limit of $0.10" in refused.content[0].text

    server.on("POST /debates/estimate", free_estimate(credits_cost_usd=2.5))
    async with Client(make(server, monkeypatch, cap=1.0)) as client:
        refused = await client.call_tool("start_debate", {"topic": "Q?", "max_cost_usd": 5})
    assert refused.is_error and "DEBATR_MAX_COST_USD" in refused.content[0].text
    assert len(server.calls("POST /debates")) == 1


async def test_get_debate_waits_and_reports_progress(server: FakeServer, monkeypatch):
    server.on(f"GET /debates/{DEBATE_ID}", [detail("running"), detail("completed")])
    server.on(f"GET /debates/{DEBATE_ID}/stream", LIVE_EVENTS)
    progress: list[tuple[float, float | None, str | None]] = []

    async def on_progress(done: float, total: float | None, message: str | None) -> None:
        progress.append((done, total, message))

    async with Client(make(server, monkeypatch)) as client:
        result = await client.call_tool(
            "get_debate",
            {"debate_id": DEBATE_ID, "wait_seconds": 30},
            progress_callback=on_progress,
        )
    out = structured(result)
    assert out["status"] == "completed" and out["verdict"]["winner"] == "Nova"
    assert "### Nova · PRO" in out["transcript"]
    assert "next" not in out
    assert [p[0] for p in progress] == [1, 2, 3, 4] and progress[-1][1] == 4
    assert progress[1][2] == "2/4 turns: Nova spoke"


async def test_get_debate_still_running(server: FakeServer, monkeypatch):
    server.on(f"GET /debates/{DEBATE_ID}", detail("running"))
    async with Client(make(server, monkeypatch)) as client:
        out = structured(
            await client.call_tool(
                "get_debate",
                {"debate_id": DEBATE_ID, "wait_seconds": 0, "include_transcript": False},
            )
        )
    assert out["status"] == "running" and "get_debate again" in out["next"]
    assert "transcript" not in out


async def test_public_debates_need_no_login(server: FakeServer, monkeypatch):
    server.on("GET /gallery/k3m9xq2p7w", detail("completed", share_url=f"{SITE}/d/k3m9xq2p7w"))
    server.on(
        "GET /gallery",
        {
            "items": [
                {
                    "slug": "k3m9xq2p7w",
                    "topic": "Tabs?",
                    "participants": [{"role": "debater", "model": "acme/a"}],
                }
            ],
            "total": 1,
        },
    )
    async with Client(make(server, monkeypatch, token=None)) as client:
        found = structured(await client.call_tool("search_gallery", {"query": "tabs"}))
        assert found["debates"][0]["url"] == f"{SITE}/d/k3m9xq2p7w"
        read = structured(
            await client.call_tool("get_debate", {"debate_id": f"{SITE}/d/k3m9xq2p7w"})
        )
        assert read["url"] == f"{SITE}/d/k3m9xq2p7w"
        locked = await client.call_tool("get_account", {})
    assert locked.is_error and "debatr login" in locked.content[0].text


async def test_api_errors_reach_the_agent(server: FakeServer, monkeypatch):
    server.on(
        f"POST /debates/{DEBATE_ID}/stop",
        httpx.Response(409, json={"detail": "Debate is already completed"}),
    )
    async with Client(make(server, monkeypatch)) as client:
        result = await client.call_tool("stop_debate", {"debate_id": DEBATE_ID})
    assert result.is_error and "Debate is already completed" in result.content[0].text


async def test_list_models_filters(server: FakeServer, monkeypatch):
    server.on(
        "GET /models",
        {
            "data": [
                {
                    "id": "acme/claude-x",
                    "name": "Claude X",
                    "is_free": False,
                    "created": 2,
                    "pricing": {"prompt": "0.000003", "completion": "0.000015"},
                },
                {
                    "id": "acme/tiny:free",
                    "name": "Tiny",
                    "is_free": True,
                    "created": 1,
                    "pricing": {"prompt": "0", "completion": "0"},
                },
            ]
        },
    )
    async with Client(make(server, monkeypatch)) as client:
        out = structured(await client.call_tool("list_models", {"search": "claude"}))
        assert [m["id"] for m in out["models"]] == ["acme/claude-x"]
        assert out["models"][0]["output_usd_per_mtok"] == 15.0
        free = structured(await client.call_tool("list_models", {"free_only": True}))
    assert [m["id"] for m in free["models"]] == ["acme/tiny:free"]


def test_cap_from_environment(monkeypatch):
    monkeypatch.setenv("DEBATR_MAX_COST_USD", "2.5")
    assert mcp_server.max_cost_cap() == 2.5
    monkeypatch.setenv("DEBATR_MAX_COST_USD", "lots")
    assert mcp_server.max_cost_cap() == mcp_server.DEFAULT_MAX_COST


@pytest.mark.parametrize("bad", [{"topic": ""}, {"topic": "Q?", "rounds": 11}])
async def test_invalid_arguments(server: FakeServer, monkeypatch, bad):
    async with Client(make(server, monkeypatch)) as client:
        result = await client.call_tool("start_debate", bad)
    assert result.is_error
