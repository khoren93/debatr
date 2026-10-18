"""Operator commands, run on the server inside the api container:

    docker compose exec api python -m app.manage credits user@example.com 5 --reason "beta tester"

They act on the database directly, as the operator: they are not part of the public `debatr`
CLI and have no API route behind them.

`credits` adds (or, with a negative amount, takes) credits through the ledger, the only way the
balance changes (services/credits.apply_transaction_sync). The description is what the user
sees in their ledger; the reason stays internal (`meta_json.reason`).
"""

import argparse
import logging
import sys
import uuid
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation

from sqlalchemy import select

from app.core.logging import setup_logging
from app.core.sync_db import get_sync_session
from app.models.models import User
from app.services.credits import apply_transaction_sync, to_usd

logger = logging.getLogger(__name__)

CREDIT_KINDS = ("adjustment", "bonus", "refund")
DEFAULT_DESCRIPTIONS = {
    "adjustment": "Balance adjustment",
    "bonus": "Bonus credits",
    "refund": "Refund",
}
# One command never moves more than this, so a slip ("500" for "5.00") stays small.
MAX_CREDIT_USD = Decimal("1000")


def parse_amount(raw: str) -> Decimal:
    """Signed USD amount ("5", "-2.50", "1,5"), rounded to the ledger's 6 places."""
    try:
        amount = Decimal(raw.strip().replace(",", "."))
    except InvalidOperation:
        raise ValueError(f"Not an amount: {raw!r}") from None
    if not amount.is_finite():
        raise ValueError(f"Not an amount: {raw!r}")
    amount = to_usd(amount)
    if amount == 0:
        raise ValueError("The amount must not be zero")
    if abs(amount) > MAX_CREDIT_USD:
        raise ValueError(f"At most {MAX_CREDIT_USD} USD per command")
    return amount


def check_kind(kind: str, amount: Decimal) -> None:
    if kind not in CREDIT_KINDS:
        raise ValueError(f"Unknown kind {kind!r}")
    if kind != "adjustment" and amount < 0:
        raise ValueError(f"A {kind} adds credits: use a positive amount, or --kind adjustment")


def change_credits(
    email: str,
    amount: Decimal,
    *,
    kind: str,
    reason: str,
    description: str | None,
    assume_yes: bool,
) -> int:
    text = (description or DEFAULT_DESCRIPTIONS[kind]).strip()[:300]
    with get_sync_session() as db:
        user = db.scalar(select(User).where(User.email == email.strip().lower()))
        if user is None:
            print(f"No account with the email {email}", file=sys.stderr)
            return 1
        before = to_usd(user.credits_usd)
        print(f"{user.email}: {before} -> {to_usd(before + amount)} USD")
        print(f"  {kind}, shown to the user as {text!r}; reason: {reason}")
        if not assume_yes and input("Apply? [y/N] ").strip().lower() not in ("y", "yes"):
            print("Cancelled")
            return 1
        tx = apply_transaction_sync(
            db,
            user.id,
            amount,
            kind,
            description=text,
            provider="admin",
            provider_ref=f"admin:manage:{uuid.uuid4()}",
            meta={"reason": reason, "source": "manage"},
        )
        if tx is None:
            print("The account is gone", file=sys.stderr)
            return 1
        logger.info("Credits %s (%s) for %s: %s", amount, kind, user.email, reason)
        print(f"Done: balance {tx.balance_after_usd} USD (transaction {tx.id})")
        return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.manage", description=__doc__)
    parser.formatter_class = argparse.RawDescriptionHelpFormatter
    commands = parser.add_subparsers(dest="command", required=True)

    credits = commands.add_parser("credits", help="add or take credits through the ledger")
    credits.add_argument("email")
    credits.add_argument("amount", help="USD, e.g. 5 or -2.50")
    credits.add_argument("--reason", required=True, help="why (internal, kept in the ledger row)")
    credits.add_argument("--kind", choices=CREDIT_KINDS, default="adjustment")
    credits.add_argument("--description", help="what the user sees in the ledger")
    credits.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    setup_logging()
    args = build_parser().parse_args(argv)
    if args.command == "credits":
        reason = str(args.reason).strip()
        try:
            amount = parse_amount(args.amount)
            check_kind(args.kind, amount)
            if not reason:
                raise ValueError("Give a reason")
        except ValueError as e:
            print(e, file=sys.stderr)
            return 2
        return change_credits(
            args.email,
            amount,
            kind=args.kind,
            reason=reason,
            description=args.description,
            assume_yes=args.yes,
        )
    return 2


if __name__ == "__main__":
    sys.exit(main())
