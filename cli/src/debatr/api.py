"""Async client for the Debatr REST API (`{site}/api`), shared by the CLI and the MCP server.

Responses are plain JSON dicts as documented at `{site}/api/docs`. Every failure (HTTP error,
network problem, unexpected reply) is raised as `ApiError` with a message fit for a human or
an agent.
"""

from __future__ import annotations

import json
import platform
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from debatr import __version__

USER_AGENT = f"debatr-cli/{__version__} (Python {platform.python_version()}; {platform.system()})"
TERMINAL_EVENTS = frozenset({"debate_completed", "debate_error", "debate_stopped"})
TERMINAL_STATUSES = frozenset({"completed", "error", "stopped"})


class ApiError(Exception):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


def _detail(response: httpx.Response) -> str | None:
    try:
        body = response.json()
    except ValueError:
        return None
    detail = body.get("detail") if isinstance(body, dict) else None
    if isinstance(detail, str):
        return detail
    if isinstance(detail, list) and detail and isinstance(detail[0], dict):
        first = detail[0]
        msg = str(first.get("msg") or "Invalid request").removeprefix("Value error, ")
        loc = [str(p) for p in first.get("loc") or [] if p not in ("body", "query", "path")]
        return f"{'.'.join(loc)}: {msg}" if loc else msg
    return None


def error_message(response: httpx.Response, signed_in: bool) -> str:
    status = response.status_code
    detail = _detail(response)
    if status == 401:
        if signed_in:
            return f"{detail or 'The API token was rejected'}. Run `debatr login` to sign in again."
        return "Not signed in: run `debatr login` (or set DEBATR_TOKEN)."
    if detail:
        return detail
    if status == 404:
        return "Not found"
    if status == 429:
        return "Too many requests, try again later"
    if status >= 500:
        return f"The server had a problem ({status}), try again later"
    return f"Request failed ({status})"


@dataclass
class SseEvent:
    event: str
    data: dict[str, Any]


async def parse_sse(lines: AsyncIterator[str]) -> AsyncIterator[tuple[str, str]]:
    """(event, data) pairs from the lines of a text/event-stream (comments are pings)."""
    event = "message"
    data: list[str] = []
    async for line in lines:
        if line == "":
            if data:
                yield event, "\n".join(data)
            event, data = "message", []
            continue
        if line.startswith(":"):
            continue
        field, _, value = line.partition(":")
        value = value.removeprefix(" ")
        if field == "event":
            event = value or "message"
        elif field == "data":
            data.append(value)
    if data:
        yield event, "\n".join(data)


def debate_url(base_url: str, debate: dict[str, Any]) -> str:
    """Share link when public, else the owner's page."""
    return debate.get("share_url") or f"{base_url.rstrip('/')}/debate/{debate['id']}"


