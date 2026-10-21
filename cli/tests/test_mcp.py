"""The MCP server over the SDK's in-process client, against the fake Debatr server."""

import json
from typing import Any

import httpx
import pytest
from conftest import (
    DEBATE_ID,
    FORMATS,
    LIVE_EVENTS,
    SITE,
    TOKEN,
    FakeServer,
    battle_detail,
    detail,
    free_estimate,
)
from mcp import Client
from mcp_types import CallToolResult, TextContent

from debatr import mcp_server
from debatr.config import Settings
from debatr.mcp_server import Clients, create_server


def make(server: FakeServer, monkeypatch, token: str | None = TOKEN, cap: float = 1.0):
    monkeypatch.setattr(mcp_server, "DebatrClient", server.client_factory())
    clients = Clients(
        lambda: Settings(url=SITE, token=token, token_source="env" if token else None)
    )
    return create_server(clients, cap=cap, website=SITE)


def structured(result: CallToolResult) -> dict[str, Any]:
    assert not result.is_error, result.content
    assert result.structured_content is not None
    return result.structured_content


def error_text(result: CallToolResult) -> str:
    assert result.is_error
    first = result.content[0]
    assert isinstance(first, TextContent)
    return first.text


async def test_tools_are_described(server: FakeServer, monkeypatch):
    async with Client(make(server, monkeypatch)) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    assert set(tools) == {
        "get_account",
        "list_formats",
        "list_models",
        "estimate_debate",
        "start_debate",
        "get_debate",
        "stop_debate",
        "resume_debate",
        "list_my_debates",
        "search_gallery",
        "get_leaderboard",
        "publish_debate",
        "generate_cover",
    }
    read_only = tools["get_debate"].annotations
    writes = tools["start_debate"].annotations
    assert read_only is not None and read_only.read_only_hint is True
    assert writes is not None and writes.read_only_hint is False
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
        assert "above the limit of $0.10" in error_text(refused)

    server.on("POST /debates/estimate", free_estimate(credits_cost_usd=2.5))
    async with Client(make(server, monkeypatch, cap=1.0)) as client:
        refused = await client.call_tool("start_debate", {"topic": "Q?", "max_cost_usd": 5})
    assert "DEBATR_MAX_COST_USD" in error_text(refused)
    assert len(server.calls("POST /debates")) == 1


async def test_get_debate_waits_and_reports_progress(server: FakeServer, monkeypatch):
    server.on(f"GET /debates/{DEBATE_ID}", [detail("running"), detail("completed")])
    server.on(f"GET /debates/{DEBATE_ID}/stream", LIVE_EVENTS)
    updates: list[tuple[float, float | None, str | None]] = []

    async def on_progress(progress: float, total: float | None, message: str | None) -> None:
        updates.append((progress, total, message))

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
    assert [u[0] for u in updates] == [1, 2, 3, 4] and updates[-1][1] == 4
    assert updates[1][2] == "2/4 turns: Nova spoke"


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
                    "language_code": "en",
                    "participants": [{"role": "debater", "model": "acme/a"}],
                }
            ],
            "total": 1,
        },
    )
    async with Client(make(server, monkeypatch, token=None)) as client:
        found = structured(
            await client.call_tool("search_gallery", {"query": "tabs", "language": "en"})
        )
        assert found["debates"][0]["url"] == f"{SITE}/d/k3m9xq2p7w"
        assert found["debates"][0]["language"] == "en"
        assert server.calls("GET /gallery")[0].url.params["language"] == "en"
        read = structured(
            await client.call_tool("get_debate", {"debate_id": f"{SITE}/d/k3m9xq2p7w"})
        )
        assert read["url"] == f"{SITE}/d/k3m9xq2p7w"
        locked = await client.call_tool("get_account", {})
    assert "debatr login" in error_text(locked)


async def test_api_errors_reach_the_agent(server: FakeServer, monkeypatch):
    server.on(
        f"POST /debates/{DEBATE_ID}/stop",
        httpx.Response(409, json={"detail": "Debate is already completed"}),
    )
    async with Client(make(server, monkeypatch)) as client:
        result = await client.call_tool("stop_debate", {"debate_id": DEBATE_ID})
    assert "Debate is already completed" in error_text(result)


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


