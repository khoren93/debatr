"""Operator commands, run on the server inside the api container:

    docker compose exec api python -m app.manage admin grant you@example.com
    docker compose exec api python -m app.manage credits user@example.com 5 --reason "beta tester"

They act on the database directly, as the operator: they are not part of the public `debatr`
CLI and have no API route behind them. Every change is written to the admin audit log.

`admin` manages console access: `grant` gives a role (and prints the one-time enrollment code
for setting up the authenticator on the first sign-in), `revoke` takes it away, `reset-2fa`
clears a lost authenticator (and the passkeys), `revoke-sessions` signs an admin out everywhere,
`enroll-code` issues a fresh enrollment code, `list` shows who has access. Roles are granted
nowhere else.

`credits` adds (or, with a negative amount, takes) credits through the ledger, the only way the
balance changes (services/credits.apply_transaction_sync). The description is what the user
sees in their ledger; the reason stays internal (`meta_json.reason`).

`indexnow --all` announces every page the sitemaps list to IndexNow at once (after a move to a
new domain); `--dry-run` only prints them.

`media refresh-timeline` brings ready timelines up to date without voicing or composing
anything (a battle's beat grid, the Shorts, the lines the video hits): by debate id, or every
ready debate of a format with `--format rap_battle`. It reads the generated track with ffmpeg,
so run it in the media-worker container:

    docker compose exec media-worker python -m app.manage media refresh-timeline --format rap_battle

`geoip update` fetches the IP → place and IP → network databases of the Audience page now (the
background queue does it monthly; services/audience/geo) and places the visits saved without one.

`official EMAIL [--name NAME] [--off]` makes an account the site's own (the gallery shows the
logo as its avatar and marks it; only it may carry the brand's name, services/official), with a
new display name if given; `--off` makes it an ordinary account again (a brand name falls back to
one from the email).

`audience classify [--days N]` weighs stored visits again — person, bot or AI agent
(services/audience/bots) —: once for the visits from before the verdicts, or after the rules
changed. Visits from before the page counted its input keep fewer signals.
"""

import argparse
import logging
import sys
import uuid
from collections.abc import Sequence
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.admin.access import ROLES
from app.core.config import settings
from app.core.logging import setup_logging
from app.core.redis import get_sync_redis
from app.core.sync_db import get_sync_session
from app.models.models import AdminPasskey, User
from app.services.admin.audit import record_sync
from app.services.admin.sessions import (
    ENROLL_SECONDS,
    drop_enrollment_code_sync,
    issue_enrollment_code_sync,
    revoke_all_sync,
)
from app.services.credits import (
    MANUAL_DESCRIPTIONS,
    MANUAL_KINDS,
    MAX_MANUAL_USD,
    apply_transaction_sync,
    check_manual_change,
    to_usd,
)

logger = logging.getLogger(__name__)

CREDIT_KINDS = MANUAL_KINDS
DEFAULT_DESCRIPTIONS = MANUAL_DESCRIPTIONS


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
    if abs(amount) > MAX_MANUAL_USD:
        raise ValueError(f"At most {MAX_MANUAL_USD} USD per command")
    return amount


def check_kind(kind: str, amount: Decimal) -> None:
    check_manual_change(amount, kind)


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
        record_sync(
            db,
            "credits.changed",
            target=user,
            reason=reason,
            after={"amount_usd": str(amount), "kind": kind, "description": text},
        )
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


def _user_by_email(db: Session, email: str) -> User | None:
    user = db.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None:
        print(f"No account with the email {email}", file=sys.stderr)
    return user


def _drop_passkeys(db: Session, user: User) -> int:
    result = db.execute(delete(AdminPasskey).where(AdminPasskey.user_id == user.id))
    return int(getattr(result, "rowcount", 0) or 0)


def _print_enrollment_code(user: User) -> None:
    code = issue_enrollment_code_sync(get_sync_redis(), str(user.id))
    host = settings.admin_hostname
    page = f"https://{host}/admin/login" if host else "/admin/login on the site"
    print(f"Enrollment code (one use, {ENROLL_SECONDS // 3600} h): {code}")
    print(f"  Sign in at {page} with this account's password, then enter the code to set")
    print("  up an authenticator app. Keep it secret: with the password it adds a phone.")


def admin_grant(email: str, role: str) -> int:
    with get_sync_session() as db:
        user = _user_by_email(db, email)
        if user is None:
            return 1
        if not user.is_active:
            print("The account is disabled", file=sys.stderr)
            return 1
        before = user.admin_role
        user.admin_role = role
        record_sync(db, "role.granted", target=user, before={"role": before}, after={"role": role})
        db.commit()
        print(f"{user.email}: role {before or 'none'} -> {role}")
        if settings.admin_skip_2fa:
            print("ADMIN_SKIP_2FA is on: sign in to the console with the password alone.")
        elif user.totp_enabled_at is None:
            _print_enrollment_code(user)
        return 0


