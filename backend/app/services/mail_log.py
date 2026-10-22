"""The letters the site sends, recorded for the console's Mail page (`mail_messages`).

- `deliver` sends a letter through services/mail and records it: the account and the address,
  the kind and subject (never the text: it carries one-time links), what the relay said and how
  long it took. The API calls it in a background task after its response; the console's test
  letter waits for it. A letter the relay refused, or one not sent because production has no
  relay, raises the `mail` alert.
- The sending service reports what happened next through its webhook (`POST /api/mail/events`,
  signed like Resend's, which uses Svix: `signature_ok`). `apply_event` finds the letter — by
  the service's id, our Message-ID or, for its first event, the address and subject a moment
  after we sent it (Resend's relay gives a letter an id and Message-ID of its own) — and keeps
  the event and the delivery state.
- `prune_job` (scheduler) deletes letters older than MAIL_LOG_DAYS.
"""

import asyncio
import base64
import binascii
import hashlib
import hmac
import logging
import time
import uuid
from collections.abc import Mapping
from datetime import datetime, timedelta
from email.message import EmailMessage
from email.utils import parseaddr
from typing import Any, Literal

from sqlalchemy import delete, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import AsyncSessionLocal
from app.models.models import MailMessage, utcnow
from app.services import alerts, mail

logger = logging.getLogger(__name__)

MailKind = Literal["verify", "reset", "test"]
KIND_LABELS: dict[str, str] = {"verify": "confirmation", "reset": "password reset", "test": "test"}
# Webhook event → the delivery state it reports (None: none of its own, it only links the
# service's id to our row). Other events (opened, clicked, received…) are ignored.
EVENT_DELIVERY: dict[str, str | None] = {
    "email.sent": None,
    "email.delivered": "delivered",
    "email.delivery_delayed": "delayed",
    "email.bounced": "bounced",
    "email.complained": "complained",
    "email.suppressed": "suppressed",
    "email.failed": "failed",
}
# Deliveries that did not reach the inbox (or did, and were marked as spam).
PROBLEMS = ("bounced", "complained", "suppressed", "failed")
# Events may come out of order (a delay reported after the delivery): a state replaces the
# one before unless it ranks lower.
RANK = {"delayed": 0, "delivered": 1, "bounced": 2, "suppressed": 2, "failed": 2, "complained": 3}
MATCH_WINDOW = timedelta(minutes=30)
EVENTS_KEPT = 20
SIGNATURE_TOLERANCE_SECONDS = 5 * 60
PRUNE_SECONDS = 6 * 3600
PRUNE_TIMEOUT = 120


def address_of(header: object) -> str:
    return parseaddr(str(header or ""))[1].strip().lower()[:320]


# --- sending ----------------------------------------------------------------------------------


async def _insert(row: MailMessage) -> bool:
    try:
        async with AsyncSessionLocal() as db:
            db.add(row)
            await db.commit()
        return True
    except (SQLAlchemyError, OSError):
        logger.warning("Could not record the mail to %s", row.to_address, exc_info=True)
        return False


async def _finish(row: MailMessage) -> None:
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(MailMessage)
                .where(MailMessage.id == row.id)
                .values(
                    status=row.status, reply=row.reply, error=row.error, duration_ms=row.duration_ms
                )
            )
            await db.commit()
    except (SQLAlchemyError, OSError):
        logger.warning("Could not record the outcome of mail %s", row.id, exc_info=True)


def failure_alert(row: MailMessage) -> alerts.Alert | None:
    """The alert for a letter the relay did not take (none for the console's test letters:
    the console shows their outcome, nor for development without a relay)."""
    if row.kind == "test" or row.status not in ("failed", "off"):
        return None
    label = KIND_LABELS.get(row.kind, row.kind)
    if row.status == "off":
        if not settings.is_production:
            return None
        return alerts.Alert(
            kind="mail",
            title="Mail is off",
            detail=f"no relay set up (MAIL_SMTP_HOST, _PASSWORD, MAIL_FROM): a {label} letter to "
            f"{row.to_address} was not sent",
            severity="critical",
            path="/admin/mail",
            quiet=6 * alerts.HOUR,
        )
    return alerts.Alert(
        kind="mail",
        title="Mail not sent",
        detail=f"{label} letter to {row.to_address}: {(row.error or 'unknown error')[:200]}",
        severity="warning",
        path="/admin/mail?status=problems",
        quiet=alerts.HOUR,
    )


