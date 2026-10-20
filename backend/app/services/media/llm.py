"""Small synchronous helper around the OpenRouter client for worker-side LLM calls.

Every call names its `purpose` and is booked in `provider_usage` (app.services.usage), failed
ones included, on the debate of the running job.
"""

import asyncio
import base64
import json
import re
import time
from typing import Any

import httpx

from app.services import usage as usage_log
from app.services.openrouter_client import OpenRouterClient, OpenRouterError


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _failed(
    purpose: str, model: str, api_key: str | None, started: float, error: Exception
) -> None:
    status = error.status_code if isinstance(error, OpenRouterError) else None
    timed_out = isinstance(error, TimeoutError | httpx.TimeoutException)
    usage_log.record(
        purpose,
        model=model,
        key=usage_log.key_owner(api_key),
        ok=False,
        error_kind=usage_log.classify_error(status, timed_out=timed_out),
        duration_ms=_elapsed_ms(started),
        meta={"error": str(error)[:300]},
    )


def complete(
    model: str,
    messages: list[dict[str, Any]],
    *,
    purpose: str,
    api_key: str | None = None,
    max_tokens: int | None = None,
) -> tuple[str, dict[str, Any]]:
    """Collect a full (non-streamed to the UI) completion. Returns (text, usage)."""

    async def run() -> tuple[str, dict[str, Any], str]:
        client = OpenRouterClient()
        text = ""
        usage: dict[str, Any] = {}
        answered = model
        async for chunk in client.stream_chat_completion(
            model, messages, api_key=api_key, max_tokens=max_tokens
        ):
            text += chunk.delta
            if chunk.usage:
                usage = chunk.usage
            if chunk.model:
                answered = chunk.model
        return text, usage, answered

    started = time.monotonic()
    try:
        text, usage, answered = asyncio.run(run())
    except Exception as e:
        _failed(purpose, model, api_key, started, e)
        raise
    usage_log.record(
        purpose,
        model=answered,
        key=usage_log.key_owner(api_key),
        usage=usage,
        ok=bool(text.strip()),
        error_kind=None if text.strip() else "empty",
        duration_ms=_elapsed_ms(started),
    )
    return text, usage


def complete_message(
    model: str,
    messages: list[dict[str, Any]],
    *,
    purpose: str,
    api_key: str | None = None,
    max_tokens: int | None = None,
    read_timeout: float | None = None,
) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    """Non-streamed completion. Returns (text, annotations, usage); annotations carry the web
    search citations of `:online` / search models."""
    started = time.monotonic()
    try:
        body = asyncio.run(
            OpenRouterClient().chat_completion(
                model, messages, api_key=api_key, max_tokens=max_tokens, read_timeout=read_timeout
            )
        )
    except Exception as e:
        _failed(purpose, model, api_key, started, e)
        raise
    choices = body.get("choices") or [{}]
    message = (choices[0] or {}).get("message") or {}
    annotations = [a for a in message.get("annotations") or [] if isinstance(a, dict)]
    text = str(message.get("content") or "")
    usage = body.get("usage") or {}
    usage_log.record(
        purpose,
        model=str(body.get("model") or model),
        key=usage_log.key_owner(api_key),
        usage=usage,
        ok=bool(text.strip()),
        error_kind=None if text.strip() else "empty",
        duration_ms=_elapsed_ms(started),
    )
    return text, annotations, usage


def generate_image(
    model: str,
    prompt: str,
    *,
    purpose: str = "image",
    aspect_ratio: str = "16:9",
    resolution: str | None = "1K",
    fallback_cost: float | None = None,
    api_key: str | None = None,
    quality: str | None = None,
    references: list[str] | None = None,
    timeout: float = 180.0,
) -> tuple[bytes, dict[str, Any]]:
    """One generated picture (on the system key unless `api_key`). Returns (image bytes,
    usage). `fallback_cost` is booked when the response carries no cost; `references` are data
    URLs the model works from."""
    started = time.monotonic()
    try:
        body = asyncio.run(
            OpenRouterClient().generate_image(
                model,
                prompt,
                aspect_ratio=aspect_ratio,
                resolution=resolution,
                api_key=api_key,
                quality=quality,
                references=references,
                read_timeout=timeout,
            )
        )
        image = body["data"][0]
        data = base64.b64decode(str(image.get("b64_json") or ""))
    except Exception as e:
        _failed(purpose, model, api_key, started, e)
        raise
    usage = body.get("usage") or {}
    usage_log.record(
        purpose,
        model=model,
        key=usage_log.key_owner(api_key),
        usage=usage,
        cost_usd=None if usage.get("cost") is not None else fallback_cost,
        ok=bool(data),
        error_kind=None if data else "empty",
        duration_ms=_elapsed_ms(started),
    )
    return data, usage


def extract_json(text: str) -> Any:
    """Parse the first JSON object/array in a model reply (tolerates code fences and prose)."""
    cleaned = re.sub(r"```(?:json)?", "", text).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    start = min((i for i in (cleaned.find("{"), cleaned.find("[")) if i >= 0), default=-1)
    if start < 0:
        raise ValueError("No JSON found in model reply")
    opener = cleaned[start]
    closer = "}" if opener == "{" else "]"
    end = cleaned.rfind(closer)
    if end <= start:
        raise ValueError("Unterminated JSON in model reply")
    return json.loads(cleaned[start : end + 1])
