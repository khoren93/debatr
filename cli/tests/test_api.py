import httpx
import pytest
from conftest import DEBATE_ID, LIVE_EVENTS, SITE, TOKEN, FakeServer

from debatr.api import ApiError, DebatrClient, parse_sse


async def lines(*items: str):
    for item in items:
        yield item


async def test_parse_sse():
    events = [
        e
        async for e in parse_sse(
            lines(
                ": ping",
                "event: a",
                'data: {"x": 1}',
                "",
                "data: one",
                "data: two",
                "",
                "event: tail",
                "data: {}",
            )
        )
    ]
    assert events == [("a", '{"x": 1}'), ("message", "one\ntwo"), ("tail", "{}")]


async def test_sends_the_token_and_a_user_agent(server: FakeServer):
    server.on("GET /auth/me", {"email": "a@b.co"})
    async with DebatrClient(SITE, TOKEN, transport=server.transport) as client:
        assert await client.me() == {"email": "a@b.co"}
    request = server.calls("GET /auth/me")[0]
    assert request.headers["authorization"] == f"Bearer {TOKEN}"
    assert request.headers["user-agent"].startswith("debatr-cli/")


@pytest.mark.parametrize(
    ("response", "token", "message"),
    [
        (
            httpx.Response(401, json={"detail": "Invalid or revoked API token"}),
            TOKEN,
            "Invalid or revoked API token. Run `debatr login`",
        ),
        (
            httpx.Response(401, json={"detail": "Sign in to continue"}),
            None,
            "Not signed in: run `debatr login`",
        ),
        (
            httpx.Response(402, json={"detail": "Insufficient credits"}),
            TOKEN,
            "Insufficient credits",
        ),
        (
            httpx.Response(
                422,
                json={"detail": [{"loc": ["body", "num_rounds"], "msg": "Value error, too many"}]},
            ),
            TOKEN,
            "num_rounds: too many",
        ),
        (
            httpx.Response(502, text="<html>Bad gateway</html>"),
            TOKEN,
            "The server had a problem (502)",
        ),
    ],
)
async def test_error_messages(server: FakeServer, response, token, message):
    server.on("GET /debates", response)
    async with DebatrClient(SITE, token, transport=server.transport) as client:
        with pytest.raises(ApiError) as err:
            await client.list_debates()
    assert err.value.message.startswith(message)
    assert err.value.status == response.status_code


async def test_network_errors_and_non_json():
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    async with DebatrClient(SITE, transport=httpx.MockTransport(refuse)) as client:
        with pytest.raises(ApiError, match=r"Could not reach https://debatr\.test"):
            await client.models()
    html = httpx.MockTransport(lambda r: httpx.Response(200, text="<html></html>"))
    async with DebatrClient(SITE, transport=html) as client:
        with pytest.raises(ApiError, match="did not answer like a Debatr server"):
            await client.models()


async def test_events(server: FakeServer):
    server.on(f"GET /debates/{DEBATE_ID}/stream", LIVE_EVENTS)
    async with DebatrClient(SITE, TOKEN, transport=server.transport) as client:
        events = [e async for e in client.events(DEBATE_ID)]
    assert events[0].event == "connected"
    assert events[-1].event == "debate_completed"
    assert sum(e.event == "turn_delta" for e in events) == 6


async def test_download(server: FakeServer, tmp_path):
    server.on("GET /media/files/x/full.mp3", httpx.Response(200, content=b"ID3data"))
    dest = tmp_path / "out.mp3"
    seen: list[int] = []
    async with DebatrClient(SITE, transport=server.transport) as client:
        await client.download(
            "/api/media/files/x/full.mp3?v=1", dest, lambda done, total: seen.append(done)
        )
    assert dest.read_bytes() == b"ID3data" and seen[-1] == 7

    server.on("GET /media/files/x/full.mp3", httpx.Response(404, json={"detail": "Not Found"}))
    async with DebatrClient(SITE, transport=server.transport) as client:
        with pytest.raises(ApiError):
            await client.download("/api/media/files/x/full.mp3", tmp_path / "missing.mp3")
    assert not (tmp_path / "missing.mp3").exists()
    assert not list(tmp_path.glob(".*.part"))
