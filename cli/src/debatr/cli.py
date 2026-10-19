"""`debatr`: run AI debates from the terminal.

Every command talks to a Debatr server over its public API. Output meant for scripts (`--json`,
`--detach`, `show --format …`) goes to stdout; progress, prompts and errors go to stderr.
"""

from __future__ import annotations

import asyncio
import json
import os
import platform
import socket
import sys
import time
import webbrowser
from collections.abc import Coroutine
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Annotated, Any, NoReturn, TypeVar

import typer
from rich.console import Console
from rich.markup import escape

from debatr import __version__, render
from debatr.api import TERMINAL_EVENTS, TERMINAL_STATUSES, ApiError, DebatrClient, debate_url
from debatr.config import Login, Settings, Store, resolve
from debatr.debate import (
    FREE_MODEL,
    Debater,
    build_config,
    digest,
    parse_debate_ref,
    transcript_markdown,
)

T = TypeVar("T")

ENV_OPENROUTER_KEY = "DEBATR_OPENROUTER_KEY"
ENV_ELEVENLABS_KEY = "DEBATR_ELEVENLABS_KEY"
SECRET_FIELDS = ("user_provider_key", "user_tts_key")

app = typer.Typer(
    name="debatr",
    help=(
        "Run AI debates from your terminal: pick a question and the models, watch them argue "
        "live and get the judge's verdict. [dim]Also an MCP server for AI agents: "
        "`debatr mcp`.[/dim]"
    ),
    no_args_is_help=True,
    rich_markup_mode="rich",
    context_settings={"help_option_names": ["-h", "--help"]},
    pretty_exceptions_show_locals=False,
)
out = Console(highlight=False)
err = Console(stderr=True, highlight=False)


class Length(str, Enum):
    very_short = "very_short"
    short = "short"
    medium = "medium"
    long = "long"


class Style(str, Enum):
    markdown = "markdown"
    spoken = "spoken"


class Voices(str, Enum):
    edge = "edge"
    elevenlabs = "elevenlabs"


class Format(str, Enum):
    text = "text"
    markdown = "markdown"
    json = "json"


class Show(str, Enum):
    """Show formats (`debatr formats`)."""

    debate = "debate"
    rap_battle = "rap_battle"


class Sort(str, Enum):
    trending = "trending"
    new = "new"
    top = "top"


class Period(str, Enum):
    week = "week"
    month = "month"
    year = "year"
    all = "all"


@dataclass
class State:
    url: str | None = None


# --- plumbing ------------------------------------------------------------------------------


def fail(message: str, code: int = 1) -> NoReturn:
    err.print(f"[bold red]Error:[/bold red] {escape(message)}")
    raise typer.Exit(code)


def run_async(coro: Coroutine[Any, Any, T]) -> T:
    try:
        return asyncio.run(coro)
    except ApiError as e:
        fail(e.message)


def settings_of(ctx: typer.Context) -> Settings:
    state = ctx.find_object(State) or State()
    try:
        return resolve(state.url)
    except ValueError as e:
        fail(str(e))


def signed_in(s: Settings) -> Settings:
    if not s.token:
        fail(f"Not signed in to {s.url}: run `debatr login` (or set DEBATR_TOKEN).")
    return s


def client_of(ctx: typer.Context, *, auth: bool = False) -> DebatrClient:
    """A client for one command (one event loop: use it inside a single `run_async`)."""
    s = settings_of(ctx)
    if auth:
        signed_in(s)
    return DebatrClient(s.url, s.token)


def interactive() -> bool:
    return sys.stdin.isatty() and sys.stderr.isatty()


def print_json(data: Any) -> None:
    sys.stdout.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def ref_of(raw: str) -> tuple[str, str]:
    try:
        ref = parse_debate_ref(raw)
    except ValueError as e:
        fail(str(e))
    return ref.kind, ref.value


async def load_debate(client: DebatrClient, raw: str) -> dict[str, Any]:
    kind, value = ref_of(raw)
    return await (client.debate(value) if kind == "id" else client.public_debate(value))


async def owned_id(client: DebatrClient, raw: str) -> str:
    """Debate id from an id or a link (a share slug is resolved through the gallery)."""
    kind, value = ref_of(raw)
    if kind == "id":
        return value
    return str((await client.public_debate(value))["id"])


def _version(value: bool) -> None:
    if value:
        out.print(f"debatr {__version__}")
        raise typer.Exit()


@app.callback()
def main_options(
    ctx: typer.Context,
    url: Annotated[
        str | None,
        typer.Option(
            "--url",
            help="Debatr server. Default: DEBATR_URL, the last server you signed in to, "
            "or https://ai-debates.net.",
            metavar="URL",
        ),
    ] = None,
    version: Annotated[
        bool,
        typer.Option(
            "--version", "-V", callback=_version, is_eager=True, help="Show the version and exit."
        ),
    ] = False,
) -> None:
    ctx.obj = State(url=url)


# --- account ------------------------------------------------------------------------------


def _client_name() -> str:
    host = socket.gethostname().split(".")[0] or platform.node() or "this computer"
    return f"Debatr CLI on {host}"[:100]


