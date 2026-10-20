"""`debatr mcp`: an MCP server (stdio) that lets AI agents run and read Debatr debates.

Agents start a debate, wait for it with `get_debate(wait_seconds=…)` (progress notifications
per turn) and read the verdict and transcript. The token comes from `debatr login` or
DEBATR_TOKEN and is re-read on every call, so signing in does not need a restart. Spending is
bounded twice: by the token's own limit on the server and by DEBATR_MAX_COST_USD per debate here.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Annotated, Any, Literal

import anyio
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations
from pydantic import BaseModel, Field

from debatr import __version__
from debatr.api import TERMINAL_EVENTS, TERMINAL_STATUSES, ApiError, DebatrClient
from debatr.config import Settings, resolve
from debatr.debate import (
    FREE_MODEL,
    TOPIC_MAX_LENGTH,
    Debater,
    build_config,
    digest,
    parse_debate_ref,
    total_turns,
)

ENV_MAX_COST = "DEBATR_MAX_COST_USD"
DEFAULT_MAX_COST = 1.0
MAX_WAIT_SECONDS = 300

READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=True)
WRITES = ToolAnnotations(
    read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=True
)
IDEMPOTENT = ToolAnnotations(
    read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=True
)

INSTRUCTIONS = """Debatr stages structured debates between AI models (any model on OpenRouter): \
a host opens each round, the debaters argue for {rounds} rounds and a judge gives a verdict with \
a winner and feedback. Use it to stress-test a decision, see both sides of a question or compare \
how models argue.

Workflow:
1. Optional: list_models to choose models ("openrouter/free" costs nothing), get_leaderboard for \
the audience's favourites, estimate_debate for the price.
2. start_debate answers at once with a debate_id; a debate takes about 1-5 minutes.
3. Call get_debate(debate_id, wait_seconds=45) until status is completed, error or stopped, \
then report the verdict (and quote the transcript where useful). Share the url with the user: \
the page has the player, audience voting and video export.
4. A debate stops with status error when a model fails to answer; resume_debate runs that turn \
again (same models, earlier turns kept) and goes on.

Besides debates there are rap battles (start_debate(format="rap_battle"), see list_formats): an \
MC and two rappers trade verses, the judge scores every round.

Debates are private unless public=true. Paid models are charged to the user's Debatr credits; \
this server refuses debates estimated above {cap} (DEBATR_MAX_COST_USD). Only when the user asks, \
generate_cover draws an AI cover (a thumbnail for the gallery, link previews and YouTube) for a \
finished debate, paid from the credits; get_debate shows its cover_url once it is drawn."""


class DebaterSpec(BaseModel):
    model: str = Field(
        default=FREE_MODEL,
        description="OpenRouter model id, e.g. 'anthropic/claude-sonnet-4.5' or "
        "'openai/gpt-5'; 'openrouter/free' picks a free model.",
    )
    name: str | None = Field(
        default=None, description="Display name (default: Nova, Atlas, Quill, …)."
    )
    stance: str | None = Field(
        default=None,
        description="Persona and position, e.g. 'A labour economist arguing against the "
        "policy'. Default: the first debater argues for, the second against.",
    )


Length = Literal["very_short", "short", "medium", "long"]
Show = Literal["debate", "rap_battle"]
SHOW_HELP = (
    "debate, or rap_battle: an MC and exactly two rappers trade verses over one beat for 1-3 "
    "rounds (rounds of 4/8/12/16 lines by length); with audio the track is made by ElevenLabs "
    "Music and is paid from the user's credits."
)
FLOWS_HELP = (
    "Rap battle with audio: how each rapper sounds, in the order of the debaters (ids from "
    "list_formats, e.g. ['gritty', 'sharp'])."
)


def max_cost_cap() -> float:
    try:
        return max(0.0, float(os.environ.get(ENV_MAX_COST) or DEFAULT_MAX_COST))
    except ValueError:
        return DEFAULT_MAX_COST


class Clients:
    """One API client per (server, token); the token is re-read for every call."""

    def __init__(self, resolver: Callable[[], Settings]) -> None:
        self._resolver = resolver
        self._key: tuple[str, str | None] | None = None
        self._client: DebatrClient | None = None

    async def get(self, *, auth: bool = True) -> DebatrClient:
        s = self._resolver()
        if auth and not s.token:
            raise ToolError(
                f"Not signed in to {s.url}: ask the user to run `debatr login` in a terminal "
                "(or to set DEBATR_TOKEN in this MCP server's configuration)."
            )
        key = (s.url, s.token)
        if self._client is None or self._key != key:
            if self._client is not None:
                await self._client.aclose()
            self._client, self._key = DebatrClient(s.url, s.token), key
        return self._client


