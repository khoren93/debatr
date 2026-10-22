"""The mail log (services/mail_log), its webhook (routes_mail) and the console's Mail page
filters (services/admin/mail). Pure: the database, the relay and Telegram are fakes."""

import base64
import hashlib
import hmac
import json
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql
from starlette.requests import Request

from app.api import routes_mail
from app.core.config import settings
from app.models.models import MailMessage
from app.schemas.admin import MailQuery
from app.services import alerts, email_check, mail, mail_log
from app.services.admin import mail as mail_admin

NOW = datetime(2026, 10, 23, 12, tzinfo=UTC)
SECRET = "whsec_" + base64.b64encode(b"0123456789abcdef0123456789abcdef").decode()


def _letter(**fields: Any) -> MailMessage:
    values: dict[str, Any] = {
        "id": uuid.uuid4(),
        "created_at": NOW,
        "kind": "verify",
        "to_address": "jane@example.com",
        "subject": "Confirm your email for Debatr",
        "status": "sent",
        "events_json": [],
        "delivery": None,
        "provider_id": None,
    }
    values.update(fields)
    return MailMessage(**values)


@pytest.fixture
def raised(monkeypatch: pytest.MonkeyPatch) -> list[alerts.Alert]:
    found: list[alerts.Alert] = []
    monkeypatch.setattr(alerts, "notify_soon", found.append)
    return found


# --- sending ----------------------------------------------------------------------------------


async def test_deliver_records_the_relay_answer(
    monkeypatch: pytest.MonkeyPatch, raised: list[alerts.Alert]
) -> None:
    saved: list[str] = []

    async def insert(row: MailMessage) -> bool:
        saved.append(f"insert {row.status}")
        return True

    async def finish(row: MailMessage) -> None:
        saved.append(f"finish {row.status}")

    monkeypatch.setattr(mail_log, "_insert", insert)
    monkeypatch.setattr(mail_log, "_finish", finish)
    monkeypatch.setattr(mail, "send", lambda message: mail.Outcome("sent", reply="250 OK id-1"))
    user_id = uuid.uuid4()
    letter = email_check.confirmation_mail("Jane", "Jane@Example.com", "tok")
    row = await mail_log.deliver(letter, kind="verify", user_id=user_id)
    assert saved == ["insert sending", "finish sent"]
    assert (row.status, row.reply, row.user_id) == ("sent", "250 OK id-1", user_id)
    assert row.to_address == "jane@example.com"  # matched against the webhook's address
    assert row.subject == "Confirm your email for Debatr" and row.message_id
    assert row.duration_ms is not None and raised == []


async def test_a_letter_that_could_not_be_recorded_is_still_sent(
    monkeypatch: pytest.MonkeyPatch, raised: list[alerts.Alert]
) -> None:
    finished: list[MailMessage] = []

    async def insert(row: MailMessage) -> bool:
        return False  # the database is down

    async def finish(row: MailMessage) -> None:
        finished.append(row)

    monkeypatch.setattr(mail_log, "_insert", insert)
    monkeypatch.setattr(mail_log, "_finish", finish)
    monkeypatch.setattr(
        mail, "send", lambda message: mail.Outcome("failed", error="SMTPAuthenticationError: 535")
    )
    letter = email_check.reset_mail("Jane", "jane@example.com", "tok")
    row = await mail_log.deliver(letter, kind="reset")
    assert row.status == "failed" and finished == []
    assert [alert.title for alert in raised] == ["Mail not sent"]
    assert "password reset letter to jane@example.com" in raised[0].detail


def test_failure_alerts(monkeypatch: pytest.MonkeyPatch) -> None:
    off = _letter(status="off")
    assert mail_log.failure_alert(off) is None  # development without a relay is normal
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    alert = mail_log.failure_alert(off)
    assert alert is not None and alert.severity == "critical" and alert.title == "Mail is off"
    assert alert.kind == "mail" and alert.path == "/admin/mail"
    assert mail_log.failure_alert(_letter(status="failed", kind="test")) is None  # shown in place
    assert mail_log.failure_alert(_letter(status="sent")) is None
    failed = mail_log.failure_alert(_letter(status="failed", error="timed out"))
    assert failed is not None and failed.severity == "warning" and "timed out" in failed.detail


