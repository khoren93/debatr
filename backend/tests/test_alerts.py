"""Operator alerts: the rules, the Telegram message, sending (and keeping the bot token out of
errors), muting, antispam and the "seen before" bookkeeping.

Pure: Telegram is an httpx.MockTransport, Redis a small fake.
"""

import json
from typing import Any

import httpx
import pytest

from app.core.config import settings
from app.services import alert_events, alerts
from app.services.alerts import Alert, DebateStart, Facts

TOKEN = "123456:secret-bot-token"


class FakeRedis:
    """The Redis calls of the alerts (sync)."""

    def __init__(self) -> None:
        self.data: dict[str, Any] = {}
        self.lists: dict[str, list[str]] = {}

    def set(self, key: str, value: Any, ex: int | None = None, nx: bool = False) -> bool:
        if nx and key in self.data:
            return False
        self.data[key] = value
        return True

    def get(self, key: str) -> Any:
        return self.data.get(key)

    def lpush(self, key: str, value: str) -> int:
        self.lists.setdefault(key, []).insert(0, value)
        return len(self.lists[key])

    def ltrim(self, key: str, start: int, end: int) -> bool:
        self.lists[key] = self.lists.get(key, [])[start : end + 1]
        return True

    def incr(self, key: str) -> int:
        self.data[key] = int(self.data.get(key, 0)) + 1
        return self.data[key]

    def expire(self, key: str, seconds: int, nx: bool = False) -> bool:
        return key in self.data