def admin_revoke(email: str) -> int:
    with get_sync_session() as db:
        user = _user_by_email(db, email)
        if user is None:
            return 1
        before = user.admin_role
        user.admin_role = None
        user.session_epoch += 1
        passkeys = _drop_passkeys(db, user)
        record_sync(db, "role.revoked", target=user, before={"role": before, "passkeys": passkeys})
        db.commit()
        ended = revoke_all_sync(get_sync_redis(), str(user.id))
        drop_enrollment_code_sync(get_sync_redis(), str(user.id))
        print(f"{user.email}: role {before or 'none'} -> none ({ended} sessions ended)")
        return 0


def admin_reset_2fa(email: str) -> int:
    """For a lost phone: the next sign-in sets up a new authenticator (with a new code)."""
    with get_sync_session() as db:
        user = _user_by_email(db, email)
        if user is None:
            return 1
        had = user.totp_enabled_at is not None
        user.totp_secret_enc = None
        user.totp_enabled_at = None
        user.recovery_codes_json = []
        user.session_epoch += 1
        passkeys = _drop_passkeys(db, user)
        record_sync(
            db, "auth.2fa_reset", target=user, before={"enrolled": had, "passkeys": passkeys}
        )
        db.commit()
        ended = revoke_all_sync(get_sync_redis(), str(user.id))
        print(
            f"{user.email}: authenticator and {passkeys} passkeys cleared ({ended} sessions ended)"
        )
        if user.admin_role:
            _print_enrollment_code(user)
        return 0


def admin_revoke_sessions(email: str) -> int:
    with get_sync_session() as db:
        user = _user_by_email(db, email)
        if user is None:
            return 1
        user.session_epoch += 1
        record_sync(db, "auth.sessions_revoked", target=user)
        db.commit()
        ended = revoke_all_sync(get_sync_redis(), str(user.id))
        print(f"{user.email}: {ended} console sessions ended")
        return 0


def admin_enroll_code(email: str) -> int:
    with get_sync_session() as db:
        user = _user_by_email(db, email)
        if user is None:
            return 1
        if not user.admin_role:
            print("The account has no admin role: grant one first", file=sys.stderr)
            return 1
        if user.totp_enabled_at is not None:
            print("The authenticator is already set up (lost it? use reset-2fa)", file=sys.stderr)
            return 1
        record_sync(db, "auth.enroll_code_issued", target=user)
        db.commit()
        _print_enrollment_code(user)
        return 0


def admin_list() -> int:
    with get_sync_session() as db:
        admins = db.scalars(
            select(User).where(User.admin_role.is_not(None)).order_by(User.email)
        ).all()
        if not admins:
            print("No admins yet: python -m app.manage admin grant <email>")
        counts = dict(
            db.execute(
                select(AdminPasskey.user_id, func.count()).group_by(AdminPasskey.user_id)
            ).all()
        )
        for user in admins:
            factor = (
                f"2FA since {user.totp_enabled_at:%Y-%m-%d}"
                if user.totp_enabled_at
                else "2FA not set up"
            )
            keys = counts.get(user.id, 0)
            extra = f", {keys} passkey{'s' if keys != 1 else ''}" if keys else ""
            state = "" if user.is_active else ", disabled"
            print(f"{user.email}  {user.admin_role}  {factor}{extra}{state}")
        return 0


def set_official(email: str, *, on: bool, name: str | None) -> int:
    from app.api.routes_auth import _default_name
    from app.services.official import reserved_name

    name = (name or "").strip()[:100]
    if name and not on:
        print("--name goes with making an account official, not with --off", file=sys.stderr)
        return 2
    with get_sync_session() as db:
        user = _user_by_email(db, email)
        if user is None:
            return 1
        before = {"official": user.official, "display_name": user.display_name}
        user.official = on
        if name:
            user.display_name = name
        elif not on and reserved_name(user.display_name):
            user.display_name = _default_name(user.email)
        after = {"official": user.official, "display_name": user.display_name}
        record_sync(db, "user.official_changed", target=user, before=before, after=after)
        db.commit()
        state = "official" if on else "an ordinary account"
        print(f"{user.email}: {state}, shown as {user.display_name!r}")
        return 0


def indexnow_all(*, dry_run: bool) -> int:
    from app.services import indexnow

    with get_sync_session() as db:
        urls = indexnow.all_urls(db)
    if dry_run:
        print("\n".join(urls))
        print(f"{len(urls)} pages", file=sys.stderr)
        return 0
    if not indexnow.enabled():
        print(
            "IndexNow is off: it needs production, an https SITE_URL and a valid INDEXNOW_KEY",
            file=sys.stderr,
        )
        return 1
    accepted = indexnow.submit_all(urls)
    print(f"{len(urls)} pages {'sent' if accepted else 'not all accepted, see the log'}")
    return 0 if accepted else 1


def geoip_update() -> int:
    from app.services.audience import geo, jobs

    if not geo.update(db=geo.ASN):
        print(
            "The network database was not updated (GEOIP_ASN_URL empty or unreachable)",
            file=sys.stderr,
        )
    if not geo.update(db=geo.CITY):
        print(
            "The GeoIP database was not updated (GEOIP_URL empty or unreachable)", file=sys.stderr
        )
        return 1
    with get_sync_session() as db:
        placed = jobs.backfill(db)
        found = jobs.backfill_networks(db)
    print(
        f"GeoIP database ready ({geo.info().get('release')}); placed {placed} visits, "
        f"found the network of {found}"
    )
    return 0