class DebatrClient:
    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._http = httpx.AsyncClient(
            base_url=f"{self.base_url}/api",
            headers=headers,
            timeout=httpx.Timeout(timeout, connect=15.0),
            transport=transport,
            follow_redirects=True,
        )

    async def __aenter__(self) -> DebatrClient:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    @property
    def signed_in(self) -> bool:
        return bool(self.token)

    # --- plumbing ------------------------------------------------------------------

    async def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        clean = {k: v for k, v in (params or {}).items() if v is not None and v != ""}
        try:
            response = await self._http.request(method, path, json=json_body, params=clean)
        except httpx.TimeoutException as e:
            raise ApiError(f"{self.base_url} did not answer in time") from e
        except httpx.HTTPError as e:
            raise ApiError(f"Could not reach {self.base_url}: {e}") from e
        if response.status_code >= 400:
            raise ApiError(error_message(response, self.signed_in), response.status_code)
        if response.status_code == 204 or not response.content:
            return None
        try:
            return response.json()
        except ValueError as e:
            raise ApiError(f"{self.base_url} did not answer like a Debatr server") from e

    def web_url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def debate_url(self, debate: dict[str, Any]) -> str:
        return debate_url(self.base_url, debate)

    def absolute(self, url: str) -> str:
        return url if url.startswith(("http://", "https://")) else f"{self.base_url}{url}"

    # --- account -------------------------------------------------------------------

    async def me(self) -> dict[str, Any] | None:
        return await self.request("GET", "/auth/me")

    async def current_token(self) -> dict[str, Any]:
        return await self.request("GET", "/auth/tokens/current")

    async def revoke_current_token(self) -> None:
        await self.request("DELETE", "/auth/tokens/current")

    async def device_start(self, client_name: str) -> dict[str, Any]:
        return await self.request("POST", "/auth/device", json_body={"client_name": client_name})

    async def device_poll(self, device_code: str) -> dict[str, Any]:
        return await self.request(
            "POST", "/auth/device/token", json_body={"device_code": device_code}
        )

    # --- catalogue -----------------------------------------------------------------

    async def models(self) -> list[dict[str, Any]]:
        body = await self.request("GET", "/models")
        return list((body or {}).get("data") or [])

    async def leaderboard(self) -> dict[str, Any]:
        return await self.request("GET", "/gallery/leaderboard")

    async def gallery(
        self,
        *,
        q: str | None = None,
        model: str | None = None,
        sort: str = "trending",
        period: str | None = None,
        category: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        params = {
            "q": q,
            "model": model,
            "sort": sort,
            "period": period,
            "category": category,
            "limit": limit,
            "offset": offset,
        }
        return await self.request("GET", "/gallery", params=params)

    async def public_debate(self, slug: str) -> dict[str, Any]:
        return await self.request("GET", f"/gallery/{slug}")

    # --- debates -------------------------------------------------------------------

    async def estimate(self, config: dict[str, Any]) -> dict[str, Any]:
        return await self.request("POST", "/debates/estimate", json_body=config)

    async def create_debate(self, config: dict[str, Any]) -> dict[str, Any]:
        return await self.request("POST", "/debates", json_body=config)

    async def list_debates(
        self, *, status: str | None = None, q: str | None = None, limit: int = 20, offset: int = 0
    ) -> list[dict[str, Any]]:
        params = {"status": status, "q": q, "limit": limit, "offset": offset}
        return list(await self.request("GET", "/debates", params=params) or [])

    async def debate(self, debate_id: str) -> dict[str, Any]:
        return await self.request("GET", f"/debates/{debate_id}")

    async def stop_debate(self, debate_id: str) -> dict[str, Any]:
        return await self.request("POST", f"/debates/{debate_id}/stop")

    async def resume_estimate(
        self, debate_id: str, keys: dict[str, str] | None = None
    ) -> dict[str, Any]:
        """Price of resuming a failed debate; `from_turn` is where it would go on (0-based)."""
        path = f"/debates/{debate_id}/resume/estimate"
        return await self.request("POST", path, json_body=keys or {})

    async def resume_debate(
        self, debate_id: str, keys: dict[str, str] | None = None
    ) -> dict[str, Any]:
        """Run a failed debate again from the turn that failed."""
        return await self.request("POST", f"/debates/{debate_id}/resume", json_body=keys or {})

    async def delete_debate(self, debate_id: str) -> None:
        await self.request("DELETE", f"/debates/{debate_id}")

    async def publish(self, debate_id: str, category: str | None = None) -> dict[str, Any]:
        return await self.request(
            "POST", f"/debates/{debate_id}/publish", json_body={"category": category}
        )

    async def unpublish(self, debate_id: str) -> dict[str, Any]:
        return await self.request("DELETE", f"/debates/{debate_id}/publish")

    async def media(self, debate_id: str) -> dict[str, Any]:
        return await self.request("GET", f"/debates/{debate_id}/media")

    async def build_media(self, debate_id: str, options: dict[str, Any]) -> dict[str, Any]:
        return await self.request("POST", f"/debates/{debate_id}/media", json_body=options)

    async def events(self, debate_id: str) -> AsyncIterator[SseEvent]:
        """Live events of a debate until it ends (the server closes the stream then)."""
        try:
            async with self._http.stream(
                "GET",
                f"/debates/{debate_id}/stream",
                headers={"Accept": "text/event-stream", "Cache-Control": "no-cache"},
                # The server pings every 15 s; a minute of silence means the connection is gone.
                timeout=httpx.Timeout(30.0, read=60.0),
            ) as response:
                if response.status_code >= 400:
                    await response.aread()
                    raise ApiError(error_message(response, self.signed_in), response.status_code)
                async for name, raw in parse_sse(response.aiter_lines()):
                    try:
                        data = json.loads(raw) if raw else {}
                    except ValueError:
                        continue
                    yield SseEvent(name, data if isinstance(data, dict) else {})
        except httpx.TimeoutException as e:
            raise ApiError("The live stream went silent") from e
        except httpx.HTTPError as e:
            raise ApiError(f"Lost the live stream: {e}") from e

    async def download(
        self,
        url: str,
        dest: Path,
        progress: Callable[[int, int | None], None] | None = None,
    ) -> Path:
        """Stream a file (e.g. the debate's MP3) to `dest`; a partial file is removed."""
        tmp = dest.with_name(f".{dest.name}.part")
        try:
            async with self._http.stream("GET", self.absolute(url), timeout=60.0) as response:
                if response.status_code >= 400:
                    await response.aread()
                    raise ApiError(error_message(response, self.signed_in), response.status_code)
                total = int(response.headers.get("content-length") or 0) or None
                done = 0
                with tmp.open("wb") as fh:
                    async for chunk in response.aiter_bytes():
                        fh.write(chunk)
                        done += len(chunk)
                        if progress:
                            progress(done, total)
            tmp.replace(dest)
        except httpx.HTTPError as e:
            raise ApiError(f"Download failed: {e}") from e
        finally:
            tmp.unlink(missing_ok=True)
        return dest
