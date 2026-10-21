"""`python -m app.manage credits`: amount parsing and argument checks (pure)."""

from decimal import Decimal

import pytest

from app.manage import build_parser, check_kind, main, parse_amount


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("5", Decimal("5.000000")),
        ("-2.50", Decimal("-2.500000")),
        ("1,5", Decimal("1.500000")),
        (" 0.1234567 ", Decimal("0.123457")),
        ("1000", Decimal("1000.000000")),
    ],
)
def test_parse_amount(raw: str, expected: Decimal) -> None:
    assert parse_amount(raw) == expected


@pytest.mark.parametrize("raw", ["", "abc", "0", "0.0000001", "NaN", "Infinity", "1000.01"])
def test_parse_amount_rejects(raw: str) -> None:
    with pytest.raises(ValueError):
        parse_amount(raw)


def test_bonus_and_refund_only_add_credits() -> None:
    check_kind("adjustment", Decimal("-1"))
    check_kind("bonus", Decimal("1"))
    for kind in ("bonus", "refund"):
        with pytest.raises(ValueError):
            check_kind(kind, Decimal("-1"))
    with pytest.raises(ValueError):
        check_kind("topup", Decimal("1"))


def test_negative_amount_is_a_positional_argument() -> None:
    args = build_parser().parse_args(["credits", "a@b.co", "-2.5", "--reason", "double charge"])
    assert (args.email, args.amount, args.kind, args.yes) == ("a@b.co", "-2.5", "adjustment", False)


def test_bad_input_exits_before_touching_the_database(capsys: pytest.CaptureFixture[str]):
    assert main(["credits", "a@b.co", "abc", "--reason", "x"]) == 2
    assert main(["credits", "a@b.co", "-1", "--kind", "bonus", "--reason", "x"]) == 2
    assert main(["credits", "a@b.co", "1", "--reason", "  "]) == 2
    assert "Give a reason" in capsys.readouterr().err


def test_indexnow_needs_all() -> None:
    args = build_parser().parse_args(["indexnow", "--all", "--dry-run"])
    assert (args.command, args.all, args.dry_run) == ("indexnow", True, True)
    with pytest.raises(SystemExit):
        build_parser().parse_args(["indexnow"])