async def deliver(
    message: EmailMessage, *, kind: MailKind, user_id: uuid.UUID | None = None
) -> MailMessage:
    """Send the letter now and record it. Never raises: a letter that could not be recorded is
    still sent, one that could not be sent is recorded as such."""
    row = MailMessage(
        id=uuid.uuid4(),
        created_at=utcnow(),
        user_id=user_id,
        kind=kind,
        to_address=address_of(message["To"]),
        subject=str(message["Subject"] or "")[:200],
        message_id=str(message["Message-ID"] or "")[:255] or None,
        status="sending",
        events_json=[],
    )
    recorded = await _insert(row)
    started = time.monotonic()
    outcome = await asyncio.to_thread(mail.send, message)
    row.status, row.reply, row.error = outcome.status, outcome.reply, outcome.error
    row.duration_ms = round((time.monotonic() - started) * 1000)
    if recorded:
        await _finish(row)
    alert = failure_alert(row)
    if alert is not None:
        alerts.notify_soon(alert)
    return row


def test_letter(to: str, sent_by: str) -> EmailMessage:
    """The console's test letter (Mail page)."""
    text, html = mail.letter(
        title="Test letter",
        lines=[
            "This letter checks that the site can send mail.",
            f"Sent from the admin console by {sent_by}.",
        ],
        button="Open Debatr",
        url=settings.SITE_URL,
        footer="Nothing to do: you can delete it.",
    )
    return mail.build_message(to, "Test letter from Debatr", text, html)


# --- the sending service's webhook ------------------------------------------------------------


