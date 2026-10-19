"""Thin async client for the OpenRouter chat completions API."""

import json
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

Message = dict[str, Any]


class OpenRouterError(Exception):
    """A failed OpenRouter request with a human-readable message."""

    def __init__(
        self, message: str, status_code: int | None = None, provider: str | None = None
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.provider = provider

    def __str__(self) -> str:
        text = self.message
        if self.status_code:
            text = f"HTTP {self.status_code}: {text}"
        if self.provider:
            text = f"{text} (provider: {self.provider})"
        return text


@dataclass
class StreamChunk:
    delta: str = ""
    usage: dict[str, Any] | None = None
    model: str | None = None  # the model that answers (a router names the one it picked)


def error_from_payload(payload: Any, status_code: int | None = None) -> OpenRouterError:
    """Build an OpenRouterError from a parsed error body ({"error": {...}})."""
    message = f"Request failed with status {status_code}" if status_code else "Request failed"
    provider: str | None = None
    err = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(err, dict):
        message = str(err.get("message") or message)
        meta = err.get("metadata")
        if isinstance(meta, dict):
            provider = meta.get("provider_name") or None
            raw = meta.get("raw")
            if isinstance(raw, str) and raw and raw not in message and len(raw) <= 400:
                message = f"{message} — {raw}"
    elif isinstance(err, str) and err:
        message = err
    return OpenRouterError(message, status_code=status_code, provider=provider)


def parse_error_body(body: bytes | str, status_code: int | None = None) -> OpenRouterError:
    text = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else body
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        snippet = text.strip()[:300] or "empty response body"
        return OpenRouterError(snippet, status_code=status_code)
    return error_from_payload(payload, status_code)


def merge_system_prompt(messages: list[Message]) -> list[Message]:
    """Fold system messages into the first user message.

    Some providers reject the system role with HTTP 400; this is the fallback format.
    """
    system_content = "\n".join(
        str(m.get("content", "")) for m in messages if m.get("role") == "system"
    )
    non_system = [m for m in messages if m.get("role") != "system"]
    if not system_content:
        return list(messages)
    if not non_system:
        return [{"role": "user", "content": system_content}]
    first_user_idx = next((i for i, m in enumerate(non_system) if m.get("role") == "user"), None)
    if first_user_idx is None:
        return [{"role": "user", "content": system_content}, *non_system]
    merged = dict(non_system[first_user_idx])
    merged["content"] = f"{system_content}\n\n{merged.get('content', '')}"
    non_system[first_user_idx] = merged
    return non_system


def _iter_sse_data(line: str) -> str | None:
    """Return the JSON payload of an SSE `data:` line, or None for comments/blank lines."""
    if not line.startswith("data:"):
        return None
    return line[5:].strip()


class OpenRouterClient:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport
        self._models_cache: list[dict[str, Any]] = []
        self._cache_time = 0.0

    # --- helpers ---------------------------------------------------------

    @property
    def base_url(self) -> str:
        return settings.OPENROUTER_BASE_URL.rstrip("/")

    def _headers(self, api_key: str | None) -> dict[str, str]:
        key = api_key or settings.OPENROUTER_API_KEY or ""
        return {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "HTTP-Referer": settings.SITE_URL,
            "X-Title": settings.PROJECT_NAME,
        }

    def _client(self, read_timeout: float | None = None) -> httpx.AsyncClient:
        timeout = httpx.Timeout(
            connect=settings.LLM_CONNECT_TIMEOUT,
            read=read_timeout or settings.LLM_READ_TIMEOUT,
            write=settings.LLM_CONNECT_TIMEOUT,
            pool=settings.LLM_CONNECT_TIMEOUT,
        )
        return httpx.AsyncClient(timeout=timeout, transport=self._transport)

    # --- chat completions ------------------------------------------------

    async def stream_chat_completion(
        self,
        model: str,
        messages: list[Message],
        api_key: str | None = None,
        max_tokens: int | None = None,
        read_timeout: float | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """Stream a chat completion, yielding text deltas and (last) usage info.

        If the provider rejects the request with HTTP 400 and a system prompt was
        present, the request is retried once with the system prompt merged into
        the first user message.
        """
        attempts = ["standard"]
        if any(m.get("role") == "system" for m in messages):
            attempts.append("merged_system")

        headers = self._headers(api_key)
        for attempt in attempts:
            current = messages if attempt == "standard" else merge_system_prompt(messages)
            payload: dict[str, Any] = {
                "model": model,
                "messages": current,
                "stream": True,
                "usage": {"include": True},
            }
            if max_tokens:
                payload["max_tokens"] = max_tokens

            try:
                async with (
                    self._client(read_timeout) as client,
                    client.stream(
                        "POST", f"{self.base_url}/chat/completions", json=payload, headers=headers
                    ) as response,
                ):
                    if response.status_code != 200:
                        body = await response.aread()
                        err = parse_error_body(body, response.status_code)
                        if response.status_code == 400 and attempt != attempts[-1]:
                            logger.warning(
                                "OpenRouter 400 for %s (%s); retrying with merged system prompt",
                                model,
                                err.message,
                            )
                            continue
                        logger.warning("OpenRouter error for %s: %s", model, err)
                        raise err

                    async for line in response.aiter_lines():
                        data = _iter_sse_data(line)
                        if data is None:
                            continue
                        if data == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        if not isinstance(chunk, dict):
                            continue
                        if chunk.get("error"):
                            # Providers can fail mid-stream with a 200 status.
                            raise error_from_payload(chunk)
                        choices = chunk.get("choices") or []
                        delta = ""
                        if choices:
                            delta = (choices[0].get("delta") or {}).get("content") or ""
                        usage = chunk.get("usage")
                        answered = chunk.get("model")
                        if delta or usage:
                            yield StreamChunk(
                                delta=delta,
                                usage=usage,
                                model=answered if isinstance(answered, str) else None,
                            )
                return
            except httpx.TimeoutException as e:
                raise OpenRouterError(f"Timed out waiting for {model}") from e
            except httpx.HTTPError as e:
                raise OpenRouterError(f"Connection error: {e}") from e

    async def chat_completion(
        self,
        model: str,
        messages: list[Message],
        api_key: str | None = None,
        max_tokens: int | None = None,
        read_timeout: float | None = None,
    ) -> dict[str, Any]:
        """One non-streamed completion: the full response body, so callers can read
        `message.annotations` (web search citations) as well as the text and usage."""
        payload: dict[str, Any] = {"model": model, "messages": messages, "usage": {"include": True}}
        if max_tokens:
            payload["max_tokens"] = max_tokens
        try:
            async with self._client(read_timeout) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    json=payload,
                    headers=self._headers(api_key),
                )
        except httpx.TimeoutException as e:
            raise OpenRouterError(f"Timed out waiting for {model}") from e
        except httpx.HTTPError as e:
            raise OpenRouterError(f"Connection error: {e}") from e
        if response.status_code != 200:
            raise parse_error_body(response.content, response.status_code)
        body = response.json()
        if not isinstance(body, dict) or body.get("error"):
            raise error_from_payload(body)
        return body

    async def generate_image(
        self,
        model: str,
        prompt: str,
        *,
        aspect_ratio: str = "16:9",
        resolution: str | None = "1K",
        api_key: str | None = None,
    ) -> dict[str, Any]:
        """Text-to-image via `POST /images`: {"data": [{"b64_json", "media_type"}], "usage"}."""
        payload: dict[str, Any] = {"model": model, "prompt": prompt, "aspect_ratio": aspect_ratio}
        if resolution:
            payload["resolution"] = resolution
        try:
            async with self._client(180.0) as client:
                response = await client.post(
                    f"{self.base_url}/images", json=payload, headers=self._headers(api_key)
                )
        except httpx.TimeoutException as e:
            raise OpenRouterError(f"Timed out waiting for {model}") from e
        except httpx.HTTPError as e:
            raise OpenRouterError(f"Connection error: {e}") from e
        if response.status_code != 200:
            raise parse_error_body(response.content, response.status_code)
        body = response.json()
        if not isinstance(body, dict) or not body.get("data"):
            raise OpenRouterError(f"{model} returned no image")
        return body

    async def validate_model(
        self, model: str, api_key: str | None = None
    ) -> tuple[bool, str | None]:
        """Send a tiny prompt to confirm the model responds. Returns (ok, error)."""
        messages = [{"role": "user", "content": "Reply with the single word: pong"}]
        try:
            async for _chunk in self.stream_chat_completion(
                model, messages, api_key=api_key, max_tokens=20, read_timeout=30.0
            ):
                return True, None
            # Stream ended without content; still a successful round-trip.
            return True, None
        except OpenRouterError as e:
            return False, str(e)
        except Exception as e:  # pragma: no cover - defensive
            logger.exception("Unexpected error validating %s", model)
            return False, str(e)

    # --- account ---------------------------------------------------------

    async def get_credits(self, api_key: str | None = None) -> tuple[float | None, str | None]:
        """Return (remaining credits, error). Credits are None when unknown."""
        if not (api_key or settings.OPENROUTER_API_KEY):
            return None, "No API key configured"
        try:
            async with self._client(read_timeout=15.0) as client:
                response = await client.get(
                    f"{self.base_url}/credits", headers=self._headers(api_key)
                )
        except httpx.HTTPError as e:
            logger.warning("Failed to fetch credits: %s", e)
            return None, "Could not reach OpenRouter"
        if response.status_code != 200:
            err = parse_error_body(response.content, response.status_code)
            return None, err.message
        data = response.json().get("data", {})
        total = float(data.get("total_credits", 0) or 0)
        used = float(data.get("total_usage", 0) or 0)
        return round(total - used, 6), None

    async def account(self) -> dict[str, Any]:
        """The system key's account for the admin console: credits bought and used (`/credits`)
        and the key's own limit and tier (`/key`). Missing parts carry an `error`."""
        out: dict[str, Any] = {}
        if not settings.OPENROUTER_API_KEY:
            return {"error": "No API key configured"}
        try:
            async with self._client(read_timeout=15.0) as client:
                credits = await client.get(f"{self.base_url}/credits", headers=self._headers(None))
                key = await client.get(f"{self.base_url}/key", headers=self._headers(None))
        except httpx.HTTPError as e:
            logger.warning("Failed to fetch the OpenRouter account: %s", e)
            return {"error": "Could not reach OpenRouter"}
        if credits.status_code == 200:
            data = credits.json().get("data", {})
            out["total_credits"] = float(data.get("total_credits") or 0)
            out["total_usage"] = float(data.get("total_usage") or 0)
        else:
            out["error"] = parse_error_body(credits.content, credits.status_code).message
        if key.status_code == 200:
            data = key.json().get("data", {})
            out["key"] = {
                "label": data.get("label"),
                "limit": data.get("limit"),
                "limit_remaining": data.get("limit_remaining"),
                "usage": data.get("usage"),
                "usage_daily": data.get("usage_daily"),
                "is_free_tier": data.get("is_free_tier"),
            }
        return out

    async def get_models(self) -> list[dict[str, Any]]:
        """Fetch the model catalogue, cached for MODELS_CACHE_TTL seconds."""
        now = time.time()
        if self._models_cache and (now - self._cache_time < settings.MODELS_CACHE_TTL):
            return self._models_cache

        try:
            async with self._client(read_timeout=30.0) as client:
                response = await client.get(f"{self.base_url}/models")
                response.raise_for_status()
                raw_models = response.json().get("data", [])
        except httpx.HTTPError as e:
            logger.warning("Failed to fetch models (serving cached): %s", e)
            return self._models_cache

        processed: list[dict[str, Any]] = []
        for model in raw_models:
            architecture = model.get("architecture") or {}
            outputs = architecture.get("output_modalities")
            if isinstance(outputs, list) and outputs and "text" not in outputs:
                continue  # image/audio-only models cannot debate
            pricing = model.get("pricing") or {}
            try:
                prompt_price = float(pricing.get("prompt") or 0)
                completion_price = float(pricing.get("completion") or 0)
            except (TypeError, ValueError):
                continue
            if prompt_price < 0 or completion_price < 0:
                continue  # routers such as openrouter/auto: a variable price we cannot estimate
            processed.append(
                {
                    "id": str(model.get("id")),
                    "name": str(model.get("name") or model.get("id")),
                    "context_length": int(model.get("context_length") or 0),
                    "pricing": {
                        "prompt": str(pricing.get("prompt") or "0"),
                        "completion": str(pricing.get("completion") or "0"),
                    },
                    "is_free": prompt_price == 0.0 and completion_price == 0.0,
                    "description": str(model.get("description") or "")[:600],
                    "created": int(model.get("created") or 0),
                }
            )

        self._models_cache = processed
        self._cache_time = now
        return processed


openrouter_client = OpenRouterClient()