async def _device_login(client: DebatrClient, open_browser: bool) -> str:
    start = await client.device_start(_client_name())
    code = str(start["user_code"])
    link = str(start.get("verification_uri_complete") or start["verification_uri"])
    err.print(f"Your one-time code: [bold]{code}[/bold]")
    opened = open_browser and webbrowser.open(link)
    if opened:
        err.print(f"Approve it in the browser window that opened ([dim]{escape(link)}[/dim]).")
    else:
        err.print(f"Open [bold]{escape(link)}[/bold] and approve the request.")
    deadline = time.monotonic() + int(start.get("expires_in") or 600)
    interval = max(1, int(start.get("interval") or 3))
    with err.status("Waiting for the approval…"):
        while time.monotonic() < deadline:
            await asyncio.sleep(interval)
            poll = await client.device_poll(str(start["device_code"]))
            state = poll.get("status")
            if state == "approved" and poll.get("token"):
                return str(poll["token"])
            if state == "denied":
                fail("The request was denied in the browser.")
            if state == "expired":
                break
    fail("The code expired before it was approved: run `debatr login` again.")


@app.command()
def login(
    ctx: typer.Context,
    with_token: Annotated[
        bool,
        typer.Option(
            "--with-token",
            help="Read an API token from standard input instead of approving in the browser "
            "(create one under Account → API tokens).",
        ),
    ] = False,
    no_browser: Annotated[
        bool, typer.Option("--no-browser", help="Print the link instead of opening it.")
    ] = False,
) -> None:
    """Sign in: approve this computer in the browser, or paste an API token."""
    s = settings_of(ctx)

    async def go() -> None:
        if with_token:
            if sys.stdin.isatty():
                token = typer.prompt("Paste your API token", hide_input=True).strip()
            else:
                token = sys.stdin.read().strip()
            if not token:
                fail("No token given")
        else:
            async with DebatrClient(s.url) as anonymous:
                token = await _device_login(anonymous, open_browser=not no_browser)
        async with DebatrClient(s.url, token) as client:
            user = await client.me()
            if not user:
                fail("The server did not accept the token")
            info = await client.current_token()
        store = Store.load()
        store.logins[s.url] = Login(
            token=token, email=user.get("email"), token_name=info.get("name")
        )
        store.default_url = s.url
        path = store.save()
        err.print(
            f"[green]✓[/green] Signed in to {escape(s.url)} as [bold]{escape(str(user.get('email')))}"
            f"[/bold] (token “{escape(str(info.get('name')))}”, saved in {escape(str(path))})."
        )
        if s.token_source == "env":
            err.print("[yellow]Note:[/yellow] DEBATR_TOKEN is set and takes precedence.")

    try:
        run_async(go())
    except KeyboardInterrupt:
        err.print("\nLogin cancelled.")
        raise typer.Exit(130) from None


@app.command()
def logout(
    ctx: typer.Context,
    keep_token: Annotated[
        bool,
        typer.Option("--keep-token", help="Only forget the token here; don't revoke it."),
    ] = False,
) -> None:
    """Sign out: revoke this computer's token and forget it."""
    s = settings_of(ctx)
    store = Store.load()
    login_entry = store.logins.get(s.url)
    if login_entry is None:
        if s.token_source == "env":
            fail("This session uses DEBATR_TOKEN: unset it to sign out.")
        err.print(f"Not signed in to {escape(s.url)}.")
        return
    if not keep_token:

        async def revoke() -> None:
            async with DebatrClient(s.url, login_entry.token) as client:
                try:
                    await client.revoke_current_token()
                except ApiError as e:
                    if e.status != 401:  # already revoked or expired is fine
                        raise

        run_async(revoke())
    del store.logins[s.url]
    store.save()
    err.print(f"[green]✓[/green] Signed out of {escape(s.url)}.")


@app.command()
def whoami(
    ctx: typer.Context,
    json_out: Annotated[bool, typer.Option("--json", help="Print JSON.")] = False,
) -> None:
    """Show the account, its balance and the token in use."""
    client = client_of(ctx, auth=True)

    async def go() -> tuple[dict[str, Any], dict[str, Any]]:
        async with client:
            user = await client.me()
            if not user:
                fail("The server did not accept the token: run `debatr login`.")
            return user, await client.current_token()

    user, token = run_async(go())
    if json_out:
        print_json({"server": client.base_url, "user": user, "token": token})
        return
    out.print(
        f"[bold]{escape(str(user.get('display_name')))}[/bold] <{escape(str(user.get('email')))}>"
    )
    out.print(f"Server   {escape(client.base_url)}")
    out.print(f"Balance  {render.usd(user.get('credits_usd'))}")
    limit = token.get("spend_limit_usd")
    budget = (
        f"spent {render.usd(token.get('spent_usd'))} of {render.usd(limit)}"
        if limit is not None
        else f"spent {render.usd(token.get('spent_usd'))}, no limit"
    )
    expires = render.when(token.get("expires_at")) or "never"
    out.print(
        f"Token    “{escape(str(token.get('name')))}” {token.get('token_hint')} · {budget} · expires {expires}"
    )