def _api(error: ApiError) -> ToolError:
    return ToolError(error.message)


async def _debate_id(client: DebatrClient, raw: str) -> str:
    """Id from an id, a link or a share slug."""
    try:
        ref = parse_debate_ref(raw)
    except ValueError as e:
        raise ToolError(str(e)) from e
    if ref.kind == "id":
        return ref.value
    return str((await client.public_debate(ref.value))["id"])


def _config(
    topic: str,
    debaters: list[DebaterSpec] | None,
    host_model: str,
    rounds: int,
    length: str,
    language: str,
    intensity: int = 5,
    context: str | None = None,
    fact_check: bool = False,
    audio: bool = False,
    public: bool = False,
    show: str = "debate",
    flows: list[str] | None = None,
) -> dict[str, Any]:
    specs = debaters or [DebaterSpec(), DebaterSpec()]
    try:
        return build_config(
            topic,
            [Debater(model=d.model, name=d.name, stance=d.stance) for d in specs],
            host_model=host_model or FREE_MODEL,
            rounds=rounds,
            length=length,
            language=language,
            intensity=intensity,
            context=context,
            fact_check=fact_check,
            audio=audio,
            public=public,
            format=show,
            flows=flows,
        )
    except ValueError as e:
        raise ToolError(str(e)) from e


def _estimate_out(est: dict[str, Any]) -> dict[str, Any]:
    return {
        "cost_usd": round(float(est.get("credits_cost_usd") or 0), 4),
        "turns": est.get("turns"),
        "spoken_minutes": round(float(est.get("duration_ms") or 0) / 60_000, 1),
        "paid_models": est.get("paid_models") or [],
        "uses_own_openrouter_key": bool(est.get("own_key")),
        "balance_usd": est.get("credits_before"),
        "token_budget_left_usd": est.get("token_budget_usd"),
        "affordable": bool(est.get("sufficient", True)),
    }


