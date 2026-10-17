"""Terminal output: the live debate, transcripts, verdicts and tables (rich).

Speaker colours mirror the web app (frontend/src/lib/format.ts). Rich drops colours by itself
when the output is not a terminal or NO_COLOR is set.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from rich.console import Console, Group
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from debatr.debate import round_heading, side_tags, total_turns, verdict_of
from debatr.markers import StreamedTurn
from debatr.styling import InlineMarkdown, Segment

HOST_COLOR = "#FFC46B"
JUDGE_COLOR = "#D9FF3D"
NEUTRAL_COLOR = "#8B90A0"
DEBATER_COLORS = (
    "#6C9CFF",
    "#FF7A66",
    "#A78BFA",
    "#34D399",
    "#F472B6",
    "#60A5FA",
    "#FB7185",
    "#FBBF24",
)


# --- formatting ------------------------------------------------------------------------


def usd(value: float | None) -> str:
    amount = float(value or 0)
    if amount == 0:
        return "$0"
    sign = "\u2212" if amount < 0 else ""  # real minus sign
    amount = abs(amount)
    return f"{sign}${amount:.4f}" if amount < 0.01 else f"{sign}${amount:.2f}"


def duration(ms: float | None) -> str:
    seconds = round(float(ms or 0) / 1000)
    if seconds < 60:
        return f"{seconds}s"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {seconds:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"


def when(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        moment = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return iso
    return moment.astimezone().strftime("%Y-%m-%d %H:%M")


def per_million(price: str | float | None) -> float:
    try:
        return float(price or 0) * 1_000_000
    except (TypeError, ValueError):
        return 0.0


# --- speakers -------------------------------------------------------------------------------


class Speakers:
    """Colour, side tag and model of each speaker, by id and by name."""

    def __init__(self, participants: list[dict[str, Any]]) -> None:
        self.tags = side_tags(participants)
        self.color: dict[str, str] = {}
        self.model: dict[str, str] = {}
        self.by_name: dict[str, str] = {}
        index = 0
        self.host_model = ""
        for i, p in enumerate(participants):
            pid = p.get("id") or f"participant_{i}"
            if p.get("role") == "moderator":
                self.color[pid] = HOST_COLOR
                self.host_model = str(p.get("model") or "")
            else:
                self.color[pid] = DEBATER_COLORS[index % len(DEBATER_COLORS)]
                index += 1
            self.model[pid] = str(p.get("model") or "")
            self.by_name[str(p.get("name") or "")] = pid

    def header(
        self,
        *,
        name: str,
        speaker_id: str | None = None,
        turn_type: str = "",
        model: str | None = None,
    ) -> Text:
        if turn_type == "verdict" or speaker_id == "judge":
            color, tag, model = JUDGE_COLOR, "JUDGE", model or self.host_model
        else:
            pid = speaker_id or self.by_name.get(name, "")
            color = self.color.get(pid, NEUTRAL_COLOR)
            tag = self.tags.get(pid, "")
            model = model or self.model.get(pid, "")
        line = Text()
        line.append("● ", style=color)
        line.append(name.replace("⚖️ ", ""), style=f"bold {color}")
        if tag:
            line.append(f"  {tag}", style="dim")
        if model:
            line.append(f"  ·  {model}", style="dim")
        return line


# --- blocks ---------------------------------------------------------------------------------


def lineup(detail: dict[str, Any], url: str) -> Panel:
    """Topic, speakers with their models and the format."""
    participants = detail.get("participants") or []
    speakers = Speakers(participants)
    settings = detail.get("settings") or {}
    rows: list[Any] = []
    for i, p in enumerate(participants):
        pid = p.get("id") or f"participant_{i}"
        rows.append(speakers.header(name=str(p.get("name") or "Speaker"), speaker_id=pid))
    rounds = int(settings.get("num_rounds") or 1)
    facts = Text(
        f"{rounds} round{'s' if rounds != 1 else ''} · "
        f"{str(settings.get('length_preset') or 'medium').replace('_', ' ')} turns · "
        f"{settings.get('language') or 'English'} · {total_turns(detail)} turns in total",
        style="dim",
    )
    rows += [Text(""), facts, Text(url, style="dim underline")]
    title = Text(str(settings.get("topic") or detail.get("title") or "Debate"), style="bold")
    return Panel(Group(*rows), title=title, title_align="left", border_style="dim", padding=(1, 2))


def verdict_panel(detail: dict[str, Any]) -> Panel | None:
    verdict = verdict_of(detail)
    if verdict is None or not (verdict["winner"] or verdict["headline"]):
        return None
    speakers = Speakers(detail.get("participants") or [])
    body: list[Any] = []
    if verdict["is_draw"]:
        body.append(Text("Draw", style=f"bold {JUDGE_COLOR}"))
    else:
        winner = Text("Winner: ", style="bold")
        color = speakers.color.get(verdict.get("winner_id") or "", JUDGE_COLOR)
        winner.append(str(verdict["winner"] or "?"), style=f"bold {color}")
        body.append(winner)
    if verdict["headline"]:
        body += [Text(""), Text(verdict["headline"])]
    for f in verdict["feedback"]:
        line = Text("\n")
        line.append(f"{f['speaker']}: ", style=speakers.color.get(f.get("speaker_id") or "", ""))
        line.append(str(f["text"] or ""), style="dim")
        body.append(line)
    return Panel(
        Group(*body),
        title=Text("⚖ The judge's verdict", style=f"bold {JUDGE_COLOR}"),
        title_align="left",
        border_style=JUDGE_COLOR,
        padding=(1, 2),
    )


def outcome_line(detail: dict[str, Any]) -> Text:
    status = str(detail.get("status") or "")
    totals = detail.get("totals") or {}
    turns = len(detail.get("turns") or [])
    styles = {"completed": ("✓ Completed", "green"), "stopped": ("■ Stopped", "yellow")}
    label, style = styles.get(status, (f"✗ {status.capitalize() or 'Unknown'}", "red"))
    line = Text(label, style=f"bold {style}")
    line.append(f"  ·  {turns} turns  ·  provider cost {usd(totals.get('cost'))}", style="dim")
    if detail.get("error_message"):
        line.append(f"\n{detail['error_message']}", style="red")
    return line


def transcript(console: Console, detail: dict[str, Any], url: str) -> None:
    """A finished (or running) debate, Markdown rendered."""
    console.print(lineup(detail, url))
    speakers = Speakers(detail.get("participants") or [])
    markdown = (detail.get("settings") or {}).get("output_style", "markdown") == "markdown"
    current_round = None
    for turn in detail.get("turns") or []:
        heading = round_heading(turn.get("round_id") or "", turn.get("turn_type") or "")
        round_id = turn.get("round_id")
        if round_id != current_round:
            current_round = round_id
            console.print()
            console.rule(Text(heading.split(" · ")[0], style="bold"), style="dim")
        console.print()
        console.print(
            speakers.header(
                name=str(turn.get("speaker_name") or ""),
                speaker_id=turn.get("speaker_id"),
                turn_type=str(turn.get("turn_type") or ""),
                model=turn.get("model_used"),
            )
        )
        if turn.get("error"):
            console.print(Text(f"⚠ {turn['error']}", style="red"))
        elif markdown:
            console.print(Markdown(str(turn.get("text") or "")))
        else:
            console.print(Text(str(turn.get("text") or "")))
    panel = verdict_panel(detail)
    console.print()
    if panel is not None:
        console.print(panel)
    console.print(outcome_line(detail))


class LiveView:
    """Prints a running debate from its SSE events: one header per turn, text as it streams
    (studio markers hidden, inline Markdown styled)."""

    def __init__(self, console: Console, detail: dict[str, Any]) -> None:
        self.console = console
        self.speakers = Speakers(detail.get("participants") or [])
        self.round: str | None = None
        self.current: int | None = None
        self.stream: StreamedTurn | None = None
        self.style = InlineMarkdown()
        self.printed: set[int] = set()

    def _write(self, segments: list[Segment], end: str = "") -> None:
        if segments or end:
            text = Text(end="")
            for chunk, style in segments:
                text.append(chunk, style=style or None)
            self.console.print(text, end=end, soft_wrap=True)

    def _flush(self, rest: str) -> None:
        """Print the end of the current turn and close its line."""
        self._write(self.style.feed(rest) + self.style.finish(), end="\n")

    def _round(self, round_id: str, turn_type: str) -> None:
        if round_id == self.round:
            return
        self.round = round_id
        self.console.print()
        label = round_heading(round_id, turn_type).split(" · ")[0]
        self.console.rule(Text(label, style="bold"), style="dim")

    def _close_open_turn(self) -> None:
        if self.current is not None and self.stream is not None:
            self._flush(self.stream.finish())
        self.current, self.stream = None, None

    def catch_up(self, detail: dict[str, Any]) -> None:
        """Print saved turns that were not streamed (joined late, reconnected)."""
        for turn in detail.get("turns") or []:
            if int(turn.get("seq_index", -1)) not in self.printed:
                self.turn_done(turn)

    def turn_started(self, data: dict[str, Any]) -> None:
        self._close_open_turn()
        seq = int(data.get("seq_index", -1))
        if seq in self.printed:
            return
        self._round(str(data.get("round_id") or ""), str(data.get("turn_type") or ""))
        self.console.print()
        self.console.print(
            self.speakers.header(
                name=str(data.get("speaker_name") or ""),
                turn_type=str(data.get("turn_type") or ""),
            )
        )
        self.current, self.stream, self.style = seq, StreamedTurn(), InlineMarkdown()

    def turn_delta(self, data: dict[str, Any]) -> None:
        if self.stream is None or int(data.get("seq_index", -1)) != self.current:
            return  # joined mid-turn: the whole text comes with turn_completed
        new = self.stream.feed(str(data.get("delta") or ""))
        if new:
            self._write(self.style.feed(new))

    def turn_done(self, turn: dict[str, Any]) -> None:
        seq = int(turn.get("seq_index", -1))
        if seq in self.printed:
            return
        if seq == self.current and self.stream is not None:
            if turn.get("error"):
                self._flush("")
            else:
                self._flush(self.stream.finish(str(turn.get("text") or "")))
            self.current, self.stream = None, None
        else:
            self._close_open_turn()
            self._round(str(turn.get("round_id") or ""), str(turn.get("turn_type") or ""))
            self.console.print()
            self.console.print(
                self.speakers.header(
                    name=str(turn.get("speaker_name") or ""),
                    speaker_id=turn.get("speaker_id"),
                    turn_type=str(turn.get("turn_type") or ""),
                    model=turn.get("model_used"),
                )
            )
            if not turn.get("error"):
                self.style = InlineMarkdown()
                self._flush(StreamedTurn().finish(str(turn.get("text") or "")))
        if turn.get("error"):
            self.console.print(Text(f"⚠ {turn['error']}", style="red"))
        self.printed.add(seq)

    def finish(self) -> None:
        self._close_open_turn()


# --- tables -----------------------------------------------------------------------------------


def estimate_table(est: dict[str, Any]) -> Table:
    table = Table.grid(padding=(0, 2))
    table.add_column(style="dim")
    table.add_column()
    table.add_row("Turns", str(est.get("turns")))
    table.add_row("Length", f"~{duration(est.get('duration_ms'))} spoken")
    credits = float(est.get("credits_cost_usd") or 0)
    cost = "free" if credits <= 0 else f"~{usd(credits)} in credits"
    if est.get("own_key"):
        cost += " (models on your OpenRouter key)"
    table.add_row("Cost", cost)
    if est.get("credits_before") is not None and credits > 0:
        table.add_row("Balance", f"{usd(est['credits_before'])} → {usd(est.get('credits_after'))}")
    if est.get("token_budget_usd") is not None:
        table.add_row("Token budget", f"{usd(est['token_budget_usd'])} left")
    return table


WIDE = 110  # terminal columns from which secondary columns are shown


def models_table(models: list[dict[str, Any]], width: int = WIDE) -> Table:
    wide = width >= WIDE
    table = Table(header_style="bold dim", box=None, pad_edge=False)
    table.add_column("Model id", style="bold", no_wrap=True)
    if wide:
        table.add_column("Name", overflow="fold")
    table.add_column("$ / 1M in", justify="right")
    table.add_column("$ / 1M out", justify="right")
    table.add_column("Context", justify="right")
    for m in models:
        pricing = m.get("pricing") or {}
        free = bool(m.get("is_free"))
        table.add_row(
            str(m.get("id")),
            *([str(m.get("name") or "")] if wide else []),
            "free" if free else f"{per_million(pricing.get('prompt')):.2f}",
            "free" if free else f"{per_million(pricing.get('completion')):.2f}",
            f"{int(m.get('context_length') or 0) // 1000}k",
            style="green" if free else None,
        )
    return table


def debates_table(debates: list[dict[str, Any]]) -> Table:
    table = Table(header_style="bold dim", box=None, pad_edge=False)
    table.add_column("Id", style="dim", no_wrap=True)
    table.add_column("Topic", overflow="fold")
    table.add_column("Status")
    table.add_column("Winner")
    table.add_column("Created", style="dim", no_wrap=True)
    styles = {"completed": "green", "running": "cyan", "queued": "cyan", "error": "red"}
    for d in debates:
        verdict = d.get("verdict") or {}
        winner = "draw" if verdict and verdict.get("is_draw") else verdict.get("winner_name") or ""
        status = str(d.get("status") or "")
        if d.get("is_public"):
            status += " · public"
        table.add_row(
            str(d.get("id")),
            str(d.get("topic") or d.get("title") or ""),
            Text(status, style=styles.get(str(d.get("status")), "yellow")),
            winner,
            when(d.get("created_at")),
        )
    return table


def gallery_table(items: list[dict[str, Any]], site: str, width: int = WIDE) -> Table:
    wide = width >= WIDE
    table = Table(header_style="bold dim", box=None, pad_edge=False)
    table.add_column("Topic", overflow="fold")
    if wide:
        table.add_column("Models", overflow="fold", style="dim")
    table.add_column("♥", justify="right")
    table.add_column("Votes", justify="right")
    table.add_column("Link", no_wrap=True, style="dim")
    for item in items:
        models = [
            str(p.get("model"))
            for p in item.get("participants") or []
            if p.get("role") != "moderator"
        ]
        table.add_row(
            str(item.get("topic") or item.get("title") or ""),
            *([" vs ".join(models)] if wide else []),
            str(item.get("likes") or 0),
            str(item.get("votes") or 0),
            f"{site}/d/{item.get('slug')}",
        )
    return table


def leaderboard_table(entries: list[dict[str, Any]]) -> Table:
    table = Table(header_style="bold dim", box=None, pad_edge=False)
    table.add_column("#", justify="right", style="dim")
    table.add_column("Model", style="bold", no_wrap=True)
    table.add_column("Rating", justify="right")
    table.add_column("Debates", justify="right")
    table.add_column("Votes", justify="right")
    table.add_column("Judge wins", justify="right")
    table.add_column("Accuracy", justify="right")
    for i, e in enumerate(entries, 1):
        checked = int(e.get("claims_checked") or 0)
        accuracy = f"{int(e.get('claims_verified') or 0) * 100 // checked}%" if checked else "-"
        table.add_row(
            str(i),
            str(e.get("model_id")),
            str(e.get("rating")),
            str(e.get("debates")),
            str(e.get("votes")),
            f"{e.get('judge_wins', 0)}/{e.get('judge_contests', 0)}",
            accuracy,
            style="green" if e.get("is_free") else None,
        )
    return table
