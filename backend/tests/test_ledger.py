import csv
import io
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from app.models.models import CreditTransaction, Debate
from app.services.ledger import build_usage, category, ledger_csv, month_start, slug, title

NOW = datetime(2026, 10, 17, 15, 30, tzinfo=UTC)


def _tx(
    amount: str,
    kind: str,
    description: str | None = None,
    ref: str | None = None,
    when: datetime = NOW,
    debate_id: uuid.UUID | None = None,
) -> CreditTransaction:
    return CreditTransaction(
        amount_usd=Decimal(amount),
        balance_after_usd=Decimal("1"),
        kind=kind,
        description=description,
        provider_ref=ref,
        created_at=when,
        debate_id=debate_id,
    )


def _debate(when: datetime, tokens: int = 0, voice_ms: int = 0, renders: int = 0) -> Debate:
    return Debate(
        created_at=when,
        totals_json={"tokens_in": tokens, "tokens_out": 0},
        media_status="ready" if voice_ms else "none",
        media_json={"stats": {"total_ms": voice_ms}, "renders": {"long": renders}},
    )


def test_category_tells_charges_apart():
    assert category(_tx("-0.1", "debate", "Topic", "debate:x:llm")) == "models"
    assert category(_tx("-0.1", "media", "Premium voices: Topic", "debate:x:media:1")) == "voices"
    assert category(_tx("-0.1", "media", "AI pictures: Topic", "debate:x:images:1")) == "pictures"
    # Without a ref the description prefix decides.
    assert category(_tx("-0.1", "media", "AI pictures: Topic")) == "pictures"
    assert category(_tx("1", "bonus", "Welcome credits")) == "bonus"
    assert category(_tx("5", "topup", "Top-up $5.00")) == "topup"


def test_title_strips_the_charge_prefix():
    assert (
        title(_tx("-0.1", "media", "Premium voices: Is AI art?", "debate:x:media:1"))
        == "Is AI art?"
    )
    assert (
        title(_tx("-0.1", "media", "AI pictures: Is AI art?", "debate:x:images:1")) == "Is AI art?"
    )
    assert title(_tx("-0.1", "debate", "Is AI art?")) == "Is AI art?"
    assert title(_tx("1", "bonus", "Welcome credits")) == "Welcome credits"
    assert title(_tx("1", "adjustment")) == "Adjustment"


def test_month_start_is_utc_midnight_of_the_first():
    assert month_start(NOW) == datetime(2026, 10, 1, tzinfo=UTC)


def test_usage_has_a_bucket_per_day_through_today():
    debates = [
        _debate(datetime(2026, 10, 14, 18, tzinfo=UTC), tokens=1200, voice_ms=60_000, renders=2),
        _debate(datetime(2026, 10, 17, 9, tzinfo=UTC), tokens=300),
    ]
    txs = [
        _tx("-0.04", "debate", "A", "debate:a:llm", datetime(2026, 10, 14, 18, 31, tzinfo=UTC)),
        _tx(
            "-0.93",
            "media",
            "Premium voices: A",
            "debate:a:media:1",
            datetime(2026, 10, 14, 18, 42, tzinfo=UTC),
        ),
        _tx("1.00", "bonus", "Welcome credits", when=datetime(2026, 10, 14, 18, 2, tzinfo=UTC)),
    ]
    out = build_usage(NOW, debates, txs)

    assert out.days[0].date == date(2026, 10, 1)
    assert len(out.days) == 17 and out.days[-1].date == date(2026, 10, 17)
    oct14 = out.days[13]
    assert (oct14.tokens, oct14.voice_ms, oct14.renders) == (1200, 60_000, 2)
    assert oct14.spent_usd == 0.97
    assert out.days[16].tokens == 300
    assert out.debates == 2 and out.tokens_in == 1500 and out.renders == 2
    assert out.spent_usd == 0.97 and out.topped_up_usd == 1.0
    assert out.llm_usd == 0.04 and out.tts_usd == 0.93


def test_usage_ignores_voice_of_unfinished_builds():
    debate = _debate(NOW, voice_ms=60_000)
    debate.media_status = "running"
    assert build_usage(NOW, [debate], []).voice_ms == 0


def test_csv_escapes_formulas_in_titles():
    debate_id = uuid.uuid4()
    rows = list(
        csv.reader(
            io.StringIO(
                ledger_csv(
                    [
                        _tx("-0.5", "debate", "=HYPERLINK(1)", "debate:x:llm", debate_id=debate_id),
                        _tx("5", "topup", "Top-up $5.00"),
                    ]
                )
            )
        )
    )
    assert rows[0] == ["date_utc", "type", "description", "debate_id", "amount_usd", "balance_usd"]
    assert rows[1] == [
        "2026-10-17 15:30:00",
        "Model tokens",
        "'=HYPERLINK(1)",
        str(debate_id),
        "-0.500000",
        "1.000000",
    ]
    assert rows[2][1:3] == ["Top-up", "Top-up $5.00"]


def test_slug():
    assert slug("Debatr Studio") == "debatr-studio"
    assert slug("!!!") == "ledger"
