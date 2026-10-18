"""Admin overview: periods, buckets, filled series and the "needs attention" list (pure)."""

from datetime import UTC, datetime, timedelta

import pytest

from app.admin.access import can
from app.api.admin.routes_overview import _cache_key
from app.services.admin import stats
from app.services.admin.stats import Signals

NOW = datetime(2026, 10, 18, 17, 30, tzinfo=UTC)  # a Sunday


def test_windows_compare_with_the_period_before() -> None:
    week = stats.window_for("7d", NOW)
    assert (week.start, week.previous_start, week.bucket) == (
        NOW - timedelta(days=7),
        NOW - timedelta(days=14),
        "day",
    )
    assert stats.window_for("24h", NOW).bucket == "hour"
    everything = stats.window_for("all", NOW, first=NOW - timedelta(days=40, hours=5))
    assert everything.previous_start is None and everything.bucket == "day"
    assert everything.start == datetime(2026, 9, 8, tzinfo=UTC)  # the first account's day
    assert stats.window_for("all", NOW, first=NOW - timedelta(days=400)).bucket == "week"
    assert stats.window_for("all", NOW, first=None).start == datetime(2026, 10, 18, tzinfo=UTC)
    with pytest.raises(KeyError):
        stats.window_for("1y", NOW)


def test_truncate_to_hour_day_and_iso_week() -> None:
    assert stats.truncate(NOW, "hour") == datetime(2026, 10, 18, 17, tzinfo=UTC)
    assert stats.truncate(NOW, "day") == datetime(2026, 10, 18, tzinfo=UTC)
    assert stats.truncate(NOW, "week") == datetime(2026, 10, 12, tzinfo=UTC)  # Monday


def test_series_have_every_bucket() -> None:
    window = stats.window_for("7d", NOW)
    starts = stats.bucket_starts(window)
    assert len(starts) == 8 and starts[0] == datetime(2026, 10, 11, tzinfo=UTC)
    points = stats.fill_series(window, {"signups": {starts[2]: 3.0}, "error": {}})
    assert [p["signups"] for p in points] == [0, 0, 3.0, 0, 0, 0, 0, 0]
    assert all(p["error"] == 0 for p in points) and points[-1]["t"] == starts[-1]
    assert len(stats.bucket_starts(stats.window_for("24h", NOW))) == 25


def test_error_rate() -> None:
    assert stats.error_rate(1, 4) == 0.25
    assert stats.error_rate(0, 0) is None


def _keys(signals: Signals) -> list[tuple[str, str]]:
    return [(item["key"], item["severity"]) for item in stats.attention_items(signals)]


def test_a_quiet_day_needs_nothing() -> None:
    assert (
        _keys(Signals(openrouter_balance=40, trending_age_hours=3, trending_every_hours=24)) == []
    )


def test_attention_is_ordered_by_severity() -> None:
    signals = Signals(
        flagged=2,
        stuck_debates=1,
        openrouter_balance=0.5,
        negative_balances=1,
        negative_total=-0.2,
        login_failures_24h=1,
        recovery_codes_left=2,
    )
    keys = _keys(signals)
    assert keys[:2] == [("stuck", "critical"), ("openrouter", "critical")]
    assert ("moderation", "warning") in keys and ("balances", "warning") in keys
    assert keys[-2:] == [("logins", "info"), ("recovery", "info")]


@pytest.mark.parametrize(
    ("signals", "expected"),
    [
        (Signals(openrouter_balance=3.0), [("openrouter", "warning")]),
        (Signals(openrouter_error="Could not reach OpenRouter"), [("openrouter", "warning")]),
        (Signals(elevenlabs_ok=False, elevenlabs_reason="401"), [("elevenlabs", "critical")]),
        (
            Signals(elevenlabs_ok=True, elevenlabs_used=95_000, elevenlabs_limit=100_000),
            [("elevenlabs", "warning")],
        ),
        (
            Signals(elevenlabs_ok=True, elevenlabs_used=99_000, elevenlabs_limit=100_000),
            [("elevenlabs", "critical")],
        ),
        (Signals(elevenlabs_ok=True, elevenlabs_used=10, elevenlabs_limit=100_000), []),
        (Signals(check_backups=True, backup_age_hours=30), [("backup", "critical")]),
        (Signals(check_backups=True, backup_age_hours=None), [("backup", "critical")]),
        (Signals(check_backups=True, backup_age_hours=5), []),
        (Signals(check_backups=False, backup_age_hours=None), []),  # development
        (Signals(trending_every_hours=24, trending_age_hours=31), [("trending", "warning")]),
        (Signals(trending_every_hours=24, trending_age_hours=None), [("trending", "warning")]),
        (Signals(trending_every_hours=0, trending_age_hours=None), []),  # refresh off
        (Signals(login_failures_24h=5), [("logins", "warning")]),
        (Signals(stuck_media=2), [("stuck", "critical")]),
        (Signals(recovery_codes_left=4), []),
    ],
)
def test_attention_thresholds(signals: Signals, expected: list[tuple[str, str]]) -> None:
    assert _keys(signals) == expected


def test_items_link_somewhere_useful() -> None:
    items = stats.attention_items(Signals(flagged=1, failed_24h=1))
    assert {i["key"]: i["href"] for i in items} == {
        "moderation": "/api/admin/db/debate/list?moderation_status=flagged",
        "failed": "/api/admin/db/debate/list?search=error",
    }


def test_money_is_cached_apart_from_the_rest() -> None:
    assert _cache_key("7d", True) != _cache_key("7d", False)
    assert can("admin", "money") and not can("moderator", "money")


def test_titles_count_in_words() -> None:
    one = {
        i["key"]: i
        for i in stats.attention_items(
            Signals(flagged=1, negative_balances=1, negative_total=-0.0002)
        )
    }
    assert one["moderation"]["title"] == "1 debate waits for moderation"
    assert one["balances"]["title"] == "1 account below zero"
    assert one["balances"]["detail"].startswith("$0.0002 in total")
    many = {i["key"]: i for i in stats.attention_items(Signals(flagged=3, failed_24h=2))}
    assert many["moderation"]["title"] == "3 debates wait for moderation"
    assert many["failed"]["title"] == "2 debates failed in 24 h"
