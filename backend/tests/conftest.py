import os

# Must be set before `app.core.config` is imported anywhere.
os.environ.setdefault("OPENROUTER_API_KEY", "test-key")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
# The developer's .env may switch the console's second factor off; the tests expect it on (the
# ones about ADMIN_SKIP_2FA patch the setting themselves).
os.environ["ADMIN_SKIP_2FA"] = "false"


import pytest


@pytest.fixture(autouse=True)
def usage_rows(monkeypatch: pytest.MonkeyPatch) -> list:
    """provider_usage rows booked by the code under test, kept in memory (tests stay pure)."""
    from app.services import usage

    rows: list = []
    monkeypatch.setattr(usage, "_write", rows.append)
    return rows


@pytest.fixture(autouse=True)
def quiet_activity(monkeypatch: pytest.MonkeyPatch) -> list:
    """Users whose activity get_current_user notes (tests of app.services.activity call the
    real function directly)."""
    from app.core import auth

    seen: list = []

    async def note(user: object) -> None:
        seen.append(user)

    monkeypatch.setattr(auth, "note_activity", note)
    return seen


@pytest.fixture(autouse=True)
def levers(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Rows of `runtime_settings` as the code under test sees them (empty: every lever at its
    env default). Tests put values in the returned dict."""
    from app.services import runtime_settings

    stored: dict = {}

    async def read() -> dict:
        return dict(stored)

    monkeypatch.setattr(runtime_settings, "_stored", read)
    monkeypatch.setattr(runtime_settings, "_stored_sync", lambda: dict(stored))
    monkeypatch.setattr(runtime_settings, "CACHE_SECONDS", 0.0)
    runtime_settings.invalidate()
    return stored


@pytest.fixture(autouse=True)
def raised_alerts(monkeypatch: pytest.MonkeyPatch) -> list:
    """Alerts the API would send in the background (tests of app.services.alerts call the real
    functions with fakes)."""
    from app.services import alerts

    raised: list = []
    monkeypatch.setattr(alerts, "notify_soon", raised.append)
    return raised
