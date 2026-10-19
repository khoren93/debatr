from decimal import Decimal

from app.core.config import settings
from app.models.models import Debate
from app.services import runtime_settings
from app.services.credits import (
    debate_charge_usd,
    lever_prices,
    prices_of,
    to_usd,
    tts_charge_usd,
    uses_own_key,
)

PRICES = {"markup": 3.0, "min_charge": 0.05, "voices_per_1k": 0.25, "music_per_min": 0.4}


def _debate(
    cost: float, own_key: bool, *, prices: dict | None = None, status: str = "completed"
) -> Debate:
    billing: dict = {"own_key": own_key}
    if prices is not None:
        billing["prices"] = prices
    return Debate(
        status=status,
        config_json={"topic": "t", "billing": billing},
        totals_json={"cost": cost},
    )


def test_to_usd_rounds_to_micro_dollars():
    assert to_usd(0.1234567) == Decimal("0.123457")
    assert to_usd(None) == Decimal("0")


def test_debate_charge_applies_markup():
    # A run from before the price snapshot pays the env markup it was quoted with.
    debate = _debate(0.5, own_key=False)
    expected = to_usd(Decimal("0.5") * Decimal(str(settings.CREDIT_MARKUP)))
    assert debate_charge_usd(debate) == expected
    assert debate_charge_usd(_debate(0.5, own_key=False, prices=PRICES)) == Decimal("1.5")


def test_a_completed_paid_debate_costs_at_least_the_minimum():
    tiny = _debate(0.002, own_key=False, prices=PRICES)
    assert debate_charge_usd(tiny) == Decimal("0.05")
    # A stopped or failed run pays its usage only; a free one nothing at all.
    assert debate_charge_usd(_debate(0.002, False, prices=PRICES, status="error")) == Decimal(
        "0.006"
    )
    assert debate_charge_usd(_debate(0.0, own_key=False, prices=PRICES)) == Decimal("0")
    assert debate_charge_usd(_debate(0.002, own_key=True, prices=PRICES)) == Decimal("0")


def test_prices_come_from_the_snapshot_then_the_levers(levers: dict) -> None:
    assert prices_of({"prices": {"markup": "2.5"}}).markup == 2.5
    assert prices_of({"prices": {"markup": "junk"}}).markup == settings.CREDIT_MARKUP
    assert prices_of(None).voices_per_1k == settings.TTS_CREDIT_PRICE_PER_1K_CHARS
    levers.update(
        credit_markup=3,
        min_debate_charge_usd=0.05,
        tts_price_per_1k_chars=0.25,
        music_price_per_min=0.4,
    )
    assert lever_prices(runtime_settings.current_sync()).as_dict() == PRICES
    for key, bad in (("credit_markup", 0.5), ("min_debate_charge_usd", 9), ("credit_markup", 11)):
        try:
            runtime_settings.validate_value(key, bad)
        except ValueError:
            continue
        raise AssertionError(f"{key}={bad} was accepted")


def test_own_key_is_free():
    debate = _debate(0.5, own_key=True)
    assert uses_own_key(debate)
    assert debate_charge_usd(debate) == Decimal("0")


def test_tts_charge_per_thousand_chars():
    assert tts_charge_usd(2000, 0.25) == Decimal("0.5")
    assert tts_charge_usd(0, 0.25) == Decimal("0")
    assert tts_charge_usd(-5, 0.25) == Decimal("0")