async def test_resume_debate_is_capped_and_hinted(server: FakeServer, monkeypatch):
    failed = detail("error", error_message="Nova (acme/alpha) could not answer", is_owner=True)
    server.on(f"GET /debates/{DEBATE_ID}", [failed, detail("queued")])
    server.on(f"POST /debates/{DEBATE_ID}/resume/estimate", free_estimate(from_turn=1))
    server.on(f"POST /debates/{DEBATE_ID}/resume", {"debate_id": DEBATE_ID, "status": "queued"})
    async with Client(make(server, monkeypatch, cap=1.0)) as client:
        seen = structured(
            await client.call_tool("get_debate", {"debate_id": DEBATE_ID, "wait_seconds": 0})
        )
        assert seen["status"] == "error" and "resume_debate" in seen["next"]
        out = structured(await client.call_tool("resume_debate", {"debate_id": DEBATE_ID}))
        assert out["status"] == "queued" and out["resumed_from_turn"] == 2

        server.on(
            f"POST /debates/{DEBATE_ID}/resume/estimate",
            free_estimate(from_turn=1, credits_cost_usd=3.0),
        )
        refused = await client.call_tool("resume_debate", {"debate_id": DEBATE_ID})
    assert "DEBATR_MAX_COST_USD" in error_text(refused)
    assert len(server.calls(f"POST /debates/{DEBATE_ID}/resume")) == 1


async def test_agents_can_stage_a_rap_battle(server: FakeServer, monkeypatch):
    server.on("GET /formats", [FORMATS])  # one response: the list
    server.on("POST /debates/estimate", free_estimate(credits_cost_usd=0.6))
    server.on("POST /debates", {"debate_id": DEBATE_ID})
    server.on(f"GET /debates/{DEBATE_ID}", battle_detail("queued"))
    async with Client(make(server, monkeypatch, cap=1.0)) as client:
        formats = structured(await client.call_tool("list_formats", {}))["formats"]
        battle = next(f for f in formats if f["id"] == "rap_battle")
        assert battle["premium_voices_only"] and battle["default_flows"] == ["gritty", "sharp"]
        assert battle["flows"][0] == {"id": "gritty", "sound": "Gritty baritone: Deep, slow"}

        out = structured(
            await client.call_tool(
                "start_debate",
                {
                    "topic": "Tabs or spaces?",
                    "format": "rap_battle",
                    "audio": True,
                    "flows": ["smooth", "sharp"],
                },
            )
        )
        assert out["turns_total"] == 6
        body = json.loads(server.calls("POST /debates")[0].content)
        assert body["format"] == "rap_battle" and body["media_plan"]["provider"] == "elevenlabs"
        assert body["media_plan"]["flows"]["participant_1"] == "smooth"

        three = await client.call_tool(
            "start_debate",
            {"topic": "Q?", "format": "rap_battle", "debaters": [{}, {}, {}]},
        )
        assert "exactly two rappers" in error_text(three)

        server.on(f"GET /debates/{DEBATE_ID}", battle_detail())
        done = structured(await client.call_tool("get_debate", {"debate_id": DEBATE_ID}))
        assert done["format"] == "rap_battle"
        assert done["verdict"]["rounds"][0]["scores"][0] == {
            "speaker": "Nova",
            "speaker_id": "participant_1",
            "score": 8,
        }


async def test_generate_cover_is_capped_and_reported(server: FakeServer, monkeypatch):
    cover = {"status": "none", "current": None, "price_usd": 0.042, "reason": None}
    server.on(f"GET /debates/{DEBATE_ID}", detail("completed", cover=cover))
    server.on(f"POST /debates/{DEBATE_ID}/cover", {**cover, "status": "queued"})
    async with Client(make(server, monkeypatch, cap=1.0)) as client:
        out = structured(
            await client.call_tool("generate_cover", {"debate_id": DEBATE_ID, "hook": "Who wins?"})
        )
        assert out["cover_status"] == "queued" and out["price_usd"] == 0.042
        assert json.loads(server.calls(f"POST /debates/{DEBATE_ID}/cover")[0].content) == {
            "hook": "Who wins?"
        }
    async with Client(make(server, monkeypatch, cap=0.01)) as client:
        refused = await client.call_tool("generate_cover", {"debate_id": DEBATE_ID})
        assert "above the limit" in error_text(refused)
