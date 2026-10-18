import os

# Must be set before `app.core.config` is imported anywhere.
os.environ.setdefault("OPENROUTER_API_KEY", "test-key")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")


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
