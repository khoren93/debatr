"""Email confirmation and password reset (services/email_check, services/mail, routes_auth) and
what waits for a confirmed address (publishing, top-ups). Pure: Redis, the database and SMTP are
fakes."""

import smtplib
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, ClassVar

import pytest
from fastapi import BackgroundTasks, HTTPException
from starlette.requests import Request

from app.api import routes_auth, routes_billing, routes_debates
from app.core.config import settings
from app.models.models import User
from app.schemas.auth import (
    ForgotPasswordRequest,
    RegisterRequest,
    ResetPasswordRequest,
    VerifyEmailRequest,
)
from app.schemas.billing import CheckoutRequest
from app.schemas.schemas import PublishRequest
from app.services import email_check, mail, orchestrator

NOW = datetime(2026, 10, 22, 12, tzinfo=UTC)


class FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.data.get(key)

    async def getdel(self, key: str) -> str | None:
        return self.data.pop(key, None)

    async def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self.data[key] = value
        return True


class FakeDB:
    def __init__(self, user: User | None = None) -> None:
        self.user = user
        self.commits = 0

    async def get(self, model: type, key: Any) -> User | None:
        return self.user if self.user is not None and self.user.id == key else None

    async def scalar(self, statement: Any) -> Any:
        return self.user

    async def commit(self) -> None:
        self.commits += 1


def _user(*, required: bool = True, verified: bool = False, epoch: int = 1) -> User:
    return User(
        id=uuid.uuid4(),
        email="jane@example.com",
        display_name="Jane",
        password_hash="old",
        is_active=True,
        session_epoch=epoch,
        email_check_required=required,
        email_verified_at=NOW if verified else None,
        admin_role=None,
        avatar_seed="",
        official=False,
        credits_usd=0,
        created_at=NOW,
    )


def _request() -> Request:
    return Request({"type": "http", "method": "POST", "path": "/", "headers": [], "session": {}})


@pytest.fixture
def redis(monkeypatch: pytest.MonkeyPatch) -> FakeRedis:
    fake = FakeRedis()
    monkeypatch.setattr(email_check, "get_async_redis", lambda: fake)
    return fake


@pytest.fixture
def published(monkeypatch: pytest.MonkeyPatch) -> list[User]:
    """`publish_waiting` calls (it queries the database: tested on its own below)."""
    calls: list[User] = []

    async def publish(db: Any, user: User) -> int:
        calls.append(user)
        return 2

    monkeypatch.setattr(email_check, "publish_waiting", publish)
    return calls