def signature_ok(secret: str, headers: Mapping[str, str], body: bytes, now: float) -> bool:
    """A Svix / Standard Webhooks signature: base64 HMAC-SHA256 of "{id}.{timestamp}.{body}"
    with the secret after "whsec_", within SIGNATURE_TOLERANCE_SECONDS of now."""
    msg_id = headers.get("svix-id") or headers.get("webhook-id")
    stamp = headers.get("svix-timestamp") or headers.get("webhook-timestamp")
    signatures = headers.get("svix-signature") or headers.get("webhook-signature")
    if not msg_id or not stamp or not signatures:
        return False
    try:
        sent_at = int(stamp)
        key = base64.b64decode(secret.removeprefix("whsec_"), validate=True)
    except (ValueError, binascii.Error):
        return False
    if abs(now - sent_at) > SIGNATURE_TOLERANCE_SECONDS:
        return False
    digest = hmac.new(key, f"{msg_id}.{stamp}.".encode() + body, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode()
    for part in signatures.split():
        version, _, signature = part.partition(",")
        if version == "v1" and hmac.compare_digest(signature, expected):
            return True
    return False


def parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else None


def event_note(data: Mapping[str, Any]) -> str | None:
    """Why a letter did not arrive, in the service's words (bounce type and message…)."""
    for key in ("bounce", "failed", "suppressed", "complaint"):
        detail = data.get(key)
        if isinstance(detail, Mapping):
            parts = [detail.get("type"), detail.get("subType"), detail.get("message")]
            parts.append(detail.get("reason"))
            text = " · ".join(str(part) for part in parts if part)
            if text:
                return text[:300]
    return None


def record_event(
    row: MailMessage,
    event_type: str,
    data: Mapping[str, Any],
    *,
    event_id: str | None,
    at: datetime,
) -> str | None:
    """Keep a webhook event on its letter. Returns the new delivery state when it changed."""
    events = list(row.events_json or [])
    if event_id and any(event.get("id") == event_id for event in events):
        return None  # the service sends an event again until it hears 2xx
    email_id = str(data.get("email_id") or "")[:64]
    if email_id and not row.provider_id:
        row.provider_id = email_id
    events.append(
        {
            "id": event_id,
            "type": event_type.removeprefix("email."),
            "at": at.isoformat(),
            "note": event_note(data),
        }
    )
    row.events_json = events[-EVENTS_KEPT:]
    state = EVENT_DELIVERY.get(event_type)
    if state is None or state == row.delivery:
        return None
    if row.delivery is not None and RANK[state] < RANK.get(row.delivery, 0):
        return None
    row.delivery, row.delivery_at = state, at
    return state


def _recipient(data: Mapping[str, Any]) -> str:
    to = data.get("to")
    first = to[0] if isinstance(to, list) and to else to
    return address_of(first) if isinstance(first, str) else ""


async def find_letter(db: AsyncSession, data: Mapping[str, Any]) -> MailMessage | None:
    email_id = str(data.get("email_id") or "")[:64]
    if email_id:
        row = await db.scalar(select(MailMessage).where(MailMessage.provider_id == email_id))
        if row is not None:
            return row
    message_id = str(data.get("message_id") or "")[:255]
    if message_id:
        row = await db.scalar(
            select(MailMessage).where(MailMessage.message_id == message_id).limit(1)
        )
        if row is not None:
            return row
    to = _recipient(data)
    if not to:
        return None
    around = parse_time(data.get("created_at")) or utcnow()
    query = select(MailMessage).where(
        MailMessage.to_address == to,
        MailMessage.provider_id.is_(None),
        MailMessage.status == "sent",
        MailMessage.created_at.between(around - MATCH_WINDOW, around + MATCH_WINDOW),
    )
    if email_id:
        # The relay's answer may name the service's id ("250 OK <id>").
        named = await db.scalar(
            query.where(MailMessage.reply.contains(email_id, autoescape=True)).limit(1)
        )
        if named is not None:
            return named
    subject = data.get("subject")
    if isinstance(subject, str) and subject:
        query = query.where(MailMessage.subject == subject[:200])
    return await db.scalar(query.order_by(MailMessage.created_at.desc()).limit(1))


def problem_alert(row: MailMessage, state: str) -> alerts.Alert | None:
    if state not in PROBLEMS or row.kind == "test":
        return None
    titles = {
        "bounced": "Letter bounced",
        "complained": "Letter marked as spam",
        "suppressed": "Letter not sent: address suppressed",
        "failed": "Letter not delivered",
    }
    note = next((e.get("note") for e in reversed(row.events_json or []) if e.get("note")), None)
    label = KIND_LABELS.get(row.kind, row.kind)
    return alerts.Alert(
        kind="mail",
        title=titles[state],
        detail=f"{label} letter to {row.to_address}" + (f": {note[:200]}" if note else ""),
        severity="warning",
        path="/admin/mail?status=problems",
        quiet=alerts.HOUR,
    )


async def apply_event(
    db: AsyncSession, event: Mapping[str, Any], *, event_id: str | None
) -> MailMessage | None:
    """Keep one webhook event (commits). Unknown letters and events are let go: the service
    keeps sending an event until it gets 2xx, and nothing would change."""
    event_type = str(event.get("type") or "")
    data = event.get("data")
    if event_type not in EVENT_DELIVERY or not isinstance(data, Mapping):
        return None
    row = await find_letter(db, data)
    if row is None:
        logger.info("Mail event %s for an unknown letter (%s)", event_type, data.get("email_id"))
        return None
    at = parse_time(event.get("created_at")) or utcnow()
    state = record_event(row, event_type, data, event_id=event_id, at=at)
    await db.commit()
    alert = problem_alert(row, state) if state else None
    if alert is not None:
        alerts.notify_soon(alert)
    return row


# --- upkeep -----------------------------------------------------------------------------------


def prune_job() -> int:
    """RQ job (scheduler): delete letters older than MAIL_LOG_DAYS (0 keeps them)."""
    from app.core.sync_db import get_sync_session

    if settings.MAIL_LOG_DAYS <= 0:
        return 0
    cutoff = utcnow() - timedelta(days=settings.MAIL_LOG_DAYS)
    with get_sync_session() as db:
        result = db.execute(delete(MailMessage).where(MailMessage.created_at < cutoff))
        db.commit()
    gone = int(getattr(result, "rowcount", 0) or 0)
    if gone:
        logger.info("Deleted %d letters older than %d days", gone, settings.MAIL_LOG_DAYS)
    return gone
