"""Admin console finance and models: buckets, the money summary, Stripe reconciliation, the
model rows, the CSV, and service costs kept off the owner's bill.

Pure: no database; the totals test uses a tiny in-memory session.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.core.config import settings
from app.models.models import Debate, Turn
from app.services import orchestrator
from app.services.admin import finance
from app.services.admin.finance import DebateFacts, Money
from app.services.credits import debate_charge_usd

NOW = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)


def test_buckets() -> None:
    assert finance.truncate(NOW, "day") == datetime(2026, 10, 18, tzinfo=UTC)
    assert finance.truncate(NOW, "week") == datetime(2026, 10, 12, tzinfo=UTC)  # a Monday
    assert finance.truncate(NOW, "month") == datetime(2026, 10, 1, tzinfo=UTC)
    dec = datetime(2026, 12, 1, tzinfo=UTC)
    assert finance.next_bucket(dec, "month") == datetime(2027, 1, 1, tzinfo=UTC)
    months = finance.bucket_starts(datetime(2026, 1, 31, tzinfo=UTC), NOW, "month")
    assert len(months) == 10 and months[1] == datetime(2026, 2, 1, tzinfo=UTC)
    assert len(finance.bucket_starts(NOW - timedelta(days=30), NOW, "day")) == 31


def test_windows() -> None:
    start, end, bucket = finance.finance_window("90d", NOW, None)
    assert (end - start, bucket) == (timedelta(days=90), "week")
    first = datetime(2025, 3, 14, 9, tzinfo=UTC)
    start, _end, bucket = finance.finance_window("all", NOW, first)
    assert (start, bucket) == (datetime(2025, 3, 1, tzinfo=UTC), "month")


def test_money_summary() -> None:
    money = Money()
    for kind, category, amount in (
        ("topup", "topup", 10.0),
        ("bonus", "bonus", 1.0),
        ("refund", "refund", 0.5),
        ("adjustment", "adjustment", 2.0),
        ("adjustment", "adjustment", -0.75),
        ("debate", "models", -1.2),
        ("media", "voices", -0.3),
        ("media", "pictures", -0.06),
    ):
        finance.add_ledger(money, kind, category, amount)
    for purpose, provider, cost in (
        ("turn", "openrouter", 0.8),
        ("tts", "elevenlabs", 0.2),
        ("director", "openrouter", 0.05),
        ("verdict_structure", "openrouter", 0.01),
    ):
        finance.add_cost(money, purpose, provider, cost)
    out = money.out()
    assert (out["topups"], out["bonuses"], out["refunds"]) == (10.0, 1.0, 0.5)
    assert (out["adjustments_in"], out["adjustments_out"]) == (2.0, 0.75)
    assert (out["charged_models"], out["charged_voices"], out["charged_pictures"]) == (
        1.2,
        0.3,
        0.06,
    )
    assert out["charged"] == 1.56
    assert (out["cost_billed"], out["cost_unbilled"]) == (1.0, 0.06)
    assert (out["cost_openrouter"], out["cost_elevenlabs"]) == (0.86, 0.2)
    assert out["margin"] == round(1.56 - 0.5 - 1.06, 6)
    assert out["markup"] == 1.56
    assert Money().out()["markup"] is None


def test_finance_csv_escapes_and_formats() -> None:
    row = {"t": NOW, **Money(topups=5).out()}
    lines = finance.finance_csv([row]).strip().splitlines()
    assert lines[0].startswith("bucket_start_utc,topups")
    assert lines[1].startswith("2026-10-18,5.000000,") and lines[1].endswith(",")  # no markup


def test_stripe_reconciliation() -> None:
    sessions = [
        {"id": "cs_1", "payment_status": "paid", "amount_total": 1000, "created": 1},
        {
            "id": "cs_2",
            "payment_status": "paid",
            "amount_total": 500,
            "customer_email": "a@b.co",
            "created": 2,
        },
        {"id": "cs_3", "payment_status": "unpaid", "amount_total": 2000, "created": 3},
    ]
    out = finance.reconcile(sessions, {"cs_1": 10.0, "cs_9": 5.0})
    assert (out["sessions"], out["paid_total"], out["credited"], out["credited_total"]) == (
        2,
        15.0,
        2,
        15.0,
    )
    assert [m["id"] for m in out["missing"]] == ["cs_2"] and out["missing"][0]["email"] == "a@b.co"
    assert out["unmatched"] == ["cs_9"]


def test_debaters_and_router_pins() -> None:
    config = {
        "participants": [
            {"role": "moderator", "model_id": "openrouter/free"},
            {"role": "debater", "model_id": "openrouter/free"},
            {"role": "debater", "model_id": "openai/gpt-5.5"},
            {"role": "debater", "model_id": "openrouter/free"},
        ]
    }
    facts = finance.debaters_of(
        config,
        [
            ("moderator", "openrouter/free"),
            ("debater", "deepseek/deepseek-r1:free"),  # pinned by the router
            ("debater", "openai/gpt-5.5"),
            ("debater", "openrouter/free"),  # never pinned: no contender
        ],
    )
    assert facts.models == {
        "participant_1": "deepseek/deepseek-r1:free",
        "participant_2": "openai/gpt-5.5",
    }
    assert facts.pinned == ["deepseek/deepseek-r1:free"]


def test_model_rows() -> None:
    usage = {
        "openai/gpt-5.5": {
            "tries": 10,
            "ok": 8,
            "own_key_tries": 2,
            "duration_p50_ms": 9000,
            "duration_p90_ms": 20000,
            "ttft_p50_ms": 800,
            "ttft_p90_ms": 2000,
            "cost": 0.4,
            "avg_tokens_out": 420,
            "errors": {"rate_limited": 2},
        }
    }
    debates = [
        DebateFacts(
            models={
                "participant_1": "openai/gpt-5.5",
                "participant_2": "deepseek/deepseek-r1:free",
            },
            pinned=["deepseek/deepseek-r1:free"],
            votes={"participant_1": 3},
            judge_winner="participant_2",
            claims={"participant_1": {"checked": 2, "verified": 1, "disputed": 1}},
        )
    ]
    catalogue = {"openai/gpt-5.5": {"name": "GPT-5.5", "is_free": False}}
    rows = finance.model_rows(usage, debates, catalogue, with_money=True)
    gpt, r1 = rows
    assert (gpt["model"], gpt["name"], gpt["tries"], gpt["failure_rate"]) == (
        "openai/gpt-5.5",
        "GPT-5.5",
        10,
        0.2,
    )
    assert gpt["cost_per_turn"] == 0.05 and gpt["errors"] == {"rate_limited": 2}
    assert (gpt["audience_wins"], gpt["audience_contests"], gpt["judge_wins"]) == (1, 1, 0)
    assert (gpt["claims_checked"], gpt["claims_verified"]) == (2, 1)
    assert (r1["judge_wins"], r1["router_pins"], r1["in_catalogue"], r1["is_free"]) == (
        1,
        1,
        False,
        True,
    )
    hidden = finance.model_rows(usage, debates, catalogue, with_money=False)
    assert hidden[0]["cost_per_turn"] is None


# --- service costs stay off the bill ----------------------------------------------------------


class TotalsDB:
    def __init__(self, turns: list[Turn]) -> None:
        self.turns = turns

    def scalars(self, statement: Any) -> Any:
        return type("R", (), {"all": lambda _self: self.turns})()


def test_service_cost_is_not_billed() -> None:
    debate = Debate(
        id=uuid.uuid4(),
        config_json={"billing": {"own_key": False}},
        totals_json={"analysis_cost": 0.01, "service_cost": 0.0002},
    )
    turns = [
        Turn(
            seq_index=0,
            turn_type="opening",
            speaker_id="participant_1",
            visuals_json={},
            usage_json={"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.0},
        ),
    ]
    db: Any = TotalsDB(turns)
    totals = orchestrator._compute_totals(db, debate)
    assert totals["cost"] == 0.01 and totals["service_cost"] == 0.0002
    debate.totals_json = totals
    expected = 0.01 * float(settings.CREDIT_MARKUP)  # the fact-check only
    assert float(debate_charge_usd(debate)) == pytest.approx(expected, abs=1e-6)


def test_verdict_structuring_goes_to_service_cost() -> None:
    debate = Debate(totals_json={"analysis_cost": 0.01})
    orchestrator._add_service_cost(debate, {"cost": 0.0002})
    orchestrator._add_service_cost(debate, {"cost": 0.0001})
    orchestrator._add_service_cost(debate, None)
    assert debate.totals_json == {"analysis_cost": 0.01, "service_cost": 0.0003}