@pytest.fixture
def telegram(monkeypatch: pytest.MonkeyPatch) -> list[httpx.Request]:
    """Telegram configured and answering 200; the requests it got."""
    sent: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(settings, "ALERT_TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setattr(settings, "ALERT_TELEGRAM_CHAT_ID", "42")
    monkeypatch.setattr(alerts, "TRANSPORT", httpx.MockTransport(answer))
    return sent


# --- the rules --------------------------------------------------------------------------------


def _kinds(facts: Facts) -> dict[str, Alert]:
    return {alert.kind: alert for alert in alerts.decide(facts)}


def test_nothing_to_say() -> None:
    assert alerts.decide(Facts()) == []
    quiet = Facts(
        login_failures=4,
        finished_last_hour=10,
        failed_last_hour=2,
        openrouter_balance=12.0,
        elevenlabs_used=8000,
        elevenlabs_limit=10000,
        disk_used=0.5,
    )
    assert alerts.decide(quiet) == []


def test_each_rule() -> None:
    found = _kinds(
        Facts(
            login_failures=6,
            login_ips=["203.0.113.9", "198.51.100.2"],
            new_flagged=[("d1", "Is AI art art?"), ("d2", None)],
            finished_last_hour=5,
            failed_last_hour=4,
            stuck_debates=1,
            stuck_media=2,
            openrouter_balance=0.5,
            elevenlabs_used=9950,
            elevenlabs_limit=10000,
            new_topups=[("u1", 10.0, "ann@example.com")],
            disk_used=0.9,
        )
    )
    assert set(found) == {
        "logins",
        "flagged",
        "errors",
        "stuck",
        "openrouter",
        "elevenlabs",
        "topup",
        "disk",
    }
    assert set(found) <= set(alert_events.KINDS)  # each one can be muted in the console
    assert "203.0.113.9" in found["logins"].detail and found["logins"].quiet == 3600
    assert found["errors"].severity == "critical"  # 4 of 5
    assert found["stuck"].detail.startswith("1 debate and 2 audio builds")
    assert found["openrouter"].severity == "critical" and "$0.50" in found["openrouter"].detail
    assert found["elevenlabs"].severity == "critical"  # under 2 %
    assert found["disk"].severity == "warning" and found["disk"].title == "Disk 90% full"
    assert found["flagged"].title == "2 debates flagged for moderation"
    assert "Untitled debate" in found["flagged"].detail
    assert found["topup"].title == "Top-up $10.00" and found["topup"].path == "/admin/users/u1"


def test_escalation_has_its_own_quiet_key() -> None:
    low = _kinds(Facts(openrouter_balance=3.0))["openrouter"]
    empty = _kinds(Facts(openrouter_balance=0.2))["openrouter"]
    assert (low.severity, empty.severity) == ("warning", "critical")
    assert low.quiet_key != empty.quiet_key


def test_error_spike_needs_a_share_and_a_count() -> None:
    assert "errors" not in _kinds(Facts(finished_last_hour=20, failed_last_hour=4))  # 20 %
    spike = _kinds(Facts(finished_last_hour=8, failed_last_hour=3))["errors"]
    assert spike.severity == "warning" and spike.title.startswith("3 of 8")


def test_lists_are_shortened() -> None:
    flagged: list[tuple[str, str | None]] = [(str(i), f"Topic {i}") for i in range(5)]
    alert = _kinds(Facts(new_flagged=flagged))["flagged"]
    assert alert.detail.endswith("and 2 more")
    topups = [("u1", 5.0, "a@b.co"), ("u2", 10.0, None)]
    many = _kinds(Facts(new_topups=topups))["topup"]
    assert many.title == "2 top-ups, $15.00" and many.path == "/admin/finance"
    assert "deleted account $10.00" in many.detail


def test_a_rejected_elevenlabs_key_wins_over_the_quota() -> None:
    alert = _kinds(Facts(elevenlabs_rejected="401", elevenlabs_used=0, elevenlabs_limit=1))
    assert alert["elevenlabs"].title == "ElevenLabs key rejected"


def test_sign_in_alerts() -> None:
    chrome = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/141.0 Safari/537.36"
    code = alerts.sign_in_alert("boss@example.com", "an authenticator code", "203.0.113.9", chrome)
    assert code.detail == "with an authenticator code · 203.0.113.9 · Chrome on macOS"
    assert (
        alerts.agent_label("Mozilla/5.0 (iPhone) AppleWebKit Version/18 Safari/605")
        == "Safari on iOS"
    )
    assert alerts.agent_label("curl/8.0") == "a browser" and alerts.agent_label(None) == ""
    recovery = alerts.sign_in_alert("boss@example.com", "a recovery code", None, None)
    assert code.severity == "info" and "203.0.113.9" in code.detail and code.quiet == 0
    assert recovery.severity == "warning" and recovery.detail == "with a recovery code"
    assert alerts.locked_alert("boss@example.com", "1.2.3.4").severity == "critical"


def test_alerts_raised_at_once_are_in_the_catalogue() -> None:
    raised = [
        alerts.sign_in_alert("a@b.co", "a passkey", None, None),
        alerts.locked_alert("a@b.co", None),
        alerts.trending_failed_alert("no answer"),
        alerts.signup_alert("u1", "a@b.co", "Ann", None, None, 0),
        alerts.debate_alert(DebateStart("d1", "Tabs?", "a@b.co", ["x/y"], 1, 0.0)),
    ]
    assert {alert.kind for alert in raised} <= set(alert_events.KINDS)
    assert len(set(alert_events.KINDS)) == len(alert_events.KINDS)


def test_sign_up_and_new_debate_alerts() -> None:
    firefox = "Mozilla/5.0 (Windows NT 10.0; rv:131.0) Gecko/20100101 Firefox/131.0"
    signup = alerts.signup_alert("u1", "ann@example.com", "Ann", "203.0.113.9", firefox, 1.5)
    assert signup.title == "New account: ann@example.com" and signup.path == "/admin/users/u1"
    assert signup.detail == "Ann · 203.0.113.9 · Firefox on Windows · $1.50 welcome credits"
    assert signup.hourly == alerts.SIGNUPS_PER_HOUR and signup.severity == "info"
    paid = alerts.debate_alert(
        DebateStart(
            "d1",
            "Tabs or spaces?",
            "ann@example.com",
            ["anthropic/claude-sonnet-5", "openrouter/free"],
            rounds=1,
            cost_usd=0.123,
            token="laptop",
            from_draft=True,
        )
    )
    assert paid.title == "New debate: Tabs or spaces?" and paid.path == "/admin/debates/d1"
    assert paid.detail == (
        "ann@example.com · claude-sonnet-5 vs Free Router · 1 round · about $0.12 · "
        "API token “laptop” · from a draft"
    )
    own = alerts.debate_alert(DebateStart("d2", "T", "a@b.co", ["x/y", "x/z"], 3, 0.5, True))
    free = alerts.debate_alert(DebateStart("d3", "T", "a@b.co", ["x/y:free"], 2, 0.0))
    assert own.detail.endswith("3 rounds · own OpenRouter key")
    assert free.detail.endswith("2 rounds · free models")


def test_changing_the_mutes_is_told() -> None:
    muted = alerts.mutes_changed_alert("boss@example.com", ["debate"], ["signin", "topup"])
    assert muted.detail == (
        "by boss@example.com; muted: Console sign-in, Top-ups; on again: New debate"
    )
    assert muted.severity == "warning"  # a security alert went quiet
    calm = alerts.mutes_changed_alert("boss@example.com", [], ["debate"])
    assert calm.severity == "info" and calm.kind not in alert_events.KINDS


# --- the message ------------------------------------------------------------------------------


def test_message_is_escaped_and_links_the_console(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ADMIN_HOST", "admin.example.com")
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    text = alerts.message(Alert("x", "<b>evil</b> & co", "a < b", "critical", "/admin/system#runs"))
    assert text.startswith("🔴 <b>&lt;b&gt;evil&lt;/b&gt; &amp; co</b>")
    assert "a &lt; b" in text
    assert '<a href="https://admin.example.com/admin/system#runs">' in text


def test_development_messages_say_so(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ADMIN_HOST", "")
    monkeypatch.setattr(settings, "SITE_URL", "http://localhost")
    text = alerts.message(Alert("x", "Hello", path="/admin"))
    assert text.startswith("[development] ") and 'href="http://localhost/admin"' in text


# --- sending ----------------------------------------------------------------------------------


def test_send_posts_html_to_the_chat(telegram: list[httpx.Request]) -> None:
    assert alerts.send_sync("hi") is None
    (request,) = telegram
    assert request.url.path == f"/bot{TOKEN}/sendMessage"
    body = json.loads(request.content)
    assert body == {
        "chat_id": "42",
        "text": "hi",
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }


def test_send_failures_never_show_the_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ALERT_TELEGRAM_BOT_TOKEN", None)
    assert alerts.send_sync("hi") == "Telegram is not configured"
    monkeypatch.setattr(settings, "ALERT_TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setattr(settings, "ALERT_TELEGRAM_CHAT_ID", "42")

    def refuse(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"ok": False, "description": "Bad Request: chat not found"})

    monkeypatch.setattr(alerts, "TRANSPORT", httpx.MockTransport(refuse))
    error = alerts.send_sync("hi")
    assert error == "Telegram answered 400: Bad Request: chat not found"

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot reach {request.url}")

    monkeypatch.setattr(alerts, "TRANSPORT", httpx.MockTransport(down))
    error = alerts.send_sync("hi")
    assert error == "Telegram unreachable (ConnectError)" and TOKEN not in error


async def test_async_delivery(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ALERT_TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setattr(settings, "ALERT_TELEGRAM_CHAT_ID", "42")
    monkeypatch.setattr(
        alerts, "ASYNC_TRANSPORT", httpx.MockTransport(lambda r: httpx.Response(200, json={}))
    )
    assert await alerts.send("hi") is None


def test_antispam_and_the_recent_list(telegram: list[httpx.Request]) -> None:
    redis: Any = FakeRedis()
    alert = Alert("disk", "Disk 90% full", quiet=3600)
    assert alerts.raise_sync(alert, redis)
    assert not alerts.raise_sync(alert, redis)  # quiet now
    assert len(telegram) == 1
    (entry,) = [json.loads(item) for item in redis.lists[alerts.RECENT_KEY]]
    assert entry["kind"] == "disk" and entry["sent"] and entry["error"] is None
    # Without a quiet period every alert goes out (sign-ins).
    signin = Alert("signin", "Console sign-in")
    assert alerts.raise_sync(signin, redis) and alerts.raise_sync(signin, redis)
    assert len(telegram) == 3


def test_unconfigured_alerts_are_still_listed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ALERT_TELEGRAM_BOT_TOKEN", None)
    redis: Any = FakeRedis()
    assert not alerts.raise_sync(Alert("topup", "Top-up $5.00"), redis)
    (entry,) = [json.loads(item) for item in redis.lists[alerts.RECENT_KEY]]
    assert not entry["sent"] and entry["error"] == "Telegram is not configured"


def test_muted_alerts_are_neither_sent_nor_listed(
    telegram: list[httpx.Request], levers: dict
) -> None:
    levers["muted_alerts"] = ["disk"]
    redis: Any = FakeRedis()
    assert not alerts.raise_sync(Alert("disk", "Disk 90% full", quiet=3600), redis)
    assert telegram == [] and redis.lists == {} and redis.data == {}  # no quiet key either
    assert alerts.raise_sync(Alert("topup", "Top-up $5.00"), redis)
    assert alerts.raise_sync(Alert("mutes", "Telegram alerts changed"), redis)  # never muted
    assert len(telegram) == 2


async def test_muted_alerts_from_the_api(levers: dict) -> None:
    levers["muted_alerts"] = ["signup"]
    # Muted before Redis or Telegram are touched (neither is set up here).
    assert not await alerts.raise_async(alerts.signup_alert("u", "a@b.co", "A", None, None, 0))


def test_frequent_alerts_have_an_hourly_cap(telegram: list[httpx.Request]) -> None:
    redis: Any = FakeRedis()
    alert = Alert("signup", "New account", "Ann", hourly=3)
    sent = [alerts.raise_sync(alert, redis) for _ in range(5)]
    assert sent == [True, True, True, False, False] and len(telegram) == 3
    last = json.loads(redis.lists[alerts.RECENT_KEY][0])
    assert last["detail"].startswith("Ann · 3 in an hour: the next ones stay quiet")
    assert len(redis.lists[alerts.RECENT_KEY]) == 3


def test_recent_list_is_capped(telegram: list[httpx.Request]) -> None:
    redis: Any = FakeRedis()
    for i in range(alerts.RECENT_KEPT + 5):
        alerts.raise_sync(Alert("signin", f"#{i}"), redis)
    assert len(redis.lists[alerts.RECENT_KEY]) == alerts.RECENT_KEPT


# --- "seen before" ----------------------------------------------------------------------------


def test_new_ids_skip_the_first_check() -> None:
    redis: Any = FakeRedis()
    assert alerts.new_ids(redis, "k", ["a", "b"]) == set()  # first look: nothing is new
    assert alerts.new_ids(redis, "k", ["a", "b", "c"]) == {"c"}
    assert alerts.new_ids(redis, "k", ["c"]) == set()
    assert alerts.new_ids(redis, "k", ["c", "a"]) == {"a"}  # gone and back: new again


def test_stuck_runs_need_two_checks() -> None:
    redis: Any = FakeRedis()
    assert alerts.seen_twice(redis, "s", ["d1", "d2"]) == set()
    assert alerts.seen_twice(redis, "s", ["d2", "d3"]) == {"d2"}
    assert alerts.seen_twice(redis, "s", []) == set()