def test_test_letter_names_who_sent_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "SITE_URL", "https://site.example")
    letter = mail_log.test_letter("ops@example.com", "boss@example.com")
    body = letter.get_body(("plain",))
    assert letter["To"] == "ops@example.com" and letter["Subject"] == "Test letter from Debatr"
    assert body is not None and "boss@example.com" in body.get_content()


# --- the webhook ------------------------------------------------------------------------------


def _signature(body: bytes, msg_id: str = "msg_1", stamp: int | None = None) -> dict[str, str]:
    stamp = stamp if stamp is not None else int(NOW.timestamp())
    key = base64.b64decode(SECRET.removeprefix("whsec_"))
    digest = hmac.new(key, f"{msg_id}.{stamp}.".encode() + body, hashlib.sha256).digest()
    return {
        "svix-id": msg_id,
        "svix-timestamp": str(stamp),
        "svix-signature": f"v1,bm90IHRoaXMgb25l v1,{base64.b64encode(digest).decode()}",
    }


def test_signature_check() -> None:
    body = b'{"type":"email.delivered"}'
    now = NOW.timestamp()
    assert mail_log.signature_ok(SECRET, _signature(body), body, now)
    assert not mail_log.signature_ok(SECRET, _signature(body), body + b" ", now)  # tampered
    assert not mail_log.signature_ok(SECRET, _signature(body), body, now + 600)  # replayed late
    assert not mail_log.signature_ok("whsec_" + "A" * 44, _signature(body), body, now)
    assert not mail_log.signature_ok(SECRET, {}, body, now)
    assert not mail_log.signature_ok("whsec_not base64!", _signature(body), body, now)
    standard = {k.replace("svix-", "webhook-"): v for k, v in _signature(body).items()}
    assert mail_log.signature_ok(SECRET, standard, body, now)  # Standard Webhooks names


def test_events_keep_the_furthest_state() -> None:
    row = _letter()
    at = NOW + timedelta(seconds=5)
    data = {"email_id": "re_1", "to": ["jane@example.com"]}
    assert mail_log.record_event(row, "email.sent", data, event_id="e1", at=at) is None
    assert row.provider_id == "re_1" and row.events_json[0]["type"] == "sent"
    assert mail_log.record_event(row, "email.delivered", data, event_id="e2", at=at) == "delivered"
    # Out of order: a delay reported after the delivery changes nothing.
    assert mail_log.record_event(row, "email.delivery_delayed", data, event_id="e3", at=at) is None
    assert row.delivery == "delivered"
    # The same event again (the service retries until it hears 2xx) is kept once.
    assert mail_log.record_event(row, "email.delivered", data, event_id="e2", at=at) is None
    assert [e["type"] for e in row.events_json] == ["sent", "delivered", "delivery_delayed"]
    assert (
        mail_log.record_event(row, "email.complained", data, event_id="e4", at=at) == "complained"
    )
    assert row.delivery == "complained" and row.delivery_at == at


def test_bounces_say_why() -> None:
    row = _letter()
    data = {
        "email_id": "re_2",
        "bounce": {"type": "Permanent", "subType": "General", "message": "Mailbox does not exist"},
    }
    assert mail_log.record_event(row, "email.bounced", data, event_id=None, at=NOW) == "bounced"
    note = "Permanent · General · Mailbox does not exist"
    assert row.events_json[-1]["note"] == note
    alert = mail_log.problem_alert(row, "bounced")
    assert alert is not None and alert.title == "Letter bounced" and note in alert.detail
    assert mail_log.problem_alert(row, "delivered") is None
    assert mail_log.problem_alert(_letter(kind="test"), "bounced") is None


class FakeDB:
    """`scalar` answers from a queue; the statements are kept as SQL."""

    def __init__(self, answers: list[Any]) -> None:
        self.answers: Iterator[Any] = iter(answers)
        self.sql: list[str] = []
        self.commits = 0

    async def scalar(self, statement: Any) -> Any:
        self.sql.append(str(statement.compile(dialect=postgresql.dialect())))
        return next(self.answers)

    async def commit(self) -> None:
        self.commits += 1