# --- catalogue -----------------------------------------------------------------------------


def filter_models(
    models: list[dict[str, Any]], words: list[str], free: bool
) -> list[dict[str, Any]]:
    terms = [w.lower() for w in words if w.strip()]
    found = [
        m
        for m in models
        if (not free or m.get("is_free"))
        and all(t in f"{m.get('id', '')} {m.get('name', '')}".lower() for t in terms)
    ]
    return sorted(found, key=lambda m: int(m.get("created") or 0), reverse=True)


@app.command()
def models(
    ctx: typer.Context,
    search: Annotated[
        list[str] | None, typer.Argument(help="Words to look for in the id or name.")
    ] = None,
    free: Annotated[bool, typer.Option("--free", help="Only free models.")] = False,
    limit: Annotated[int, typer.Option("--limit", min=1, help="How many to show.")] = 30,
    json_out: Annotated[bool, typer.Option("--json", help="Print JSON.")] = False,
) -> None:
    """List the models you can cast (OpenRouter), newest first."""
    client = client_of(ctx)

    async def go() -> list[dict[str, Any]]:
        async with client:
            return await client.models()

    found = filter_models(run_async(go()), search or [], free)
    if json_out:
        print_json(found[:limit])
        return
    if not found:
        fail("No model matches")
    out.print(render.models_table(found[:limit], out.width))
    if len(found) > limit:
        err.print(f"[dim]{len(found) - limit} more: narrow the search or raise --limit.[/dim]")
    if not free:
        err.print(f"[dim]Free router: {FREE_MODEL} (picks an available free model).[/dim]")


@app.command()
def gallery(
    ctx: typer.Context,
    search: Annotated[str | None, typer.Argument(help="Words in the topic.")] = None,
    sort: Annotated[Sort, typer.Option("--sort")] = Sort.trending,
    period: Annotated[Period, typer.Option("--period", help="Window for --sort top.")] = Period.all,
    model: Annotated[
        str | None, typer.Option("--model", help="Debates this model argued in.")
    ] = None,
    show: Annotated[
        Show | None, typer.Option("--format", help="Only debates or only rap battles.")
    ] = None,
    limit: Annotated[int, typer.Option("--limit", min=1, max=100)] = 15,
    json_out: Annotated[bool, typer.Option("--json", help="Print JSON.")] = False,
) -> None:
    """Browse public debates and rap battles."""
    client = client_of(ctx)

    async def go() -> dict[str, Any]:
        async with client:
            return await client.gallery(
                q=search,
                model=model,
                sort=sort.value,
                period=period.value,
                format=show.value if show else None,
                limit=limit,
            )

    body = run_async(go())
    items = body.get("items") or []
    if json_out:
        print_json(body)
        return
    if not items:
        err.print("No public debates match.")
        return
    out.print(render.gallery_table(items, client.base_url, out.width))
    err.print(f"[dim]{len(items)} of {body.get('total')} · `debatr show <link>` reads one.[/dim]")


@app.command()
def formats(
    ctx: typer.Context,
    json_out: Annotated[bool, typer.Option("--json", help="Print JSON.")] = False,
) -> None:
    """Show formats (`run --format`) and the rap battle's flows (`run --flow`)."""
    client = client_of(ctx)

    async def go() -> list[dict[str, Any]]:
        async with client:
            return await client.formats()

    body = run_async(go())
    if json_out:
        print_json(body)
        return
    out.print(render.formats_table(body))


@app.command()
def leaderboard(
    ctx: typer.Context,
    free: Annotated[bool, typer.Option("--free", help="Only free models.")] = False,
    show: Annotated[
        Show, typer.Option("--format", help="Best debaters, or best rappers (rap_battle).")
    ] = Show.debate,
    limit: Annotated[int, typer.Option("--limit", min=1)] = 20,
    json_out: Annotated[bool, typer.Option("--json", help="Print JSON.")] = False,
) -> None:
    """Models ranked by audience votes (Elo-like rating, 1000 = average), per format."""
    client = client_of(ctx)

    async def go() -> dict[str, Any]:
        async with client:
            return await client.leaderboard(None if show is Show.debate else show.value)

    body = run_async(go())
    entries = [e for e in body.get("entries") or [] if not free or e.get("is_free")][:limit]
    if json_out:
        print_json({**body, "entries": entries})
        return
    if not entries:
        err.print("No ranked models yet.")
        return
    out.print(render.leaderboard_table(entries))
    err.print(
        f"[dim]{body.get('total_votes', 0)} votes in {body.get('total_debates', 0)} public "
        "debates.[/dim]"
    )


# --- running debates -------------------------------------------------------------------------