@pytest.fixture(autouse=True)
def no_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    async def allow(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(routes_auth, "enforce_limit", allow)


# --- the rule ---------------------------------------------------------------------------------


def test_new_accounts_wait_for_the_address_older_ones_do_not() -> None:
    assert email_check.pending(_user())
    assert not email_check.pending(_user(verified=True))
    assert not email_check.pending(_user(required=False))


def test_confirm_marks_once() -> None:
    user = _user()
    assert email_check.confirm(user)
    assert user.email_verified_at is not None
    assert not email_check.confirm(user)


# --- links ------------------------------------------------------------------------------------


async def test_a_confirmation_link_opens_again_a_reset_link_once(redis: FakeRedis) -> None:
    user = _user()
    verify = await email_check.issue("verify", user)
    reset = await email_check.issue("reset", user)
    assert verify not in str(redis.data)  # only hashes are stored
    assert (await email_check.read("verify", verify) or {}).get("uid") == str(user.id)
    assert await email_check.read("verify", verify) is not None
    assert await email_check.read("reset", reset) is not None
    assert await email_check.read("reset", reset) is None
    assert await email_check.read("verify", "unknown-token") is None
    assert await email_check.read("reset", verify) is None  # kinds do not mix


async def test_a_link_belongs_to_the_address_and_the_password_it_was_sent_for(
    redis: FakeRedis,
) -> None:
    user = _user()
    data = await email_check.read("reset", await email_check.issue("reset", user))
    assert email_check.matches(data, user, epoch=True)
    user.session_epoch += 1  # the password changed since
    assert not email_check.matches(data, user, epoch=True)
    assert email_check.matches(data, user)
    user.email = "other@example.com"
    assert not email_check.matches(data, user)
    user.email, user.is_active = "jane@example.com", False
    assert not email_check.matches(data, user)


# --- letters ----------------------------------------------------------------------------------


def test_letters_link_the_site_and_escape_the_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "SITE_URL", "https://site.example")
    monkeypatch.setattr(settings, "MAIL_FROM", "Site <noreply@site.example>")
    monkeypatch.setattr(settings, "MAIL_REPLY_TO", "")
    monkeypatch.setattr(settings, "SUPPORT_EMAIL", "help@site.example")
    letter = email_check.confirmation_mail("<b>Jane</b>", "jane@example.com", "tok123")
    assert letter["To"] == "jane@example.com"
    assert letter["From"] == "Site <noreply@site.example>"
    assert letter["Reply-To"] == "help@site.example"  # no MAIL_REPLY_TO: the contact address
    assert letter["Message-ID"].endswith("@site.example>")
    assert letter["Auto-Submitted"] == "auto-generated"
    text = letter.get_body(("plain",))
    html = letter.get_body(("html",))
    assert text is not None and html is not None
    assert "https://site.example/verify-email?token=tok123" in text.get_content()
    assert "&lt;b&gt;Jane&lt;/b&gt;" in html.get_content()
    reset = email_check.reset_mail("Jane", "jane@example.com", "tok456")
    reset_text = reset.get_body(("plain",))
    assert reset_text is not None and "/reset-password?token=tok456" in reset_text.get_content()
    monkeypatch.setattr(settings, "MAIL_REPLY_TO", "replies@site.example")
    assert (
        email_check.reset_mail("Jane", "jane@example.com", "t")["Reply-To"]
        == "replies@site.example"
    )
    monkeypatch.setattr(settings, "MAIL_REPLY_TO", "")
    monkeypatch.setattr(settings, "SUPPORT_EMAIL", "")
    assert email_check.reset_mail("Jane", "jane@example.com", "t")["Reply-To"] is None


class FakeSMTP:
    """The relay (`mail._TLSRelay` / `_Relay`): records letters, refuses the login on `fail`."""

    sent: ClassVar[list[Any]] = []
    fail = False

    def __init__(self, host: str, port: int, **kwargs: Any) -> None:
        self.host, self.port = host, port
        self.reply = ""

    def __enter__(self) -> "FakeSMTP":
        return self

    def __exit__(self, *exc: Any) -> None: ...

    def starttls(self, **kwargs: Any) -> None: ...

    def login(self, user: str, password: str) -> None:
        if FakeSMTP.fail:
            raise smtplib.SMTPAuthenticationError(535, b"bad key")

    def send_message(self, message: Any) -> None:
        FakeSMTP.sent.append((self.host, self.port, message["Subject"]))
        self.reply = "250 OK queued as 7f3e"


def test_send_uses_the_relay_and_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    letter = email_check.reset_mail("Jane", "jane@example.com", "tok")
    monkeypatch.setattr(settings, "MAIL_SMTP_HOST", "")
    off = mail.send(letter)  # no relay: logged only
    assert off.status == "off" and off.error and "MAIL_SMTP_HOST" in off.error
    monkeypatch.setattr(settings, "MAIL_SMTP_HOST", "smtp.relay.example")
    monkeypatch.setattr(settings, "MAIL_SMTP_PASSWORD", "re_test")
    monkeypatch.setattr(settings, "MAIL_FROM", "")
    assert mail.send(letter).status == "off"  # no sender address either
    monkeypatch.setattr(settings, "MAIL_FROM", "Site <noreply@site.example>")
    monkeypatch.setattr(mail, "_TLSRelay", FakeSMTP)
    monkeypatch.setattr(mail, "_Relay", FakeSMTP)
    FakeSMTP.sent, FakeSMTP.fail = [], False
    monkeypatch.setattr(settings, "MAIL_SMTP_PORT", 465)  # TLS from the start
    sent = mail.send(letter)
    assert sent == mail.Outcome("sent", reply="250 OK queued as 7f3e")
    assert FakeSMTP.sent == [("smtp.relay.example", 465, "Reset your Debatr password")]
    monkeypatch.setattr(settings, "MAIL_SMTP_PORT", 587)  # STARTTLS
    assert mail.send(letter).status == "sent" and FakeSMTP.sent[-1][1] == 587
    FakeSMTP.fail = True
    failed = mail.send(letter)
    assert failed.status == "failed"
    assert failed.error == "SMTPAuthenticationError: 535 bad key"