async def test_letters_are_found_by_id_then_by_address() -> None:
    row = _letter()
    by_id = FakeDB([row])
    assert await mail_log.find_letter(by_id, {"email_id": "re_1"}) is row  # type: ignore[arg-type]
    assert len(by_id.sql) == 1 and "provider_id" in by_id.sql[0]

    data = {
        "email_id": "re_9",
        "message_id": "<x@relay.example>",
        "to": ["Jane@Example.com"],
        "subject": "Confirm your email for Debatr",
        "created_at": "2026-10-23T12:00:03.5+00:00",
    }
    # Not by the service's id, not by Message-ID, not named in the relay's answer: the newest
    # letter to the address with the subject, sent around that time.
    db = FakeDB([None, None, None, row])
    assert await mail_log.find_letter(db, data) is row  # type: ignore[arg-type]
    assert "message_id" in db.sql[1] and "LIKE" in db.sql[2] and "subject" in db.sql[3]
    assert await mail_log.find_letter(FakeDB([]), {"to": []}) is None  # type: ignore[arg-type]


def _request(body: bytes, headers: dict[str, str]) -> Request:
    sent = False

    async def receive() -> dict[str, Any]:
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    return Request({"type": "http", "method": "POST", "path": "/", "headers": raw}, receive)


async def test_webhook_route(monkeypatch: pytest.MonkeyPatch) -> None:
    body = json.dumps({"type": "email.delivered", "data": {"email_id": "re_1"}}).encode()
    applied: list[tuple[str, str | None]] = []

    async def apply(db: Any, event: dict[str, Any], *, event_id: str | None) -> None:
        applied.append((event["type"], event_id))

    monkeypatch.setattr(mail_log, "apply_event", apply)
    monkeypatch.setattr(routes_mail.time, "time", lambda: NOW.timestamp())
    monkeypatch.setattr(settings, "MAIL_WEBHOOK_SECRET", None)
    with pytest.raises(HTTPException) as off:
        await routes_mail.mail_events(_request(body, _signature(body)), db=None)  # type: ignore[arg-type]
    assert off.value.status_code == 404
    monkeypatch.setattr(settings, "MAIL_WEBHOOK_SECRET", SECRET)
    with pytest.raises(HTTPException) as bad:
        await routes_mail.mail_events(_request(body, _signature(b"other")), db=None)  # type: ignore[arg-type]
    assert bad.value.status_code == 401 and applied == []
    answer = await routes_mail.mail_events(_request(body, _signature(body)), db=None)  # type: ignore[arg-type]
    assert answer.status_code == 204 and applied == [("email.delivered", "msg_1")]


# --- the console's filters --------------------------------------------------------------------


def _where(query: MailQuery) -> str:
    found = mail_admin.conditions(query, NOW)
    return " AND ".join(str(c.compile(dialect=postgresql.dialect())) for c in found)


def test_mail_page_filters() -> None:
    assert _where(MailQuery()) == ""
    problems = _where(MailQuery(status="problems"))
    assert "mail_messages.status IN" in problems and "mail_messages.delivery IN" in problems
    assert "delivery IS NULL" in _where(MailQuery(status="waiting"))
    assert "mail_messages.delivery =" in _where(MailQuery(status="bounced"))
    assert "mail_messages.status =" in _where(MailQuery(status="off"))
    searched = _where(MailQuery(q=str(uuid.uuid4())))
    assert "mail_messages.id =" in searched and "ILIKE" in searched.upper()
    assert "mail_messages.id =" not in _where(MailQuery(q="jane@"))


def test_letters_out_never_carry_the_text() -> None:
    row = _letter(
        events_json=[{"id": "e1", "type": "delivered", "at": NOW.isoformat(), "note": None}]
    )
    out = mail_admin.letter_out(row)
    assert out["events"] == [{"type": "delivered", "at": NOW.isoformat(), "note": None}]
    assert not {"text", "html", "body", "token", "link"} & set(out)


def test_relay_settings_hide_the_password(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "MAIL_SMTP_HOST", "smtp.relay.example")
    monkeypatch.setattr(settings, "MAIL_SMTP_PASSWORD", "re_secret")
    monkeypatch.setattr(settings, "MAIL_FROM", "Site <noreply@site.example>")
    monkeypatch.setattr(settings, "MAIL_REPLY_TO", "")
    monkeypatch.setattr(settings, "SUPPORT_EMAIL", "help@site.example")
    relay = mail_admin.relay()
    assert relay["configured"] and relay["reply_to"] == "help@site.example"
    assert "re_secret" not in json.dumps(relay)
