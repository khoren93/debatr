import json

import httpx
import pytest

from app.services.openrouter_client import (
    OpenRouterClient,
    OpenRouterError,
    merge_system_prompt,
    parse_error_body,
)

MESSAGES = [
    {"role": "system", "content": "Be brief."},
    {"role": "user", "content": "Hi"},
]


def _sse(*events: dict | str) -> bytes:
    lines = [": OPENROUTER PROCESSING"]
    for e in events:
        lines.append("data: " + (e if isinstance(e, str) else json.dumps(e)))
    lines.append("data: [DONE]")
    return ("\n\n".join(lines) + "\n\n").encode()


def _delta(text: str) -> dict:
    return {"choices": [{"delta": {"content": text}}]}


def _client(handler) -> OpenRouterClient:
    return OpenRouterClient(transport=httpx.MockTransport(handler))


async def _collect(client: OpenRouterClient, **kwargs):
    chunks = []
    async for chunk in client.stream_chat_completion("test/model", MESSAGES, **kwargs):
        chunks.append(chunk)
    return chunks


# --- pure helpers ----------------------------------------------------------


def test_merge_system_prompt_folds_into_first_user_message():
    merged = merge_system_prompt(MESSAGES)
    assert [m["role"] for m in merged] == ["user"]
    assert merged[0]["content"] == "Be brief.\n\nHi"
    # original untouched
    assert MESSAGES[1]["content"] == "Hi"


def test_merge_system_prompt_without_system_is_noop():
    msgs = [{"role": "user", "content": "x"}]
    assert merge_system_prompt(msgs) == msgs


def test_parse_error_body_extracts_message_and_provider():
    body = json.dumps(
        {
            "error": {
                "message": "Rate limited",
                "metadata": {"provider_name": "Acme", "raw": "slow down"},
            }
        }
    )
    err = parse_error_body(body, 429)
    assert err.status_code == 429
    assert err.provider == "Acme"
    assert "Rate limited" in err.message and "slow down" in err.message
    assert str(err) == "HTTP 429: Rate limited — slow down (provider: Acme)"


def test_parse_error_body_handles_non_json():
    err = parse_error_body(b"<html>Bad gateway</html>", 502)
    assert err.status_code == 502
    assert "Bad gateway" in err.message


# --- streaming -------------------------------------------------------------


async def test_stream_yields_deltas_and_usage():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        body = _sse(
            _delta("Hello"),
            _delta(", world"),
            {
                "choices": [{"delta": {}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 2, "cost": 0.001},
            },
        )
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    chunks = await _collect(_client(handler))
    assert "".join(c.delta for c in chunks) == "Hello, world"
    assert chunks[-1].usage == {"prompt_tokens": 5, "completion_tokens": 2, "cost": 0.001}

    assert len(requests) == 1
    payload = requests[0]
    assert payload["stream"] is True
    assert payload["usage"] == {"include": True}
    assert payload["messages"] == MESSAGES
    assert "max_tokens" not in payload


async def test_stream_names_the_model_that_answers():
    def handler(request: httpx.Request) -> httpx.Response:
        chunk = {**_delta("Hi"), "model": "upstage/solar-pro-3:free"}
        return httpx.Response(200, content=_sse(chunk))

    chunks = await _collect(_client(handler))
    assert [c.model for c in chunks] == ["upstage/solar-pro-3:free"]


async def test_stream_retries_with_merged_system_prompt_on_400():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        requests.append(payload)
        if any(m["role"] == "system" for m in payload["messages"]):
            return httpx.Response(400, json={"error": {"message": "system role unsupported"}})
        return httpx.Response(200, content=_sse(_delta("ok")))

    chunks = await _collect(_client(handler))
    assert [c.delta for c in chunks] == ["ok"]
    assert len(requests) == 2
    assert [m["role"] for m in requests[1]["messages"]] == ["user"]


async def test_stream_does_not_retry_on_non_400():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(402, json={"error": {"message": "Insufficient credits"}})

    with pytest.raises(OpenRouterError) as exc:
        await _collect(_client(handler))
    assert exc.value.status_code == 402
    assert "Insufficient credits" in str(exc.value)
    assert calls == 1


async def test_stream_raises_on_mid_stream_error():
    def handler(request: httpx.Request) -> httpx.Response:
        body = _sse(_delta("partial"), {"error": {"message": "Provider crashed"}})
        return httpx.Response(200, content=body)

    client = _client(handler)
    received = []
    with pytest.raises(OpenRouterError, match="Provider crashed"):
        async for chunk in client.stream_chat_completion("test/model", MESSAGES):
            received.append(chunk.delta)
    assert received == ["partial"]


async def test_validate_model_reports_errors():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": {"message": "No endpoints found"}})

    ok, error = await _client(handler).validate_model("missing/model")
    assert ok is False
    assert error is not None and "No endpoints found" in error


async def test_validate_model_ok_and_passes_max_tokens():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, content=_sse(_delta("pong")))

    ok, error = await _client(handler).validate_model("test/model")
    assert (ok, error) == (True, None)
    assert seen["max_tokens"] == 20


# --- account ---------------------------------------------------------------


async def test_get_credits_returns_remaining_balance():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer user-key"
        return httpx.Response(200, json={"data": {"total_credits": 10.0, "total_usage": 2.5}})

    credits, error = await _client(handler).get_credits(api_key="user-key")
    assert (credits, error) == (7.5, None)


async def test_get_credits_reports_invalid_key():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "Invalid key"}})

    credits, error = await _client(handler).get_credits()
    assert credits is None and error == "Invalid key"


async def test_get_models_filters_non_text_and_caches():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "a/free",
                        "name": "Free A",
                        "context_length": 8000,
                        "pricing": {"prompt": "0", "completion": "0"},
                    },
                    {
                        "id": "b/paid",
                        "name": "Paid B",
                        "context_length": 128000,
                        "pricing": {"prompt": "0.000001", "completion": "0.000002"},
                    },
                    {
                        "id": "c/image",
                        "name": "Img C",
                        "pricing": {},
                        "architecture": {"output_modalities": ["image"]},
                    },
                    {"id": "openrouter/auto", "pricing": {"prompt": "-1", "completion": "-1"}},
                    {"id": "d/odd", "pricing": {"prompt": "n/a", "completion": "0"}},
                ]
            },
        )

    client = _client(handler)
    models = await client.get_models()
    assert [m["id"] for m in models] == ["a/free", "b/paid"]
    assert models[0]["is_free"] is True and models[1]["is_free"] is False
    await client.get_models()
    assert calls == 1
