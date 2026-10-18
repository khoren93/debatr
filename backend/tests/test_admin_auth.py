"""The sqladmin login: rate limit, credential checks, the admin session deadline, the shared
cookie options and the allowlisted user form. Pure: the rate limiter is replaced."""

import time
from typing import Any
from urllib.parse import urlencode

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.admin import auth as admin_auth
from app.admin.auth import AdminAuth, credentials_match
from app.admin.views import DebateAdmin, ParticipantAdmin, TurnAdmin, UserAdmin
from app.core import auth as core_auth
from app.core.auth import (
    ADMIN_SESSION_KEY,
    ADMIN_SESSION_SECONDS,
    ADMIN_UNTIL_KEY,
    SESSION_USER_KEY,
    admin_login_session,
    admin_logout_session,
    is_admin_session,
    session_cookie_options,
)
from app.core.config import settings

NOW = 1_800_000_000.0


def _request(session: dict[str, Any], form: dict[str, str] | None = None) -> Request:
    body = urlencode(form or {}).encode()
    scope: dict[str, Any] = {
        "type": "http",
        "method": "POST",
        "path": "/api/admin/login",
        "query_string": b"",
        "headers": [(b"content-type", b"application/x-www-form-urlencoded")],
        "client": ("203.0.113.7", 50000),
        "session": session,
    }

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(scope, receive)


@pytest.fixture
def limiter(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Replace the Redis rate limiter; returns the IPs it was asked about."""
    calls: list[str] = []

    async def fake_limit(request: Request) -> None:
        calls.append(request.client.host if request.client else "")

    monkeypatch.setattr(admin_auth, "enforce_admin_login_limit", fake_limit)
    return calls


@pytest.fixture
def credentials(monkeypatch: pytest.MonkeyPatch) -> tuple[str, str]:
    monkeypatch.setattr(settings, "ADMIN_USER", "root")
    monkeypatch.setattr(settings, "ADMIN_PASSWORD", "пароль-correct-horse")
    return "root", "пароль-correct-horse"


def test_credentials_match_handles_non_ascii() -> None:
    assert credentials_match("пароль", "пароль")
    assert not credentials_match("пароль", "password")
    assert not credentials_match("", "password")


async def test_login_checks_the_limit_and_opens_a_session(
    limiter: list[str], credentials: tuple[str, str]
) -> None:
    session: dict[str, Any] = {SESSION_USER_KEY: "user-1"}
    user, password = credentials
    ok = await AdminAuth("x").login(_request(session, {"username": user, "password": password}))
    assert ok is True
    assert limiter == ["203.0.113.7"]
    assert session[ADMIN_SESSION_KEY] == "authenticated"
    assert isinstance(session[ADMIN_UNTIL_KEY], int)
    assert session[SESSION_USER_KEY] == "user-1"


@pytest.mark.parametrize(
    "form",
    [
        {"username": "root", "password": "wrong"},
        {"username": "admin", "password": "пароль-correct-horse"},
        {"username": "пользователь", "password": "пароль"},
        {},
    ],
)
async def test_wrong_credentials_are_refused(
    limiter: list[str], credentials: tuple[str, str], form: dict[str, str]
) -> None:
    session: dict[str, Any] = {}
    assert await AdminAuth("x").login(_request(session, form)) is False
    assert ADMIN_SESSION_KEY not in session
    assert len(limiter) == 1


async def test_login_stops_at_the_limit(
    monkeypatch: pytest.MonkeyPatch, credentials: tuple[str, str]
) -> None:
    async def blocked(request: Request) -> None:
        raise HTTPException(status_code=429, detail="Too many sign-in attempts.")

    monkeypatch.setattr(admin_auth, "enforce_admin_login_limit", blocked)
    session: dict[str, Any] = {}
    user, password = credentials
    with pytest.raises(HTTPException) as caught:
        await AdminAuth("x").login(_request(session, {"username": user, "password": password}))
    assert caught.value.status_code == 429
    assert session == {}


def test_admin_session_has_a_deadline() -> None:
    session: dict[str, Any] = {}
    request = _request(session)
    assert not is_admin_session(request, now=NOW)

    admin_login_session(request, now=NOW)
    assert session[ADMIN_UNTIL_KEY] == int(NOW + ADMIN_SESSION_SECONDS)
    assert is_admin_session(request, now=NOW + ADMIN_SESSION_SECONDS - 1)
    assert not is_admin_session(request, now=NOW + ADMIN_SESSION_SECONDS)


def test_login_from_before_the_deadline_counts_as_ended() -> None:
    assert not is_admin_session(_request({ADMIN_SESSION_KEY: "authenticated"}), now=NOW)
    session = {ADMIN_SESSION_KEY: "authenticated", ADMIN_UNTIL_KEY: "9999999999"}
    assert not is_admin_session(_request(session), now=NOW)


async def test_logout_and_ended_sessions_keep_the_user_login() -> None:
    session: dict[str, Any] = {SESSION_USER_KEY: "user-1"}
    request = _request(session)
    admin_login_session(request, now=time.time() - ADMIN_SESSION_SECONDS - 1)

    assert await AdminAuth("x").authenticate(request) is False
    assert session == {SESSION_USER_KEY: "user-1"}

    admin_login_session(request)
    assert await AdminAuth("x").authenticate(request) is True
    assert await AdminAuth("x").logout(request) is True
    assert session == {SESSION_USER_KEY: "user-1"}

    admin_logout_session(request)  # no admin keys left: nothing to do
    assert session == {SESSION_USER_KEY: "user-1"}


def test_session_cookie_is_strict_and_secure_in_production(monkeypatch: pytest.MonkeyPatch):
    options = session_cookie_options()
    assert options["same_site"] == "strict"
    assert options["max_age"] == settings.SESSION_MAX_AGE
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    assert core_auth.session_cookie_options()["https_only"] is True
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    assert core_auth.session_cookie_options()["https_only"] is False


def test_sqladmin_middleware_uses_the_same_cookie_options() -> None:
    (middleware,) = admin_auth.authentication_backend.middlewares
    assert middleware.kwargs["same_site"] == "strict"
    assert middleware.kwargs["max_age"] == settings.SESSION_MAX_AGE


def test_user_admin_never_shows_or_edits_secrets_or_the_balance() -> None:
    def names(columns: Any) -> set[str]:
        return {column.key for column in columns}

    secrets = {"password_hash", "openrouter_key_enc"}
    assert not UserAdmin.can_delete
    assert names(UserAdmin.form_columns) == {"display_name", "is_active"}
    assert not names(UserAdmin.column_details_list) & secrets
    assert "credits_usd" not in names(DebateAdmin.form_columns)
    assert not TurnAdmin.can_edit
    assert not ParticipantAdmin.can_edit