def test_an_unreachable_relay_says_where_and_why(monkeypatch: pytest.MonkeyPatch) -> None:
    def blocked(host: str, port: int, **kwargs: Any) -> Any:
        raise TimeoutError("timed out")

    monkeypatch.setattr(settings, "MAIL_SMTP_HOST", "smtp.relay.example")
    monkeypatch.setattr(settings, "MAIL_SMTP_PASSWORD", "re_test")
    monkeypatch.setattr(settings, "MAIL_FROM", "Site <noreply@site.example>")
    monkeypatch.setattr(mail, "_TLSRelay", blocked)
    monkeypatch.setattr(mail, "_Relay", blocked)
    letter = email_check.reset_mail("Jane", "jane@example.com", "tok")
    monkeypatch.setattr(settings, "MAIL_SMTP_PORT", 465)
    assert mail.send(letter).error == (
        "TimeoutError: timed out (smtp.relay.example:465: hosts often block outgoing port 465, "
        "set MAIL_SMTP_PORT=587)"
    )
    monkeypatch.setattr(settings, "MAIL_SMTP_PORT", 587)
    assert mail.send(letter).error == "TimeoutError: timed out (smtp.relay.example:587)"


def test_the_relay_keeps_its_answer_to_the_letter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(smtplib.SMTP, "data", lambda self, msg: (250, b"OK id=ab12"))
    relay = mail._Relay()  # no host: nothing connects
    assert relay.data(b"letter") == (250, b"OK id=ab12")
    assert relay.reply == "250 OK id=ab12"
    refused = smtplib.SMTPRecipientsRefused({"x@example.com": (550, b"no such user")})
    assert mail.error_text(refused) == "SMTPRecipientsRefused: x@example.com: 550 no such user"
    assert mail.error_text(TimeoutError("timed out")) == "TimeoutError: timed out"


# --- routes -----------------------------------------------------------------------------------


async def test_register_mails_a_confirmation(monkeypatch: pytest.MonkeyPatch) -> None:
    letters: list[str] = []

    async def mail_link(kind: str, user: Any) -> str:
        letters.append(kind)
        return "letter"

    class DB:
        async def scalar(self, statement: Any) -> None:
            return None

        def add(self, obj: Any) -> None:
            obj.id = uuid.uuid4()

        async def flush(self) -> None: ...

        async def commit(self) -> None: ...

        async def refresh(self, obj: Any) -> None:
            obj.credits_usd, obj.created_at, obj.official = 0, NOW, False
            obj.session_epoch, obj.email_check_required = 0, True

    monkeypatch.setattr(routes_auth.email_check, "mail_link", mail_link)
    background = BackgroundTasks()
    body = RegisterRequest(email="new@example.com", password="long enough pass")
    out = await routes_auth.register(body, _request(), background, db=DB())  # type: ignore[arg-type]
    assert out.email_required and not out.email_verified
    assert letters == ["verify"] and len(background.tasks) == 1


async def test_forgot_password_answers_the_same_for_any_address(
    monkeypatch: pytest.MonkeyPatch, redis: FakeRedis
) -> None:
    sent = BackgroundTasks()
    await routes_auth.forgot_password(
        ForgotPasswordRequest(email="Nobody@Example.com"),
        _request(),
        sent,
        db=FakeDB(),  # type: ignore[arg-type]
    )
    assert sent.tasks == [] and redis.data == {}
    user = _user()
    await routes_auth.forgot_password(
        ForgotPasswordRequest(email="jane@example.com"),
        _request(),
        sent,
        db=FakeDB(user),  # type: ignore[arg-type]
    )
    assert len(sent.tasks) == 1 and len(redis.data) == 1


