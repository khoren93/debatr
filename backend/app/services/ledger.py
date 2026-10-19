"""Ledger presentation and monthly usage for the Account page (pure functions, no DB).

A ledger row's `category` says what the money paid for: `models` (debate tokens), `voices`
(premium TTS), `pictures` (AI images) or the kind of a credit (`topup`, `bonus`, `refund`,
`adjustment`). Charges carry the debate title in their description ("Premium voices: <title>"),
so `title` strips that prefix and the UI shows the category as its own label.
"""

import csv
import io
import re
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta

from app.models.models import CreditTransaction, Debate
from app.schemas.billing import UsageDay, UsageOut

CATEGORY_LABELS = {
    "models": "Model tokens",
    "voices": "Premium voices",
    "pictures": "AI pictures",
    "music": "Battle music",
    "topup": "Top-up",
    "bonus": "Bonus",
    "refund": "Refund",
    "adjustment": "Adjustment",
}

# Description prefixes written by services/credits.py (kept for rows of deleted debates).
_PREFIXES = {"voices": "Premium voices: ", "pictures": "AI pictures: ", "music": "Music: "}

# Characters that make spreadsheets treat a cell as a formula (CSV injection).
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def category(tx: CreditTransaction) -> str:
    if tx.kind == "debate":
        return "models"
    if tx.kind == "media":
        ref = tx.provider_ref or ""
        if ":images:" in ref or (tx.description or "").startswith(_PREFIXES["pictures"]):
            return "pictures"
        if ":music:" in ref or (tx.description or "").startswith(_PREFIXES["music"]):
            return "music"
        return "voices"
    return tx.kind


def title(tx: CreditTransaction) -> str:
    """The row's headline: the debate title for charges, the description otherwise."""
    text = (tx.description or "").strip()
    prefix = _PREFIXES.get(category(tx))
    if prefix and text.startswith(prefix):
        text = text[len(prefix) :].strip()
    return text or CATEGORY_LABELS.get(category(tx), tx.kind.replace("_", " ").capitalize())


def _day(moment: datetime) -> date:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC).date()


def month_start(now: datetime) -> datetime:
    return now.astimezone(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def build_usage(
    now: datetime, debates: Iterable[Debate], txs: Iterable[CreditTransaction]
) -> UsageOut:
    """This month's consumption: totals plus one bucket per UTC day up to today.

    Tokens, voice time and renders count towards the day the debate was created (renders are
    plain counters without timestamps); money towards the day of the ledger row.
    """
    start = month_start(now)
    first, today = start.date(), _day(now)
    days = {
        first + timedelta(n): UsageDay(date=first + timedelta(n))
        for n in range((today - first).days + 1)
    }
    out = UsageOut(period_start=start)
    for d in debates:
        out.debates += 1
        totals = d.totals_json or {}
        media = d.media_json or {}
        tokens_in = int(totals.get("tokens_in") or 0)
        tokens_out = int(totals.get("tokens_out") or 0)
        voice_ms = (
            int((media.get("stats") or {}).get("total_ms") or 0) if d.media_status == "ready" else 0
        )
        renders = sum(int(v or 0) for v in (media.get("renders") or {}).values())
        out.tokens_in += tokens_in
        out.tokens_out += tokens_out
        out.voice_ms += voice_ms
        out.renders += renders
        bucket = days.get(_day(d.created_at)) if d.created_at else None
        if bucket is not None:
            bucket.tokens += tokens_in + tokens_out
            bucket.voice_ms += voice_ms
            bucket.renders += renders
    for tx in txs:
        amount = float(tx.amount_usd)
        if amount < 0:
            out.spent_usd += -amount
            if tx.kind == "debate":
                out.llm_usd += -amount
            elif tx.kind == "media":
                out.tts_usd += -amount
            bucket = days.get(_day(tx.created_at)) if tx.created_at else None
            if bucket is not None:
                bucket.spent_usd = round(bucket.spent_usd - amount, 6)
        elif tx.kind in ("topup", "bonus", "refund"):
            out.topped_up_usd += amount
    out.spent_usd = round(out.spent_usd, 6)
    out.topped_up_usd = round(out.topped_up_usd, 6)
    out.llm_usd = round(out.llm_usd, 6)
    out.tts_usd = round(out.tts_usd, 6)
    out.days = list(days.values())
    return out


def text_cell(value: str) -> str:
    """A CSV cell a spreadsheet will not run as a formula."""
    return "'" + value if value.startswith(_FORMULA_START) else value


def slug(text: str) -> str:
    """File-name-safe lowercase slug ("AI Debates" -> "ai-debates")."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "ledger"


def ledger_csv(txs: Iterable[CreditTransaction]) -> str:
    """The whole ledger as CSV (UTC timestamps, signed amounts, balance after each row)."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["date_utc", "type", "description", "debate_id", "amount_usd", "balance_usd"])
    for tx in txs:
        writer.writerow(
            [
                tx.created_at.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")
                if tx.created_at
                else "",
                CATEGORY_LABELS.get(category(tx), tx.kind),
                text_cell(title(tx)),
                str(tx.debate_id) if tx.debate_id else "",
                f"{float(tx.amount_usd):.6f}",
                f"{float(tx.balance_after_usd):.6f}",
            ]
        )
    return buffer.getvalue()