def audience_classify(days: int | None) -> int:
    from app.models.models import Visit, utcnow
    from app.services.audience import jobs

    since = utcnow() - timedelta(days=days) if days else None
    with get_sync_session() as db:
        done = jobs.classify(db, since=since)
        rows = db.execute(
            select(Visit.verdict, func.count())
            .where(*([Visit.started_at >= since] if since else []))
            .group_by(Visit.verdict)
        ).all()
    print(f"Weighed {done} visits: " + ", ".join(f"{v} {n}" for v, n in sorted(rows)))
    return 0


def media_refresh(ids: list[str], fmt: str | None) -> int:
    from app.models.models import Debate
    from app.services.media.jobs import refresh_timeline

    if fmt:
        with get_sync_session() as db:
            rows = db.scalars(
                select(Debate.id).where(
                    Debate.media_status == "ready",
                    Debate.config_json["format"].as_string() == fmt,
                )
            )
            ids = [*ids, *(str(i) for i in rows)]
    if not ids:
        print("Nothing to refresh", file=sys.stderr)
        return 1
    for debate_id in dict.fromkeys(ids):
        try:
            print(debate_id, refresh_timeline(debate_id))
        except ValueError:
            print(debate_id, "skipped: not a debate id")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.manage", description=__doc__)
    parser.formatter_class = argparse.RawDescriptionHelpFormatter
    commands = parser.add_subparsers(dest="command", required=True)

    admin = commands.add_parser("admin", help="admin console access")
    actions = admin.add_subparsers(dest="action", required=True)
    grant = actions.add_parser("grant", help="give a role (prints the enrollment code)")
    grant.add_argument("email")
    grant.add_argument("--role", choices=ROLES, default="admin")
    for name, text in (
        ("revoke", "take the role away and end its sessions"),
        ("reset-2fa", "clear a lost authenticator and passkeys (prints a new enrollment code)"),
        ("revoke-sessions", "sign the admin out everywhere"),
        ("enroll-code", "issue a fresh enrollment code"),
    ):
        actions.add_parser(name, help=text).add_argument("email")
    actions.add_parser("list", help="who has console access")

    credits = commands.add_parser("credits", help="add or take credits through the ledger")
    credits.add_argument("email")
    credits.add_argument("amount", help="USD, e.g. 5 or -2.50")
    credits.add_argument("--reason", required=True, help="why (internal, kept in the ledger row)")
    credits.add_argument("--kind", choices=CREDIT_KINDS, default="adjustment")
    credits.add_argument("--description", help="what the user sees in the ledger")
    credits.add_argument("--yes", action="store_true", help="do not ask for confirmation")

    official = commands.add_parser("official", help="the site's own account (logo avatar, mark)")
    official.add_argument("email")
    official.add_argument("--name", help="display name to show, e.g. Debatr")
    official.add_argument("--off", action="store_true", help="make it an ordinary account again")

    index = commands.add_parser("indexnow", help="announce pages to IndexNow")
    index.add_argument("--all", action="store_true", required=True, help="every sitemap page")
    index.add_argument("--dry-run", action="store_true", help="print the pages, send nothing")

    media = commands.add_parser("media", help="audio and video files of debates")
    media_actions = media.add_subparsers(dest="action", required=True)
    refresh = media_actions.add_parser(
        "refresh-timeline", help="update ready timelines without rebuilding the audio"
    )
    refresh.add_argument("ids", nargs="*", help="debate ids")
    refresh.add_argument("--format", dest="fmt", help="every ready debate of this format")

    geoip = commands.add_parser("geoip", help="the IP databases of the Audience page")
    geoip.add_subparsers(dest="action", required=True).add_parser("update", help="fetch them now")
    audience = commands.add_parser("audience", help="visits of the site")
    weigh = audience.add_subparsers(dest="action", required=True).add_parser(
        "classify", help="weigh stored visits again: person, bot or AI agent"
    )
    weigh.add_argument("--days", type=int, default=None, help="only visits of the last N days")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    setup_logging()
    args = build_parser().parse_args(argv)
    if args.command == "admin":
        if args.action == "list":
            return admin_list()
        if args.action == "grant":
            return admin_grant(args.email, args.role)
        handlers = {
            "revoke": admin_revoke,
            "reset-2fa": admin_reset_2fa,
            "revoke-sessions": admin_revoke_sessions,
            "enroll-code": admin_enroll_code,
        }
        return handlers[args.action](args.email)
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
    if args.command == "official":
        return set_official(args.email, on=not args.off, name=args.name)
    if args.command == "indexnow":
        return indexnow_all(dry_run=args.dry_run)
    if args.command == "media":
        return media_refresh(list(args.ids), args.fmt)
    if args.command == "geoip":
        return geoip_update()
    if args.command == "audience":
        return audience_classify(args.days)
    return 2


if __name__ == "__main__":
    sys.exit(main())