async def test_reset_sets_the_password_once_confirms_and_ends_other_sessions(
    redis: FakeRedis, published: list[User]
) -> None:
    user = _user()
    token = await email_check.issue("reset", user)
    request = _request()
    body = ResetPasswordRequest(token=token, password="a new password")
    out = await routes_auth.reset_password(body, request, db=FakeDB(user))  # type: ignore[arg-type]
    assert user.password_hash != "old" and user.session_epoch == 2
    assert user.email_verified_at is not None and out.email_verified
    assert published == [user]
    assert request.session.get("uid") == str(user.id)
    with pytest.raises(HTTPException) as again:
        await routes_auth.reset_password(body, _request(), db=FakeDB(user))  # type: ignore[arg-type]
    assert again.value.status_code == 400


async def test_a_reset_link_dies_with_a_password_change(redis: FakeRedis) -> None:
    user = _user()
    token = await email_check.issue("reset", user)
    user.session_epoch += 1
    with pytest.raises(HTTPException):
        await routes_auth.reset_password(
            ResetPasswordRequest(token=token, password="a new password"),
            _request(),
            db=FakeDB(user),  # type: ignore[arg-type]
        )
    assert user.password_hash == "old"


async def test_verify_confirms_and_publishes_what_waited(
    redis: FakeRedis, published: list[User]
) -> None:
    user = _user()
    token = await email_check.issue("verify", user)
    first = await routes_auth.verify_email(VerifyEmailRequest(token=token), db=FakeDB(user))  # type: ignore[arg-type]
    assert first.published == 2 and user.email_verified_at is not None
    again = await routes_auth.verify_email(VerifyEmailRequest(token=token), db=FakeDB(user))  # type: ignore[arg-type]
    assert again.ok and again.published == 0 and published == [user]
    with pytest.raises(HTTPException):
        await routes_auth.verify_email(
            VerifyEmailRequest(token="not-a-real-token"),
            db=FakeDB(user),  # type: ignore[arg-type]
        )


# --- what waits for the address ---------------------------------------------------------------


def _finished(owner: User) -> Any:
    verdict = SimpleNamespace(turn_type="verdict", text="Winner: A", error=None)
    return SimpleNamespace(
        id=uuid.uuid4(),
        user=owner,
        user_id=owner.id,
        status="completed",
        is_public=False,
        slug=None,
        published_at=None,
        moderation_status="approved",
        moderation_json={},
        config_json={"auto_publish": True, "topic": "Tabs or spaces?"},
        turns=[verdict],
        motion_id=None,
        category=None,
    )


class SyncDB:
    def scalar(self, statement: Any) -> None:
        return None


def test_auto_publish_waits_for_the_owners_address() -> None:
    debate = _finished(_user())
    orchestrator._auto_publish(SyncDB(), debate)  # type: ignore[arg-type]
    assert not debate.is_public
    ready = _finished(_user(verified=True))
    orchestrator._auto_publish(SyncDB(), ready)  # type: ignore[arg-type]
    assert ready.is_public and ready.slug


async def test_publish_keeps_the_wish_until_the_address_is_confirmed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = _user()
    debate = _finished(owner)

    async def load(db: Any, debate_id: str, **kw: Any) -> Any:
        return debate

    monkeypatch.setattr(routes_debates, "load_debate", load)
    with pytest.raises(HTTPException) as refused:
        await routes_debates.publish_debate(
            str(debate.id),
            PublishRequest(),
            _request(),
            user=owner,
            db=FakeDB(),  # type: ignore[arg-type]
        )
    assert refused.value.status_code == 403 and "jane@example.com" in str(refused.value.detail)
    assert debate.moderation_json["publish_requested"] and not debate.is_public


async def test_publish_waiting_publishes_approved_clean_wishes() -> None:
    owner = _user(verified=True)
    wanted, unwanted = _finished(owner), _finished(owner)
    unwanted.config_json = {"auto_publish": False}

    class DB(FakeDB):
        async def scalars(self, statement: Any) -> list[Any]:
            return [wanted, unwanted]

    db = DB()
    assert await email_check.publish_waiting(db, owner) == 1  # type: ignore[arg-type]
    assert wanted.is_public and not unwanted.is_public and db.commits == 1


async def test_top_ups_wait_for_the_address() -> None:
    with pytest.raises(HTTPException) as refused:
        await routes_billing.checkout(CheckoutRequest(amount_usd=5), user=_user(), db=None)  # type: ignore[arg-type]
    assert refused.value.status_code == 403
