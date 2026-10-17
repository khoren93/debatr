"""Small synchronous helper around the OpenRouter client for worker-side LLM calls."""

import asyncio
import base64
import json
import re
from typing import Any

from app.services.openrouter_client import OpenRouterClient


def complete(
    model: str,
    messages: list[dict[str, Any]],
    *,
    api_key: str | None = None,
    max_tokens: int | None = None,
) -> tuple[str, dict[str, Any]]:
    """Collect a full (non-streamed to the UI) completion. Returns (text, usage)."""

    async def run() -> tuple[str, dict[str, Any]]:
        client = OpenRouterClient()
        text = ""
        usage: dict[str, Any] = {}
        async for chunk in client.stream_chat_completion(
            model, messages, api_key=api_key, max_tokens=max_tokens
        ):
            text += chunk.delta
            if chunk.usage:
                usage = chunk.usage
        return text, usage

    return asyncio.run(run())


def complete_message(
    model: str,
    messages: list[dict[str, Any]],
    *,
    api_key: str | None = None,
    max_tokens: int | None = None,
    read_timeout: float | None = None,
) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    """Non-streamed completion. Returns (text, annotations, usage); annotations carry the web
    search citations of `:online` / search models."""
    body = asyncio.run(
        OpenRouterClient().chat_completion(
            model, messages, api_key=api_key, max_tokens=max_tokens, read_timeout=read_timeout
        )
    )
    choices = body.get("choices") or [{}]
    message = (choices[0] or {}).get("message") or {}
    annotations = [a for a in message.get("annotations") or [] if isinstance(a, dict)]
    return str(message.get("content") or ""), annotations, body.get("usage") or {}


def generate_image(
    model: str, prompt: str, *, aspect_ratio: str = "16:9", resolution: str | None = "1K"
) -> tuple[bytes, dict[str, Any]]:
    """One generated picture on the system key. Returns (image bytes, usage)."""
    body = asyncio.run(
        OpenRouterClient().generate_image(
            model, prompt, aspect_ratio=aspect_ratio, resolution=resolution
        )
    )
    image = body["data"][0]
    return base64.b64decode(str(image.get("b64_json") or "")), body.get("usage") or {}


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