async def follow(
    client: DebatrClient, debate_id: str, view: render.LiveView | None
) -> dict[str, Any]:
    """Follow a debate until it ends; prints it through `view` (None = quietly). Reconnects
    when the stream drops and fills in turns that were missed meanwhile."""
    detail = await client.debate(debate_id)
    if view is not None:
        view.catch_up(detail)
    failures = 0
    while detail.get("status") not in TERMINAL_STATUSES:
        ended = False
        try:
            async for ev in client.events(debate_id):
                failures = 0
                if view is None:
                    pass
                elif ev.event == "connected":
                    # The stream is live now: print what was saved before it was.
                    view.catch_up(await client.debate(debate_id))
                elif ev.event == "turn_started":
                    view.turn_started(ev.data)
                elif ev.event == "turn_delta":
                    view.turn_delta(ev.data)
                elif ev.event in ("turn_completed", "turn_error"):
                    view.turn_done(ev.data)
                if ev.event in TERMINAL_EVENTS:
                    ended = True
                    break
        except ApiError as e:
            if e.status is not None and e.status < 500:
                raise
            failures += 1
            if failures > 6:
                raise
            await asyncio.sleep(min(2**failures, 20))
        else:
            if not ended:
                await asyncio.sleep(1)  # closed without an ending (server restart): reconnect
        detail = await client.debate(debate_id)
        if view is not None:
            view.catch_up(detail)
    if view is not None:
        view.finish()
    return detail


def report(detail: dict[str, Any], url: str, json_out: bool) -> None:
    """Final result of `run` / `watch`; the exit code follows the debate's status."""
    if json_out:
        print_json(digest(detail, url))
    else:
        panel = render.verdict_panel(detail)
        err.print()
        if panel is not None:
            out.print(panel)
        err.print(render.outcome_line(detail))
        if detail.get("status") == "error" and detail.get("is_owner"):
            err.print(f"Run the failed turn again and go on: `debatr resume {detail.get('id')}`")
        err.print(f"[dim]Watch, vote and export the video: {escape(url)}[/dim]")
    if detail.get("status") != "completed":
        raise typer.Exit(1)


def _on_interrupt(s: Settings, debate_id: str, offer_stop: bool) -> NoReturn:
    err.print()
    if (
        offer_stop
        and interactive()
        and typer.confirm(
            "Stop the debate on the server too? (otherwise it keeps running)",
            default=True,
            err=True,
        )
    ):

        async def stop_it() -> None:
            async with DebatrClient(s.url, s.token) as client:
                await client.stop_debate(debate_id)

        try:
            asyncio.run(stop_it())
            err.print("[yellow]■[/yellow] Debate stopped.")
        except ApiError as e:
            err.print(f"[red]Could not stop it:[/red] {escape(e.message)}")
    else:
        err.print(
            f"The debate continues on the server: `debatr watch {debate_id}` · "
            f"`debatr stop {debate_id}`"
        )
    raise typer.Exit(130)


def _secrets_hidden(config: dict[str, Any]) -> dict[str, Any]:
    return {k: ("***" if k in SECRET_FIELDS and v else v) for k, v in config.items()}