def create_server(
    clients: Clients, *, cap: float | None = None, website: str | None = None
) -> MCPServer:
    cost_cap = max_cost_cap() if cap is None else cap
    server = MCPServer(
        "debatr",
        title="Debatr",
        description="Run structured debates between AI models and get a judge's verdict.",
        instructions=INSTRUCTIONS.format(rounds="1-10", cap=f"${cost_cap:.2f}"),
        website_url=website,
        version=__version__,
        log_level="WARNING",
    )

    @server.tool(title="Debatr account", annotations=READ_ONLY)
    async def get_account() -> dict[str, Any]:
        """The signed-in Debatr account: credit balance (USD) and this API token's spending
        limit. Free models cost nothing."""
        client = await clients.get()
        try:
            user = await client.me()
            token = await client.current_token()
        except ApiError as e:
            raise _api(e) from e
        return {
            "server": client.base_url,
            "email": (user or {}).get("email"),
            "name": (user or {}).get("display_name"),
            "balance_usd": (user or {}).get("credits_usd"),
            "token": {
                "name": token.get("name"),
                "spend_limit_usd": token.get("spend_limit_usd"),
                "spent_usd": token.get("spent_usd"),
                "expires_at": token.get("expires_at"),
            },
            "max_cost_per_debate_usd": cost_cap,
        }

    @server.tool(title="List formats", annotations=READ_ONLY)
    async def list_formats() -> dict[str, Any]:
        """Show formats for start_debate(format=…): seats, rounds, voices, and the rap
        battle's flows (start_debate(flows=…))."""
        client = await clients.get(auth=False)
        try:
            formats = await client.formats()
        except ApiError as e:
            raise _api(e) from e
        return {
            "formats": [
                {
                    "id": f.get("id"),
                    "name": f.get("name"),
                    "about": f.get("tagline"),
                    "debaters": [f.get("min_debaters"), f.get("max_debaters")],
                    "rounds": [f.get("min_rounds"), f.get("max_rounds")],
                    "host_required": f.get("host_required"),
                    "premium_voices_only": f.get("voices") == "elevenlabs",
                    **(
                        {
                            "flows": [
                                {"id": x.get("id"), "sound": f"{x.get('label')}: {x.get('hint')}"}
                                for x in f.get("flows") or []
                            ],
                            "default_flows": f.get("default_flows") or [],
                        }
                        if f.get("flows")
                        else {}
                    ),
                }
                for f in formats
            ]
        }

    @server.tool(title="List models", annotations=READ_ONLY)
    async def list_models(
        search: Annotated[
            str, Field(description="Words that must appear in the id or name, e.g. 'claude'.")
        ] = "",
        free_only: Annotated[bool, Field(description="Only models that cost nothing.")] = False,
        limit: Annotated[int, Field(ge=1, le=100)] = 25,
    ) -> dict[str, Any]:
        """Models that can debate or host (the OpenRouter catalogue), newest first. Prices are
        USD per million tokens."""
        client = await clients.get(auth=False)
        try:
            models = await client.models()
        except ApiError as e:
            raise _api(e) from e
        terms = [w.lower() for w in search.split()]
        found = sorted(
            (
                m
                for m in models
                if (not free_only or m.get("is_free"))
                and all(t in f"{m.get('id', '')} {m.get('name', '')}".lower() for t in terms)
            ),
            key=lambda m: int(m.get("created") or 0),
            reverse=True,
        )

        def price(value: Any) -> float:
            try:
                return round(float(value or 0) * 1_000_000, 4)
            except (TypeError, ValueError):
                return 0.0

        return {
            "matches": len(found),
            "models": [
                {
                    "id": m.get("id"),
                    "name": m.get("name"),
                    "free": bool(m.get("is_free")),
                    "input_usd_per_mtok": price((m.get("pricing") or {}).get("prompt")),
                    "output_usd_per_mtok": price((m.get("pricing") or {}).get("completion")),
                    "context_tokens": m.get("context_length"),
                }
                for m in found[:limit]
            ],
            "free_router": FREE_MODEL,
        }

    @server.tool(title="Estimate a debate", annotations=READ_ONLY)
    async def estimate_debate(
        topic: Annotated[
            str, Field(description="The question to debate.", max_length=TOPIC_MAX_LENGTH)
        ],
        debaters: Annotated[
            list[DebaterSpec] | None,
            Field(description="1-7 debaters (default: two free models, for and against)."),
        ] = None,
        host_model: Annotated[
            str, Field(description="Model of the host, who also judges.")
        ] = FREE_MODEL,
        rounds: Annotated[int, Field(ge=1, le=10)] = 2,
        length: Annotated[Length, Field(description="Length of each turn.")] = "short",
        language: str = "English",
        fact_check: bool = False,
        audio: bool = False,
        format: Annotated[Show, Field(description=SHOW_HELP)] = "debate",
        flows: Annotated[list[str] | None, Field(description=FLOWS_HELP)] = None,
    ) -> dict[str, Any]:
        """Price and length of a debate before starting it (same arguments as start_debate)."""
        config = _config(
            topic,
            debaters,
            host_model,
            rounds,
            length,
            language,
            fact_check=fact_check,
            audio=audio,
            show=format,
            flows=flows,
        )
        client = await clients.get()
        try:
            est = await client.estimate(config)
        except ApiError as e:
            raise _api(e) from e
        return {**_estimate_out(est), "max_cost_per_debate_usd": cost_cap}

    @server.tool(title="Start a debate", annotations=WRITES)
    async def start_debate(
        topic: Annotated[
            str,
            Field(
                description="The question, phrased so there are sides to take.",
                max_length=TOPIC_MAX_LENGTH,
            ),
        ],
        debaters: Annotated[
            list[DebaterSpec] | None,
            Field(description="1-7 debaters (default: two free models, for and against)."),
        ] = None,
        host_model: Annotated[
            str, Field(description="Model of the host, who also judges.")
        ] = FREE_MODEL,
        rounds: Annotated[int, Field(ge=1, le=10, description="Rounds of arguments.")] = 2,
        length: Annotated[Length, Field(description="Length of each turn.")] = "short",
        language: Annotated[str, Field(description="Language of the debate.")] = "English",
        intensity: Annotated[int, Field(ge=1, le=10, description="1 calm … 10 fierce.")] = 5,
        context: Annotated[
            str | None, Field(description="Background the speakers should know.")
        ] = None,
        fact_check: Annotated[
            bool, Field(description="Web fact-check of the figures shown on screen (paid).")
        ] = False,
        audio: Annotated[
            bool,
            Field(
                description="Voice it when done (MP3 + video page): free voices for a debate, "
                "the paid ElevenLabs track for a rap battle."
            ),
        ] = False,
        public: Annotated[
            bool, Field(description="Publish to the public gallery when finished.")
        ] = False,
        format: Annotated[Show, Field(description=SHOW_HELP)] = "debate",
        flows: Annotated[list[str] | None, Field(description=FLOWS_HELP)] = None,
        max_cost_usd: Annotated[
            float | None,
            Field(ge=0, description="Refuse to start above this estimate (USD)."),
        ] = None,
    ) -> dict[str, Any]:
        """Start a debate. Returns at once with its debate_id; then call get_debate with
        wait_seconds until it is completed."""
        config = _config(
            topic,
            debaters,
            host_model,
            rounds,
            length,
            language,
            intensity,
            context,
            fact_check,
            audio,
            public,
            format,
            flows,
        )
        limit = cost_cap if max_cost_usd is None else min(max_cost_usd, cost_cap)
        client = await clients.get()
        try:
            est = await client.estimate(config)
            cost = float(est.get("credits_cost_usd") or 0)
            if cost > limit:
                raise ToolError(
                    f"This debate is estimated at ${cost:.2f}, above the limit of ${limit:.2f}. "
                    "Use cheaper or free models (openrouter/free), fewer rounds or shorter turns"
                    + (
                        ", or ask the user to raise DEBATR_MAX_COST_USD."
                        if limit == cost_cap
                        else "."
                    )
                )
            if not est.get("sufficient", True):
                raise ToolError(
                    f"Not enough credits for this debate (about ${cost:.2f}): the user can top "
                    "up on the website, or use free models (openrouter/free)."
                )
            created = await client.create_debate(config)
            detail = await client.debate(str(created["debate_id"]))
        except ApiError as e:
            raise _api(e) from e
        return {
            "debate_id": detail["id"],
            "status": detail.get("status"),
            "url": client.debate_url(detail),
            "estimated_cost_usd": round(cost, 4),
            "turns_total": total_turns(detail),
            "next": f"get_debate(debate_id='{detail['id']}', wait_seconds=45)",
        }

    @server.tool(title="Get a debate", annotations=READ_ONLY)
    async def get_debate(
        debate_id: Annotated[
            str, Field(description="Id from start_debate; a share link or slug also works.")
        ],
        ctx: Context,
        wait_seconds: Annotated[
            int,
            Field(
                ge=0,
                le=MAX_WAIT_SECONDS,
                description="Wait up to this long for a running debate to finish (returns as "
                "soon as it does). Most clients cancel calls after ~60 s, so stay below 55.",
            ),
        ] = 45,
        include_transcript: Annotated[
            bool, Field(description="Include the full transcript (Markdown).")
        ] = True,
    ) -> dict[str, Any]:
        """Status, progress, verdict and transcript of a debate."""
        try:
            ref = parse_debate_ref(debate_id)
        except ValueError as e:
            raise ToolError(str(e)) from e
        # Public debates are readable without signing in; private ones answer 403.
        client = await clients.get(auth=False)
        try:
            if ref.kind == "slug":
                detail = await client.public_debate(ref.value)
            else:
                detail = await client.debate(ref.value)
                if wait_seconds > 0 and detail.get("status") not in TERMINAL_STATUSES:
                    await _wait(client, detail, wait_seconds, ctx)
                    detail = await client.debate(ref.value)
        except ApiError as e:
            raise _api(e) from e
        out = digest(
            detail, client.debate_url(detail), turns="markdown" if include_transcript else "none"
        )
        if out["status"] not in TERMINAL_STATUSES:
            out["next"] = f"Still {out['status']}: call get_debate again with wait_seconds."
        elif out["status"] == "error" and detail.get("is_owner"):
            out["next"] = (
                f"A model failed: resume_debate(debate_id='{detail['id']}') runs the failed "
                "turn again and goes on."
            )
        return out

    @server.tool(title="Resume a failed debate", annotations=WRITES)
    async def resume_debate(
        debate_id: Annotated[str, Field(description="Id of a debate with status error.")],
        max_cost_usd: Annotated[
            float | None,
            Field(ge=0, description="Refuse to resume above this estimate (USD)."),
        ] = None,
    ) -> dict[str, Any]:
        """Run a debate that stopped with an error again from the turn that failed: the turns
        before it stay and the same models speak. Returns at once; then call get_debate with
        wait_seconds until it is completed."""
        limit = cost_cap if max_cost_usd is None else min(max_cost_usd, cost_cap)
        client = await clients.get()
        try:
            debate_ref = await _debate_id(client, debate_id)
            est = await client.resume_estimate(debate_ref)
            cost = float(est.get("credits_cost_usd") or 0)
            if cost > limit:
                raise ToolError(
                    f"Resuming is estimated at ${cost:.2f}, above the limit of ${limit:.2f}"
                    + (": ask the user to raise DEBATR_MAX_COST_USD." if limit == cost_cap else ".")
                )
            if not est.get("sufficient", True):
                raise ToolError(
                    f"Not enough credits to resume (about ${cost:.2f}): the user can top up on "
                    "the website."
                )
            await client.resume_debate(debate_ref)
            detail = await client.debate(debate_ref)
        except ApiError as e:
            raise _api(e) from e
        return {
            "debate_id": detail["id"],
            "status": detail.get("status"),
            "url": client.debate_url(detail),
            "resumed_from_turn": int(est.get("from_turn") or 0) + 1,
            "estimated_cost_usd": round(cost, 4),
            "next": f"get_debate(debate_id='{detail['id']}', wait_seconds=45)",
        }

    @server.tool(title="Stop a debate", annotations=IDEMPOTENT)
    async def stop_debate(
        debate_id: Annotated[str, Field(description="Id of a running debate.")],
    ) -> dict[str, Any]:
        """Stop a queued or running debate; the current turn ends early."""
        client = await clients.get()
        try:
            return await client.stop_debate(await _debate_id(client, debate_id))
        except ApiError as e:
            raise _api(e) from e

    @server.tool(title="My debates", annotations=READ_ONLY)
    async def list_my_debates(
        search: Annotated[str, Field(description="Words in the topic.")] = "",
        status: Annotated[
            Literal["draft", "queued", "running", "completed", "error", "stopped"] | None,
            Field(description="Only debates in this state."),
        ] = None,
        limit: Annotated[int, Field(ge=1, le=100)] = 20,
    ) -> dict[str, Any]:
        """The user's debates, newest first."""
        client = await clients.get()
        try:
            debates = await client.list_debates(status=status, q=search or None, limit=limit)
        except ApiError as e:
            raise _api(e) from e
        return {
            "debates": [
                {
                    "debate_id": d.get("id"),
                    "topic": d.get("topic") or d.get("title"),
                    "status": d.get("status"),
                    "winner": ((d.get("verdict") or {}).get("winner_name")),
                    "models": [p.get("model") for p in d.get("participants") or []],
                    "is_public": d.get("is_public"),
                    "created_at": d.get("created_at"),
                    "url": client.debate_url(d),
                }
                for d in debates
            ]
        }

    @server.tool(title="Search the gallery", annotations=READ_ONLY)
    async def search_gallery(
        query: Annotated[str, Field(description="Words in the topic.")] = "",
        model: Annotated[str, Field(description="Only debates this model argued in.")] = "",
        sort: Literal["trending", "new", "top"] = "trending",
        format: Annotated[
            Show | None, Field(description="Only debates or only rap battles.")
        ] = None,
        limit: Annotated[int, Field(ge=1, le=50)] = 10,
    ) -> dict[str, Any]:
        """Public debates and rap battles from the gallery; read one with get_debate(url)."""
        client = await clients.get(auth=False)
        try:
            body = await client.gallery(
                q=query or None, model=model or None, sort=sort, format=format, limit=limit
            )
        except ApiError as e:
            raise _api(e) from e
        return {
            "total": body.get("total"),
            "debates": [
                {
                    "url": f"{client.base_url}/d/{item.get('slug')}",
                    "format": item.get("format") or "debate",
                    "topic": item.get("topic"),
                    "models": [
                        p.get("model")
                        for p in item.get("participants") or []
                        if p.get("role") != "moderator"
                    ],
                    "winner": (item.get("verdict") or {}).get("winner_name"),
                    "likes": item.get("likes"),
                    "audience_votes": item.get("votes"),
                    "published_at": item.get("published_at"),
                }
                for item in body.get("items") or []
            ],
        }

    @server.tool(title="Model leaderboard", annotations=READ_ONLY)
    async def get_leaderboard(
        free_only: Annotated[bool, Field(description="Only free models.")] = False,
        format: Annotated[
            Show, Field(description="Rank debaters, or rappers (votes on rap battles).")
        ] = "debate",
        limit: Annotated[int, Field(ge=1, le=100)] = 20,
    ) -> dict[str, Any]:
        """Models ranked by audience votes on public debates (Elo-like rating, 1000 =
        average; rating is null for models whose debates got no votes yet), with judge wins
        and the accuracy of their fact-checked figures."""
        client = await clients.get(auth=False)
        try:
            body = await client.leaderboard(None if format == "debate" else format)
        except ApiError as e:
            raise _api(e) from e
        entries = [e for e in body.get("entries") or [] if not free_only or e.get("is_free")]
        return {
            "total_votes": body.get("total_votes"),
            "models": [
                {
                    "rank": i,
                    "model": e.get("model_id"),
                    "rating": e.get("rating") if e.get("rated", True) else None,
                    "free": e.get("is_free"),
                    "debates": e.get("debates"),
                    "audience_votes": e.get("votes"),
                    "judge_wins": f"{e.get('judge_wins', 0)}/{e.get('judge_contests', 0)}",
                    "claims_verified": f"{e.get('claims_verified', 0)}/{e.get('claims_checked', 0)}",
                }
                for i, e in enumerate(entries[:limit], 1)
            ],
        }

    @server.tool(title="Generate an AI cover", annotations=WRITES)
    async def generate_cover(
        debate_id: Annotated[str, Field(description="Id of a completed debate.")],
        hook: Annotated[
            str | None,
            Field(
                max_length=22,
                description="The cover's headline (at most 4 words, 22 characters); by default "
                "the art director writes one from the debate.",
            ),
        ] = None,
    ) -> dict[str, Any]:
        """Draw an AI cover for a finished debate: a clickbait thumbnail with the debaters as
        characters, used in the gallery, link previews and as the YouTube thumbnail. About a
        minute; paid from the user's credits (~$0.04). Only when the user asks for it. Returns
        at once; get_debate shows cover_url when it is ready."""
        client = await clients.get()
        try:
            debate_ref = await _debate_id(client, debate_id)
            detail = await client.debate(debate_ref)
            price = float((detail.get("cover") or {}).get("price_usd") or 0)
            if price > cost_cap:
                raise ToolError(
                    f"A cover costs about ${price:.2f}, above the limit of ${cost_cap:.2f}: ask "
                    "the user to raise DEBATR_MAX_COST_USD."
                )
            state = await client.generate_cover(debate_ref, hook)
        except ApiError as e:
            raise _api(e) from e
        return {
            "debate_id": debate_ref,
            "cover_status": state.get("status"),
            "price_usd": round(price, 4),
            "next": f"get_debate(debate_id='{debate_ref}', wait_seconds=45) in about a minute",
        }

    @server.tool(title="Publish a debate", annotations=IDEMPOTENT)
    async def publish_debate(
        debate_id: Annotated[str, Field(description="Id of a completed debate.")],
        category: Annotated[
            Literal["tech", "society", "science", "culture", "money", "fun"] | None,
            Field(description="Gallery category."),
        ] = None,
    ) -> dict[str, Any]:
        """Make a completed debate public in the gallery (after an automatic content check;
        a flagged debate waits for a moderator). Only when the user asks for it."""
        client = await clients.get()
        try:
            return await client.publish(await _debate_id(client, debate_id), category)
        except ApiError as e:
            raise _api(e) from e

    return server


async def _wait(client: DebatrClient, detail: dict[str, Any], seconds: int, ctx: Context) -> None:
    """Follow the live stream until the debate ends or time runs out, reporting each turn."""
    total = total_turns(detail)
    done = len(detail.get("turns") or [])
    with anyio.move_on_after(seconds):
        try:
            async for ev in client.events(str(detail["id"])):
                if ev.event in ("turn_completed", "turn_error"):
                    done += 1
                    name = str(ev.data.get("speaker_name") or "").replace("⚖️ ", "")
                    await ctx.report_progress(done, total, f"{done}/{total} turns: {name} spoke")
                if ev.event in TERMINAL_EVENTS:
                    return
        except ApiError:
            # The stream dropped: check every few seconds instead.
            for _ in range(seconds // 3 + 1):
                await anyio.sleep(3)
                current = await client.debate(str(detail["id"]))
                if current.get("status") in TERMINAL_STATUSES:
                    return


def serve(settings: Settings) -> None:
    """Run on stdio. `settings.url` is kept; the token is re-read on every call."""
    url = settings.url
    server = create_server(Clients(lambda: resolve(url)), website=url)
    server.run("stdio")