def _config_from_file(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        fail(f"Cannot read {path}: {e}")
    if not isinstance(data, dict):
        fail(f"{path} must hold a JSON object (see `debatr run … --print-config`)")
    return data


@app.command()
def run(
    ctx: typer.Context,
    topic: Annotated[
        str | None,
        typer.Argument(
            help='The question, e.g. "Should cities ban cars?" (at most 150 characters)',
            show_default=False,
        ),
    ] = None,
    debater: Annotated[
        list[str] | None,
        typer.Option(
            "--debater",
            "-d",
            help=f"Model of a debater; repeat for each (default: {FREE_MODEL} twice).",
            metavar="MODEL",
        ),
    ] = None,
    name: Annotated[
        list[str] | None,
        typer.Option("--name", "-n", help="Debater names, in the order of -d.", metavar="NAME"),
    ] = None,
    stance: Annotated[
        list[str] | None,
        typer.Option(
            "--stance",
            "-s",
            help="Persona and stance per debater, in the order of -d "
            "(default: first for, second against).",
            metavar="TEXT",
        ),
    ] = None,
    show: Annotated[
        Show,
        typer.Option(
            "--format",
            help="debate, or rap_battle: an MC and two rappers over one beat (2 debaters, "
            "1-3 rounds; --audio makes the track with ElevenLabs, paid).",
        ),
    ] = Show.debate,
    flow: Annotated[
        list[str] | None,
        typer.Option(
            "--flow",
            help="Rap battle: how each rapper sounds, in the order of -d (see `debatr formats`).",
            metavar="FLOW",
        ),
    ] = None,
    host: Annotated[
        str,
        typer.Option("--host", help="Model of the host, who also judges.", metavar="MODEL"),
    ] = FREE_MODEL,
    no_host: Annotated[
        bool,
        typer.Option("--no-host", help="No host; the server's default model judges (paid)."),
    ] = False,
    rounds: Annotated[int, typer.Option("--rounds", "-r", min=1, max=10)] = 2,
    length: Annotated[
        Length, typer.Option("--length", "-l", help="Length of a turn.")
    ] = Length.short,
    language: Annotated[
        str, typer.Option("--language", help="Language of the debate.")
    ] = "English",
    intensity: Annotated[
        int, typer.Option("--intensity", min=1, max=10, help="1 calm … 10 fierce.")
    ] = 5,
    style: Annotated[
        Style | None,
        typer.Option("--style", help="markdown, or spoken (plain prose; default with --audio)."),
    ] = None,
    context: Annotated[
        str | None,
        typer.Option(
            "--context", "-c", help="Background the speakers should know.", metavar="TEXT"
        ),
    ] = None,
    scenes: Annotated[
        bool,
        typer.Option(
            "--scenes", help="Draw charts and schemes after each turn (slower; on the web page)."
        ),
    ] = False,
    fact_check: Annotated[
        bool,
        typer.Option(
            "--fact-check", help="Web fact-check of on-screen figures (implies --scenes; paid)."
        ),
    ] = False,
    audio: Annotated[
        bool,
        typer.Option("--audio", help="Voice the debate when it ends (MP3 + video on the web)."),
    ] = False,
    voices: Annotated[
        Voices | None,
        typer.Option(
            "--voices",
            help="edge (free) or elevenlabs (premium, paid; the only voices of a rap battle).",
        ),
    ] = None,
    public: Annotated[
        bool,
        typer.Option("--public", help="Publish to the gallery when done (after a content check)."),
    ] = False,
    config_file: Annotated[
        Path | None,
        typer.Option(
            "--config",
            help="Request body as JSON (see --print-config); a TOPIC overrides its topic.",
            exists=True,
            dir_okay=False,
            metavar="FILE",
        ),
    ] = None,
    print_config: Annotated[
        bool, typer.Option("--print-config", help="Print the request body and exit.")
    ] = False,
    draft: Annotated[
        bool, typer.Option("--draft", help="Save as a draft to finish on the web.")
    ] = False,
    yes: Annotated[
        bool, typer.Option("--yes", "-y", help="Start paid runs without asking.")
    ] = False,
    max_cost: Annotated[
        float | None,
        typer.Option(
            "--max-cost",
            min=0,
            help="Don't start if the estimate is above this (USD).",
            metavar="USD",
        ),
    ] = None,
    detach: Annotated[
        bool, typer.Option("--detach", help="Start it and print the id; don't follow.")
    ] = False,
    json_out: Annotated[
        bool, typer.Option("--json", help="No live output; print the result as JSON.")
    ] = False,
) -> None:
    """Start a debate and watch it live.

    [dim]Examples:[/dim]
      debatr run "Should cities ban cars?"
      debatr run "Is AI art real art?" -d anthropic/claude-sonnet-4.5 -d openai/gpt-5 --rounds 3
      debatr run "Nuclear or renewables?" -d MODEL -n Ada -s "A nuclear engineer" -d MODEL -n Ben
      debatr run "Tabs or spaces?" --format rap_battle --rounds 1 --length very_short
    """
    openrouter_key = os.environ.get(ENV_OPENROUTER_KEY) or None
    elevenlabs_key = os.environ.get(ENV_ELEVENLABS_KEY) or None
    if config_file is not None:
        config = _config_from_file(config_file)
        if topic:
            config["topic"] = topic
        config.setdefault("auto_publish", public)
        if draft:
            config["draft"] = True
        if openrouter_key:
            config.setdefault("user_provider_key", openrouter_key)
    else:
        if not topic:
            fail('Give the question to debate, e.g. debatr run "Should cities ban cars?"')
        models_list = debater or [FREE_MODEL, FREE_MODEL]
        names, stances = name or [], stance or []
        if len(names) > len(models_list) or len(stances) > len(models_list):
            fail("More --name / --stance values than debaters (-d)")
        try:
            config = build_config(
                topic,
                [
                    Debater(
                        model=m,
                        name=names[i] if i < len(names) else None,
                        stance=stances[i] if i < len(stances) else None,
                    )
                    for i, m in enumerate(models_list)
                ],
                host_model=None if no_host else host,
                rounds=rounds,
                length=length.value,
                language=language,
                intensity=intensity,
                style=style.value if style else None,
                context=context,
                scenes=scenes,
                fact_check=fact_check,
                audio=audio,
                voices=voices.value if voices else None,
                public=public,
                draft=draft,
                openrouter_key=openrouter_key,
                elevenlabs_key=elevenlabs_key,
                format=show.value,
                flows=flow,
            )
        except ValueError as e:
            fail(str(e))
    if print_config:
        print_json(_secrets_hidden(config))
        return

    s = signed_in(settings_of(ctx))
    quiet = json_out or detach
    started: dict[str, str] = {}

    async def go() -> dict[str, Any] | None:
        async with DebatrClient(s.url, s.token) as client:
            await _check_flows(client, config)
            if not config.get("draft"):
                await _check_cost(client, config, quiet=quiet, yes=yes, max_cost=max_cost)
            created = await client.create_debate(config)
            debate_id = started["id"] = str(created["debate_id"])
            detail = await client.debate(debate_id)
            url = client.debate_url(detail)
            if config.get("draft"):
                link = client.web_url(f"/create?draft={debate_id}")
                err.print(f"[green]✓[/green] Draft saved: {escape(link)}")
                if json_out:
                    print_json({"id": debate_id, "url": link, "status": "draft"})
                return None
            if detach:
                if json_out:
                    print_json({"id": debate_id, "url": url, "status": detail.get("status")})
                else:
                    out.print(debate_id)
                    err.print(
                        f"[dim]Started: {escape(url)} · `debatr watch {debate_id}` follows it.[/dim]"
                    )
                return None
            view = None if json_out else render.LiveView(out, detail)
            if view is not None:
                out.print(render.lineup(detail, url))
            return await follow(client, debate_id, view)

    try:
        final = run_async(go())
    except KeyboardInterrupt:
        if "id" not in started:
            err.print("\nCancelled.")
            raise typer.Exit(130) from None
        _on_interrupt(s, started["id"], offer_stop=True)
    if final is not None:
        report(final, debate_url(s.url, final), json_out)


async def _check_flows(client: DebatrClient, config: dict[str, Any]) -> None:
    """Unknown flow ids would quietly fall back to the defaults on the server: name them."""
    chosen = set(((config.get("media_plan") or {}).get("flows") or {}).values())
    if not chosen:
        return
    try:
        formats = await client.formats()
    except ApiError:
        return  # an older server: it checks what it knows
    known = {
        str(f.get("id"))
        for fmt in formats
        if fmt.get("id") == config.get("format")
        for f in fmt.get("flows") or []
    }
    unknown = sorted(chosen - known)
    if known and unknown:
        fail(f"Unknown flow {', '.join(unknown)}: pick from {', '.join(sorted(known))}")


async def _check_cost(
    client: DebatrClient,
    config: dict[str, Any],
    *,
    quiet: bool,
    yes: bool,
    max_cost: float | None,
) -> None:
    """Estimate the run and refuse or confirm it before anything is charged."""
    _confirm_cost(await client.estimate(config), quiet=quiet, yes=yes, max_cost=max_cost)


def _confirm_cost(est: dict[str, Any], *, quiet: bool, yes: bool, max_cost: float | None) -> None:
    """Refuse a run the credits or the token cannot pay, or ask before a paid one."""
    credits = float(est.get("credits_cost_usd") or 0)
    if not quiet:
        err.print(render.estimate_table(est))
    if not est.get("sufficient", True):
        budget = est.get("token_budget_usd")
        if budget is not None and credits > float(budget):
            fail(
                f"This run needs about {render.usd(credits)} but this token may spend only "
                f"{render.usd(budget)} more (raise its limit under Account → API tokens)."
            )
        fail(
            f"Not enough credits: this run needs about {render.usd(credits)} and you have "
            f"{render.usd(est.get('credits_before'))}. Top up on the website or use free models."
        )
    if max_cost is not None and credits > max_cost:
        fail(f"The estimate {render.usd(credits)} is above --max-cost {render.usd(max_cost)}")
    if credits > 0 and not yes and max_cost is None:
        if not interactive():
            fail(
                f"This run costs about {render.usd(credits)} in credits: pass --yes "
                "(or --max-cost) to start it without a prompt."
            )
        if not typer.confirm(f"Start for ~{render.usd(credits)}?", default=True, err=True):
            raise typer.Exit(1)


@app.command()
def watch(
    ctx: typer.Context,
    debate: Annotated[str, typer.Argument(help="Debate id or link.", metavar="DEBATE")],
    json_out: Annotated[
        bool, typer.Option("--json", help="No live output; print the result as JSON.")
    ] = False,
) -> None:
    """Follow a debate live (or replay a finished one)."""
    s = settings_of(ctx)
    seen: dict[str, str] = {}

    async def go() -> dict[str, Any]:
        async with DebatrClient(s.url, s.token) as client:
            detail = await load_debate(client, debate)
            debate_id = seen["id"] = str(detail["id"])
            view = None if json_out else render.LiveView(out, detail)
            if view is not None:
                out.print(render.lineup(detail, client.debate_url(detail)))
            return await follow(client, debate_id, view)

    try:
        final = run_async(go())
    except KeyboardInterrupt:
        if "id" not in seen:
            raise typer.Exit(130) from None
        _on_interrupt(s, seen["id"], offer_stop=False)
    report(final, debate_url(s.url, final), json_out)


def _own_keys() -> dict[str, str]:
    """Own provider keys from the environment, sent like `run` sends them."""
    keys = {
        "user_provider_key": os.environ.get(ENV_OPENROUTER_KEY) or "",
        "user_tts_key": os.environ.get(ENV_ELEVENLABS_KEY) or "",
    }
    return {k: v for k, v in keys.items() if v}


@app.command()
def resume(
    ctx: typer.Context,
    debate: Annotated[str, typer.Argument(help="Debate id or link.", metavar="DEBATE")],
    yes: Annotated[
        bool, typer.Option("--yes", "-y", help="Resume paid runs without asking.")
    ] = False,
    max_cost: Annotated[
        float | None,
        typer.Option(
            "--max-cost",
            min=0,
            help="Don't resume if the estimate is above this (USD).",
            metavar="USD",
        ),
    ] = None,
    detach: Annotated[
        bool, typer.Option("--detach", help="Resume it and print the id; don't follow.")
    ] = False,
    json_out: Annotated[
        bool, typer.Option("--json", help="No live output; print the result as JSON.")
    ] = False,
) -> None:
    """Run a debate that stopped with an error again from the turn that failed.

    The earlier turns stay and the same models speak; only the remaining turns are charged.
    A debate that ran on your own OpenRouter key needs it again (DEBATR_OPENROUTER_KEY).
    """
    s = signed_in(settings_of(ctx))
    quiet = json_out or detach
    started: dict[str, str] = {}

    async def go() -> dict[str, Any] | None:
        async with DebatrClient(s.url, s.token) as client:
            debate_id = await owned_id(client, debate)
            keys = _own_keys()
            est = await client.resume_estimate(debate_id, keys)
            _confirm_cost(est, quiet=quiet, yes=yes, max_cost=max_cost)
            await client.resume_debate(debate_id, keys)
            started["id"] = debate_id
            detail = await client.debate(debate_id)
            url = client.debate_url(detail)
            from_turn = int(est.get("from_turn") or 0) + 1
            if detach:
                if json_out:
                    print_json({"id": debate_id, "url": url, "status": detail.get("status")})
                else:
                    out.print(debate_id)
                    err.print(
                        f"[dim]Resumed from turn {from_turn}: {escape(url)} · "
                        f"`debatr watch {debate_id}` follows it.[/dim]"
                    )
                return None
            if json_out:
                return await follow(client, debate_id, None)
            err.print(f"[green]↻[/green] Resumed from turn {from_turn}.")
            view = render.LiveView(out, detail)
            out.print(render.lineup(detail, url))
            return await follow(client, debate_id, view)

    try:
        final = run_async(go())
    except KeyboardInterrupt:
        if "id" not in started:
            err.print("\nCancelled.")
            raise typer.Exit(130) from None
        _on_interrupt(s, started["id"], offer_stop=True)
    if final is not None:
        report(final, debate_url(s.url, final), json_out)


# --- reading and managing --------------------------------------------------------------------


@app.command()
def show(
    ctx: typer.Context,
    debate: Annotated[str, typer.Argument(help="Debate id or link.", metavar="DEBATE")],
    fmt: Annotated[
        Format, typer.Option("--format", "-f", help="text, markdown or json.")
    ] = Format.text,
    output: Annotated[
        Path | None,
        typer.Option(
            "--output",
            "-o",
            help="Write to a file (Markdown unless --format json).",
            dir_okay=False,
        ),
    ] = None,
) -> None:
    """Print a debate: transcript and verdict."""
    client = client_of(ctx)

    async def go() -> dict[str, Any]:
        async with client:
            return await load_debate(client, debate)

    detail = run_async(go())
    url = client.debate_url(detail)
    if fmt is Format.json:
        text = json.dumps(digest(detail, url), indent=2, ensure_ascii=False) + "\n"
    elif fmt is Format.markdown or output is not None:
        text = transcript_markdown(detail) + f"\n{url}\n"
    else:
        render.transcript(out, detail, url)
        err.print(f"[dim]{escape(url)}[/dim]")
        return
    if output is None:
        sys.stdout.write(text)
    else:
        output.write_text(text, encoding="utf-8")
        err.print(f"[green]✓[/green] Saved {escape(str(output))}")


@app.command(name="list")
def list_debates(
    ctx: typer.Context,
    search: Annotated[str | None, typer.Argument(help="Words in the topic.")] = None,
    status: Annotated[
        str | None,
        typer.Option("--status", help="draft, queued, running, completed, error or stopped."),
    ] = None,
    limit: Annotated[int, typer.Option("--limit", min=1, max=200)] = 20,
    json_out: Annotated[bool, typer.Option("--json", help="Print JSON.")] = False,
) -> None:
    """Your debates, newest first."""
    client = client_of(ctx, auth=True)

    async def go() -> list[dict[str, Any]]:
        async with client:
            return await client.list_debates(status=status, q=search, limit=limit)

    debates = run_async(go())
    if json_out:
        print_json(debates)
        return
    if not debates:
        err.print('No debates yet: `debatr run "your question"` starts one.')
        return
    out.print(render.debates_table(debates))


@app.command()
def stop(
    ctx: typer.Context,
    debate: Annotated[str, typer.Argument(help="Debate id or link.", metavar="DEBATE")],
) -> None:
    """Stop a running debate (the current turn ends early)."""
    client = client_of(ctx, auth=True)

    async def go() -> None:
        async with client:
            await client.stop_debate(await owned_id(client, debate))

    run_async(go())
    err.print("[yellow]■[/yellow] Debate stopped.")


@app.command()
def delete(
    ctx: typer.Context,
    debate: Annotated[str, typer.Argument(help="Debate id or link.", metavar="DEBATE")],
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Don't ask.")] = False,
) -> None:
    """Delete a debate with its audio, for good."""
    client = client_of(ctx, auth=True)
    if not yes:
        if not interactive():
            fail("Pass --yes to delete without a prompt")
        if not typer.confirm("Delete this debate for good?", default=False, err=True):
            raise typer.Exit(1)

    async def go() -> None:
        async with client:
            await client.delete_debate(await owned_id(client, debate))

    run_async(go())
    err.print("[green]✓[/green] Deleted.")


@app.command()
def publish(
    ctx: typer.Context,
    debate: Annotated[str, typer.Argument(help="Debate id or link.", metavar="DEBATE")],
    category: Annotated[
        str | None,
        typer.Option("--category", help="tech, society, science, culture, money or fun."),
    ] = None,
) -> None:
    """Publish a finished debate to the gallery (after the content check)."""
    client = client_of(ctx, auth=True)

    async def go() -> dict[str, Any]:
        async with client:
            return await client.publish(await owned_id(client, debate), category)

    result = run_async(go())
    if result.get("is_public"):
        err.print(f"[green]✓[/green] Public: {escape(str(result.get('share_url')))}")
        if result.get("share_url"):
            out.print(result["share_url"])
    else:
        err.print("Waiting for a moderator: the content check flagged it for a review.")


@app.command()
def unpublish(
    ctx: typer.Context,
    debate: Annotated[str, typer.Argument(help="Debate id or link.", metavar="DEBATE")],
) -> None:
    """Take a debate out of the gallery."""
    client = client_of(ctx, auth=True)

    async def go() -> None:
        async with client:
            await client.unpublish(await owned_id(client, debate))

    run_async(go())
    err.print("[green]✓[/green] Private again.")


@app.command(name="open")
def open_debate(
    ctx: typer.Context,
    debate: Annotated[str, typer.Argument(help="Debate id or link.", metavar="DEBATE")],
) -> None:
    """Open a debate in the browser (player, votes, video export)."""
    client = client_of(ctx)

    async def go() -> dict[str, Any]:
        async with client:
            return await load_debate(client, debate)

    url = client.debate_url(run_async(go()))
    if not webbrowser.open(url):
        out.print(url)


@app.command()
def audio(
    ctx: typer.Context,
    debate: Annotated[str, typer.Argument(help="Debate id or link.", metavar="DEBATE")],
    output: Annotated[
        Path | None,
        typer.Option(
            "--output", "-o", help="File name (default: debate-<id>.mp3).", dir_okay=False
        ),
    ] = None,
    build: Annotated[
        bool, typer.Option("--build", help="Voice the debate first if it has no audio yet.")
    ] = False,
    voices: Annotated[
        Voices | None,
        typer.Option("--voices", help="Voices for --build (edge; a rap battle: elevenlabs)."),
    ] = None,
    wait: Annotated[
        bool, typer.Option("--wait/--no-wait", help="Wait for an audio build in progress.")
    ] = True,
) -> None:
    """Download the voiced debate as MP3."""
    client = client_of(ctx)

    async def go() -> Path:
        async with client:
            detail = await load_debate(client, debate)
            debate_id = str(detail["id"])
            media = await client.media(debate_id)
            state = media.get("media_status")
            if state in ("none", "error") and build:
                plan = detail.get("media_plan") or {}
                battle = (detail.get("settings") or {}).get("format") == "rap_battle"
                provider = voices.value if voices else ("elevenlabs" if battle else "edge")
                if battle and provider != "elevenlabs":
                    fail("A rap battle is voiced with premium voices only: --voices elevenlabs")
                options: dict[str, Any] = {
                    "provider": provider,
                    "visuals": bool(plan.get("visuals")),
                }
                if plan.get("flows"):
                    options["flows"] = plan["flows"]
                await client.build_media(debate_id, options)
                state = "queued"
            if state in ("queued", "running"):
                if not wait:
                    fail("The audio is still being built: try again in a minute (or use --wait).")
                with err.status("Voicing the debate…") as status:
                    while state in ("queued", "running"):
                        await asyncio.sleep(3)
                        media = await client.media(debate_id)
                        state = media.get("media_status")
                        progress = media.get("progress") or {}
                        if progress.get("message"):
                            status.update(f"Voicing the debate… {escape(str(progress['message']))}")
            if state != "ready":
                problem = (media.get("progress") or {}).get("error")
                if problem:
                    fail(f"The audio build failed: {problem}")
                battle = (detail.get("settings") or {}).get("format") == "rap_battle"
                fail(
                    "This rap battle has no track yet: add --build to make it (ElevenLabs, paid)."
                    if battle
                    else "This debate has no audio yet: add --build to voice it (free Edge voices)."
                )
            urls = media.get("urls") or {}
            dest = output or Path(f"debate-{debate_id[:8]}.mp3")
            with err.status(f"Downloading {dest}…"):
                return await client.download(str(urls["full_mp3"]), dest)

    path = run_async(go())
    err.print(f"[green]✓[/green] Saved {escape(str(path))}")


# --- MCP -------------------------------------------------------------------------------------


@app.command()
def mcp(ctx: typer.Context) -> None:
    """Run the MCP server on stdio, for AI agents (Claude, Cursor, …).

    [dim]Claude Code:[/dim]  claude mcp add debatr -- uvx debatr mcp
    [dim]Uses your `debatr login` or DEBATR_TOKEN; DEBATR_MAX_COST_USD caps each debate (default $1).[/dim]
    """
    from debatr.mcp_server import serve

    serve(settings_of(ctx))


def main() -> None:
    try:
        app()
    except KeyboardInterrupt:  # pragma: no cover - Ctrl+C outside a command's own handling
        err.print("\nInterrupted.")
        sys.exit(130)
