"""Admin console: second factor, sessions, sign-in flow, access checks and the gate.

Pure: Redis and the database are small in-memory fakes, the rate limiters are switched off.
"""

import builtins
import time
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import HTTPException
from starlette.applications import Starlette
from starlette.datastructures import Headers
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response
from starlette.routing import Route
from starlette.types import Message

from app.admin import access
from app.admin import auth as sqladmin_auth
from app.admin.access import (
    AdminContext,
    account_allows_console,
    can,
    csrf_ok,
    require_sudo,
    resolve_admin,
    session_cookie_name,
    ticket_cookie_name,
)
from app.admin.gate import AdminGate, gate_decision, hostname
from app.admin.views import ParticipantAdmin, TurnAdmin, UserAdmin
from app.api.admin import routes_auth
from app.api.serializers import can_manage, can_view
from app.core.config import settings
from app.core.redis import admin_enroll_key, admin_totp_step_key
from app.core.security import decrypt_totp_secret, encrypt_totp_secret, hash_password
from app.manage import build_parser
from app.models.models import AdminAuditLog, Debate, User
from app.schemas import admin as admin_schemas
from app.schemas.admin import (
    AdminCodeRequest,
    AdminLoginRequest,
    EnrollConfirmRequest,
    EnrollStartRequest,
)
from app.services.admin import sessions, totp
from app.services.admin.audit import json_safe, scrub
from app.services.admin.sessions import AdminSession

PASSWORD = "correct horse battery"
PASSWORD_HASH = hash_password(PASSWORD)


# --- fakes ------------------------------------------------------------------------------------


class FakeRedis:
    """The async Redis calls the console uses (decoded strings, no expiry)."""

    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.sets: dict[str, set[str]] = {}

    async def get(self, key: str) -> str | None:
        return self.data.get(key)

    async def set(self, key: str, value: Any, ex: int | None = None, nx: bool = False) -> bool:
        if nx and key in self.data:
            return False
        self.data[key] = str(value)
        return True

    async def delete(self, *keys: str) -> int:
        gone = 0
        for key in keys:
            gone += (self.data.pop(key, None) is not None) + (self.sets.pop(key, None) is not None)
        return gone

    async def sadd(self, key: str, *values: str) -> int:
        self.sets.setdefault(key, set()).update(values)
        return len(values)

    async def srem(self, key: str, *values: str) -> int:
        for value in values:
            self.sets.get(key, set()).discard(value)
        return len(values)

    async def smembers(self, key: str) -> builtins.set[str]:
        return set(self.sets.get(key, set()))

    async def expire(self, key: str, seconds: int, nx: bool = False) -> bool:
        return True

    async def incr(self, key: str) -> int:
        value = int(self.data.get(key, "0")) + 1
        self.data[key] = str(value)
        return value


class FakeDB:
    def __init__(self, *users: User) -> None:
        self.users = {user.id: user for user in users}
        self.lookup: User | None = None  # what `scalar(select(User)…)` returns
        self.added: list[Any] = []

    async def get(self, model: type, key: Any) -> Any:
        return self.users.get(key) if model is User else None

    async def scalar(self, statement: Any) -> Any:
        return self.lookup

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        return None

    def actions(self) -> list[tuple[str, bool]]:
        return [(row.action, row.ok) for row in self.added if isinstance(row, AdminAuditLog)]


def _user(**fields: Any) -> User:
    defaults: dict[str, Any] = {
        "id": uuid.uuid4(),
        "email": "boss@example.com",
        "display_name": "Boss",
        "password_hash": PASSWORD_HASH,
        "is_active": True,
        "admin_role": "admin",
        "totp_secret_enc": None,
        "totp_enabled_at": None,
        "recovery_codes_json": [],
        "session_epoch": 0,
    }
    return User(**{**defaults, **fields})


def _enrolled(secret: str, **fields: Any) -> User:
    enrolled = {
        "totp_secret_enc": encrypt_totp_secret(secret),
        "totp_enabled_at": datetime.now(UTC),
    }
    return _user(**{**enrolled, **fields})


def _request(
    method: str = "POST",
    cookies: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
    path: str = "/api/admin/auth/login",
) -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    if cookies:
        raw.append((b"cookie", "; ".join(f"{k}={v}" for k, v in cookies.items()).encode()))
    raw.append((b"user-agent", b"pytest"))
    scope: dict[str, Any] = {
        "type": "http",
        "method": method,
        "path": path,
        "query_string": b"",
        "headers": raw,
        "client": ("203.0.113.9", 40000),
        "scheme": "http",
        "server": ("testserver", 80),
    }
    return Request(scope)


def _cookie(response: Response, name: str) -> str | None:
    for header in response.headers.getlist("set-cookie"):
        key, _, rest = header.partition("=")
        if key == name:
            value = rest.split(";", 1)[0]
            return value.strip('"') or None
    return None


@pytest.fixture
def redis(monkeypatch: pytest.MonkeyPatch) -> FakeRedis:
    fake = FakeRedis()
    monkeypatch.setattr(routes_auth, "get_async_redis", lambda: fake)
    monkeypatch.setattr(access, "get_async_redis", lambda: fake)

    async def no_limit(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(routes_auth, "enforce_admin_login_limit", no_limit)
    monkeypatch.setattr(routes_auth, "enforce_limit", no_limit)
    return fake


# --- TOTP, recovery and enrollment codes ------------------------------------------------------


def test_totp_accepts_the_window_once() -> None:
    secret = totp.new_secret()
    now = 1_800_000_015.0
    step = int(now // totp.STEP_SECONDS)
    code = totp.code_now(secret, now)
    assert totp.matching_step(secret, code, now=now, after_step=None) == step
    assert totp.matching_step(secret, f" {code[:3]} {code[3:]} ", now=now, after_step=None) == step
    # A clock 30 s off still works, 90 s off does not.
    assert totp.matching_step(secret, code, now=now + 30, after_step=None) == step
    assert totp.matching_step(secret, code, now=now + 90, after_step=None) is None
    # Once accepted, the same step is refused (replay).
    assert totp.matching_step(secret, code, now=now, after_step=step) is None
    assert totp.matching_step(secret, "12345", now=now, after_step=None) is None
    assert totp.matching_step(secret, "", now=now, after_step=None) is None


def test_recovery_codes_work_once_and_ignore_case_and_dashes() -> None:
    plain, hashes = totp.new_recovery_codes()
    assert len(plain) == len(set(plain)) == totp.RECOVERY_CODE_COUNT
    assert all(len(code) == 11 and code[5] == "-" for code in plain)
    left = totp.use_recovery_code(hashes, plain[3].lower().replace("-", ""))
    assert left is not None and len(left) == totp.RECOVERY_CODE_COUNT - 1
    assert totp.use_recovery_code(left, plain[3]) is None
    assert totp.use_recovery_code(hashes, "") is None
    assert totp.use_recovery_code(hashes, "NOPE-NOPE") is None


def test_enrollment_code_and_qr() -> None:
    code = totp.new_enrollment_code()
    assert len(code) == 19 and code.count("-") == 3
    assert not set(totp.normalize_code(code)) - set(totp.CODE_ALPHABET)
    uri = totp.provisioning_uri("JBSWY3DPEHPK3PXP", "boss@example.com")
    assert uri.startswith("otpauth://totp/") and "issuer=Debatr" in uri
    assert totp.qr_data_uri(uri).startswith("data:image/svg+xml")


def test_totp_secrets_have_their_own_key() -> None:
    sealed = encrypt_totp_secret("JBSWY3DPEHPK3PXP")
    assert decrypt_totp_secret(sealed) == "JBSWY3DPEHPK3PXP"
    from app.core.security import decrypt_secret

    assert decrypt_secret(sealed) is None  # not readable with the OpenRouter-key key


# --- sessions ---------------------------------------------------------------------------------


async def test_session_lifetime_idle_and_absolute() -> None:
    redis: Any = FakeRedis()
    now = 1_000_000.0
    token, hashed, session = await sessions.create_session(
        redis,
        user_id="u1",
        epoch=0,
        ip="1.2.3.4",
        user_agent="ua",
        now=now,
    )
    assert hashed == sessions.token_hash(token) and token not in str(redis.data)
    assert await sessions.load_session(redis, hashed, now + 60) is not None
    # Idle for longer than IDLE_SECONDS: gone.
    assert await sessions.load_session(redis, hashed, now + sessions.IDLE_SECONDS + 1) is None

    _, hashed, session = await sessions.create_session(
        redis,
        user_id="u1",
        epoch=0,
        ip="",
        user_agent="",
        now=now,
    )
    session.last_seen_at = now + sessions.ABSOLUTE_SECONDS - 10  # active all along
    assert session.ttl(now + sessions.ABSOLUTE_SECONDS) == 0  # but the absolute limit holds
    listed = await sessions.list_sessions(redis, "u1", now)
    assert [h for h, _ in listed] == [hashed]
    assert await sessions.revoke_all(redis, "u1") == 1
    assert await sessions.load_session(redis, hashed, now) is None


def test_account_checks() -> None:
    user = _enrolled("JBSWY3DPEHPK3PXP")
    session = AdminSession(
        user_id=str(user.id),
        csrf="c",
        created_at=0,
        last_seen_at=0,
        ip="",
        user_agent="",
        epoch=0,
    )
    assert account_allows_console(user, session)
    for change in (
        {"is_active": False},
        {"admin_role": None},
        {"admin_role": "owner"},
        {"totp_enabled_at": None},
        {"session_epoch": 1},
    ):
        changed = _enrolled("JBSWY3DPEHPK3PXP", id=user.id, **change)
        assert not account_allows_console(changed, session), change
    assert not account_allows_console(None, session)
    assert not account_allows_console(_enrolled("JBSWY3DPEHPK3PXP"), session)  # other user


def test_permissions() -> None:
    assert can("admin", "money") and can("admin", "database")
    assert can("moderator", "moderation") and not can("moderator", "money")
    assert not can("moderator", "database") and not can(None, "console")


def test_csrf_needed_for_unsafe_methods_only() -> None:
    session = AdminSession(
        user_id="u", csrf="secret", created_at=0, last_seen_at=0, ip="", user_agent="", epoch=0
    )
    assert csrf_ok(_request("GET"), session)
    assert not csrf_ok(_request("POST"), session)
    assert not csrf_ok(_request("POST", headers={"X-CSRF-Token": "wrong"}), session)
    assert csrf_ok(_request("DELETE", headers={"X-CSRF-Token": "secret"}), session)


def test_cookie_names_take_the_host_prefix_over_https(monkeypatch: pytest.MonkeyPatch):
    assert session_cookie_name(_request()) == "debatr_admin"
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    assert session_cookie_name(_request()) == "__Host-debatr_admin"
    assert ticket_cookie_name(_request()) == "__Host-debatr_admin_signin"


# --- the sign-in flow -------------------------------------------------------------------------


async def _sign_in_ticket(db: FakeDB, user: User) -> tuple[str, str]:
    db.lookup = user
    response = Response()
    out = await routes_auth.login(
        AdminLoginRequest(email=user.email, password=PASSWORD),
        _request(),
        response,
        db,  # type: ignore[arg-type]
    )
    ticket = _cookie(response, "debatr_admin_signin")
    assert ticket
    return out.next, ticket


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({}, "wrong password"),
        ({"admin_role": None}, "not an admin"),
        ({"is_active": False}, "account disabled"),
    ],
)
async def test_login_refusals_look_the_same(
    redis: FakeRedis, change: dict[str, Any], reason: str
) -> None:
    user = _user(**change)
    db = FakeDB(user)
    db.lookup = user
    password = "wrong" if not change else PASSWORD
    with pytest.raises(HTTPException) as caught:
        await routes_auth.login(
            AdminLoginRequest(email=user.email, password=password),
            _request(),
            Response(),
            db,  # type: ignore[arg-type]
        )
    assert (caught.value.status_code, caught.value.detail) == (401, routes_auth.WRONG_LOGIN)
    (row,) = [r for r in db.added if isinstance(r, AdminAuditLog)]
    assert (row.action, row.ok, row.reason) == ("auth.login_failed", False, reason)


async def test_unknown_email_is_refused_like_a_wrong_password(redis: FakeRedis) -> None:
    db = FakeDB()
    with pytest.raises(HTTPException) as caught:
        await routes_auth.login(
            AdminLoginRequest(email="nobody@example.com", password=PASSWORD),
            _request(),
            Response(),
            db,  # type: ignore[arg-type]
        )
    assert caught.value.detail == routes_auth.WRONG_LOGIN
    assert db.actions() == [("auth.login_failed", False)]


async def test_first_sign_in_enrolls_with_the_server_code(redis: FakeRedis) -> None:
    user = _user()
    db = FakeDB(user)
    next_step, ticket = await _sign_in_ticket(db, user)
    assert next_step == "enroll"
    cookies = {"debatr_admin_signin": ticket}

    with pytest.raises(HTTPException) as caught:  # no enrollment code issued yet
        await routes_auth.enroll_start(
            EnrollStartRequest(enrollment_code="AAAA-BBBB-CCCC-DDDD"),
            _request(cookies=cookies),
            db,  # type: ignore[arg-type]
        )
    assert caught.value.status_code == 400

    code = totp.new_enrollment_code()
    redis.data[admin_enroll_key(str(user.id))] = totp.code_hash(code)
    started = await routes_auth.enroll_start(
        EnrollStartRequest(enrollment_code=code.lower()),
        _request(cookies=cookies),
        db,  # type: ignore[arg-type]
    )
    assert started.qr.startswith("data:image/svg+xml")

    response = Response()
    out = await routes_auth.enroll_confirm(
        EnrollConfirmRequest(code=totp.code_now(started.secret, time.time())),
        _request(cookies=cookies),
        response,
        db,  # type: ignore[arg-type]
    )
    assert out.recovery_codes is not None and len(out.recovery_codes) == 10
    assert user.totp_enabled_at is not None and len(user.recovery_codes_json) == 10
    assert decrypt_totp_secret(user.totp_secret_enc or "") == started.secret
    assert admin_enroll_key(str(user.id)) not in redis.data  # the code works once
    assert _cookie(response, "debatr_admin")
    assert ("auth.enrolled", True) in db.actions() and ("auth.signed_in", True) in db.actions()


async def test_sign_in_with_a_code_then_sudo(redis: FakeRedis) -> None:
    secret = totp.new_secret()
    user = _enrolled(secret)
    db = FakeDB(user)
    next_step, ticket = await _sign_in_ticket(db, user)
    assert next_step == "totp"
    response = Response()
    code = totp.code_now(secret, time.time())
    out = await routes_auth.verify_code(
        AdminCodeRequest(code=code),
        _request(cookies={"debatr_admin_signin": ticket}),
        response,
        db,  # type: ignore[arg-type]
    )
    token = _cookie(response, "debatr_admin")
    assert token and out.me.user.email == user.email and out.recovery_codes is None

    # The session resolves for this account; the same code cannot sign in again.
    ctx = await resolve_admin(_request("GET", cookies={"debatr_admin": token}), db)  # type: ignore[arg-type]
    assert isinstance(ctx, AdminContext) and ctx.user is user
    _, ticket = await _sign_in_ticket(db, user)
    with pytest.raises(HTTPException) as caught:
        await routes_auth.verify_code(
            AdminCodeRequest(code=code),
            _request(cookies={"debatr_admin_signin": ticket}),
            Response(),
            db,  # type: ignore[arg-type]
        )
    assert caught.value.status_code == 400

    # Dangerous actions need a fresh code.
    with pytest.raises(HTTPException) as caught:
        await require_sudo(ctx)
    assert caught.value.headers == {access.SUDO_HEADER: "required"}
    del redis.data[admin_totp_step_key(str(user.id))]  # as if the next code came up
    await routes_auth.confirm_sudo(AdminCodeRequest(code=code), _request(), ctx, db)  # type: ignore[arg-type]
    assert await require_sudo(ctx) is ctx
    fresh = await routes_auth.regenerate_recovery_codes(_request(), ctx, db)  # type: ignore[arg-type]
    assert len(fresh.recovery_codes) == 10


async def test_skip_2fa_signs_in_with_the_password_alone(
    redis: FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "ADMIN_SKIP_2FA", True)
    user = _user()  # never enrolled
    db = FakeDB(user)
    db.lookup = user
    response = Response()
    out = await routes_auth.login(
        AdminLoginRequest(email=user.email, password=PASSWORD),
        _request(),
        response,
        db,  # type: ignore[arg-type]
    )
    token = _cookie(response, "debatr_admin")
    assert out.next == "done" and out.me is not None and not out.me.two_factor and token
    ctx = await resolve_admin(_request("GET", cookies={"debatr_admin": token}), db)  # type: ignore[arg-type]
    assert isinstance(ctx, AdminContext) and await require_sudo(ctx) is ctx
    (row,) = [r for r in db.added if isinstance(r, AdminAuditLog)]
    assert row.action == "auth.signed_in" and row.after_json is not None


async def test_skip_2fa_is_ignored_in_production(
    redis: FakeRedis, production: pytest.MonkeyPatch
) -> None:
    production.setattr(settings, "ADMIN_SKIP_2FA", True)
    assert not settings.admin_skip_2fa
    user = _user()
    db = FakeDB(user)
    db.lookup = user
    out = await routes_auth.login(
        AdminLoginRequest(email=user.email, password=PASSWORD),
        _request(),
        Response(),
        db,  # type: ignore[arg-type]
    )
    assert out.next == "enroll" and out.me is None
    session = AdminSession(
        user_id=str(user.id), csrf="c", created_at=0, last_seen_at=0, ip="", user_agent="", epoch=0
    )
    assert not account_allows_console(user, session)


async def test_recovery_code_signs_in_once(redis: FakeRedis) -> None:
    plain, hashes = totp.new_recovery_codes()
    user = _enrolled(totp.new_secret(), recovery_codes_json=hashes)
    db = FakeDB(user)
    _, ticket = await _sign_in_ticket(db, user)
    await routes_auth.verify_code(
        AdminCodeRequest(recovery_code=plain[0]),
        _request(cookies={"debatr_admin_signin": ticket}),
        Response(),
        db,  # type: ignore[arg-type]
    )
    assert len(user.recovery_codes_json) == 9
    assert ("auth.recovery_code_used", True) in db.actions()


async def test_wrong_codes_lock_the_second_factor(redis: FakeRedis) -> None:
    secret = totp.new_secret()
    user = _enrolled(secret)
    db = FakeDB(user)
    statuses: list[int] = []
    for _ in range(sessions.MAX_CODE_FAILURES):
        _, ticket = await _sign_in_ticket(db, user)
        with pytest.raises(HTTPException) as caught:
            await routes_auth.verify_code(
                AdminCodeRequest(code="000000"),
                _request(cookies={"debatr_admin_signin": ticket}),
                Response(),
                db,  # type: ignore[arg-type]
            )
        statuses.append(caught.value.status_code)
    assert statuses == [400] * (sessions.MAX_CODE_FAILURES - 1) + [429]
    # Locked: even the right code is refused now.
    _, ticket = await _sign_in_ticket(db, user)
    with pytest.raises(HTTPException) as caught:
        await routes_auth.verify_code(
            AdminCodeRequest(code=totp.code_now(secret, time.time())),
            _request(cookies={"debatr_admin_signin": ticket}),
            Response(),
            db,  # type: ignore[arg-type]
        )
    assert caught.value.status_code == 429
    assert ("auth.locked", False) in db.actions()


async def test_a_ticket_dies_after_too_many_wrong_codes(redis: FakeRedis) -> None:
    user = _enrolled(totp.new_secret())
    db = FakeDB(user)
    _, ticket = await _sign_in_ticket(db, user)
    cookies = {"debatr_admin_signin": ticket}
    for _ in range(sessions.MAX_TICKET_FAILURES - 1):
        with pytest.raises(HTTPException):
            await routes_auth.verify_code(
                AdminCodeRequest(code="000000"),
                _request(cookies=cookies),
                Response(),
                db,  # type: ignore[arg-type]
            )
        await sessions.clear_code_failures(redis, str(user.id))  # type: ignore[arg-type]
    with pytest.raises(HTTPException):
        await routes_auth.verify_code(
            AdminCodeRequest(code="000000"),
            _request(cookies=cookies),
            Response(),
            db,  # type: ignore[arg-type]
        )
    with pytest.raises(HTTPException) as caught:
        await routes_auth.verify_code(
            AdminCodeRequest(code="000000"),
            _request(cookies=cookies),
            Response(),
            db,  # type: ignore[arg-type]
        )
    assert (caught.value.status_code, caught.value.detail) == (401, routes_auth.SIGN_IN_AGAIN)


async def test_sessions_end_with_the_account(redis: FakeRedis) -> None:
    secret = totp.new_secret()
    user = _enrolled(secret)
    db = FakeDB(user)
    _, ticket = await _sign_in_ticket(db, user)
    response = Response()
    await routes_auth.verify_code(
        AdminCodeRequest(code=totp.code_now(secret, time.time())),
        _request(cookies={"debatr_admin_signin": ticket}),
        response,
        db,  # type: ignore[arg-type]
    )
    cookies = {"debatr_admin": _cookie(response, "debatr_admin") or ""}
    # An API token never opens the console, even next to a valid cookie.
    bearer = _request("GET", cookies=cookies, headers={"Authorization": "Bearer debatr_x"})
    assert await resolve_admin(bearer, db) is None  # type: ignore[arg-type]
    assert await resolve_admin(_request("GET", cookies=cookies), db) is not None  # type: ignore[arg-type]
    user.session_epoch += 1  # password changed / signed out everywhere
    assert await resolve_admin(_request("GET", cookies=cookies), db) is None  # type: ignore[arg-type]
    user.session_epoch -= 1
    assert await resolve_admin(_request("GET", cookies=cookies), db) is None  # deleted for good  # type: ignore[arg-type]
    with pytest.raises(HTTPException) as caught:
        await access.current_admin(_request("GET", cookies=cookies), db)  # type: ignore[arg-type]
    assert caught.value.status_code == 401


# --- AdminGate --------------------------------------------------------------------------------


def _decision(monkeypatch: pytest.MonkeyPatch, **kw: Any) -> tuple[int, str] | None:
    headers = kw.pop("headers", {})
    defaults: dict[str, Any] = {
        "path": "/api/admin/auth/me",
        "method": "GET",
        "host_header": "admin.example.com",
        "scheme": "https",
        "client": "203.0.113.9",
    }
    return gate_decision(headers=Headers(headers), **{**defaults, **kw})


@pytest.fixture
def production(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "ADMIN_HOST", "admin.example.com")
    monkeypatch.setattr(settings, "ADMIN_ALLOWED_IPS", "")
    return monkeypatch


def test_gate_host_and_network(production: pytest.MonkeyPatch) -> None:
    assert _decision(production) is None
    assert _decision(production, host_header="ADMIN.example.com:443") is None
    assert _decision(production, host_header="example.com") == (404, "Not Found")
    production.setattr(settings, "ADMIN_ALLOWED_IPS", "10.0.0.0/8, 2001:db8::/32")
    assert _decision(production) == (404, "Not Found")
    assert _decision(production, client="10.1.2.3") is None
    assert _decision(production, client="2001:db8::5") is None
    production.setattr(settings, "ADMIN_HOST", "")
    assert _decision(production, client="10.1.2.3") == (404, "Not Found")  # console off


def test_gate_fetch_metadata_and_origin(production: pytest.MonkeyPatch) -> None:
    for site in ("same-site", "cross-site"):
        assert _decision(production, headers={"sec-fetch-site": site})[0] == 403  # type: ignore[index]
    for site in ("same-origin", "none"):
        assert _decision(production, headers={"sec-fetch-site": site}) is None
    post = {"method": "POST"}
    assert _decision(production, **post)[0] == 403  # type: ignore[index]
    for origin in ("https://example.com", "https://shop.example.com", "http://admin.example.com"):
        assert _decision(production, headers={"origin": origin}, **post)[0] == 403, origin  # type: ignore[index]
    assert _decision(production, headers={"origin": "https://admin.example.com"}, **post) is None


def test_gate_in_development_shares_the_site_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(settings, "ADMIN_HOST", "")
    post: dict[str, Any] = {"method": "POST", "host_header": "localhost:8000", "scheme": "http"}
    listed = settings.allowed_origins_list[0]  # e.g. Vite's dev server
    assert _decision(monkeypatch, headers={"origin": listed}, **post) is None
    assert _decision(monkeypatch, headers={"origin": "http://localhost:8000"}, **post) is None
    assert _decision(monkeypatch, headers={"origin": "http://evil.test"}, **post)[0] == 403  # type: ignore[index]


def test_hostname() -> None:
    assert hostname("Admin.Example.com:8443") == "admin.example.com"
    assert hostname("[::1]:80") == "[::1]"
    assert hostname("localhost") == "localhost"


async def _call(
    app: AdminGate, path: str, host: str, method: str = "GET"
) -> tuple[int, Headers, bytes]:
    scope: dict[str, Any] = {
        "type": "http",
        "method": method,
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [(b"host", host.encode())],
        "client": ("203.0.113.9", 40000),
        "scheme": "https",
        "server": (host, 443),
    }
    sent: list[Message] = []

    async def receive() -> Message:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Message) -> None:
        sent.append(message)

    await app(scope, receive, send)
    start = next(m for m in sent if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return start["status"], Headers(raw=start["headers"]), body


async def test_gate_middleware(production: pytest.MonkeyPatch) -> None:
    async def ok(request: Request) -> PlainTextResponse:
        return PlainTextResponse("app")

    gate = AdminGate(Starlette(routes=[Route("/{path:path}", ok, methods=["GET", "POST"])]))
    admin = "admin.example.com"
    status, headers, body = await _call(gate, "/api/admin/auth/me", admin)
    assert (status, body) == (200, b"app") and headers["cache-control"] == "no-store"
    assert headers["x-frame-options"] == "DENY"
    assert (await _call(gate, "/api/debates", admin))[0] == 404  # the rest of the API is off
    assert (await _call(gate, "/api/health", admin))[2] == b"app"
    status, headers, _ = await _call(gate, "/api/admin/db/login", admin)
    assert status == 302 and headers["location"].startswith("/admin/login")
    assert (await _call(gate, "/api/admin/auth/login", admin, "POST"))[0] == 403  # no Origin
    assert (await _call(gate, "/api/admin/auth/me", "example.com"))[0] == 404
    assert (await _call(gate, "/api/debates", "example.com"))[2] == b"app"


# --- what never leaves the server -------------------------------------------------------------


def test_response_models_carry_no_secrets() -> None:
    forbidden = {"password", "password_hash", "totp_secret_enc", "recovery_codes_json", "token"}
    for name in (
        "AdminUserOut",
        "AdminSessionInfo",
        "AdminMeOut",
        "AdminSessionOut",
        "AdminLoginOut",
    ):
        model = getattr(admin_schemas, name)
        assert not set(model.model_fields) & forbidden, name


def test_audit_scrubs_secrets_at_any_depth() -> None:
    dirty = {
        "email": "a@b.co",
        "password_hash": "x",
        "nested": {"totp_secret_enc": "y", "ok": 1, "list": [{"code": "z", "keep": 2}]},
    }
    assert scrub(dirty) == {"email": "a@b.co", "nested": {"ok": 1, "list": [{"keep": 2}]}}
    assert json_safe({"when": datetime(2026, 1, 1, tzinfo=UTC)})["when"].startswith("2026")


def test_public_api_has_no_admin_bypass() -> None:
    owner, other = _user(), _user()
    private = Debate(id=uuid.uuid4(), user_id=owner.id, is_public=False)
    assert can_view(private, owner) and can_manage(private, owner)
    assert not can_view(private, other) and not can_manage(private, other)
    assert not can_view(private, None)


def test_sqladmin_is_locked_down() -> None:
    names = {column.key for column in UserAdmin.form_columns}  # type: ignore[union-attr]
    assert names == {"display_name", "is_active"}
    details = {column.key for column in UserAdmin.column_details_list}  # type: ignore[union-attr]
    assert not details & {"password_hash", "openrouter_key_enc", "totp_secret_enc", "admin_role"}
    assert not UserAdmin.can_delete and not TurnAdmin.can_edit and not ParticipantAdmin.can_edit
    (middleware,) = sqladmin_auth.authentication_backend.middlewares
    assert middleware.kwargs["same_site"] == "strict"


def test_manage_admin_commands_parse() -> None:
    parser = build_parser()
    args = parser.parse_args(["admin", "grant", "a@b.co", "--role", "moderator"])
    assert (args.action, args.email, args.role) == ("grant", "a@b.co", "moderator")
    assert parser.parse_args(["admin", "reset-2fa", "a@b.co"]).action == "reset-2fa"
    assert parser.parse_args(["admin", "list"]).action == "list"
    with pytest.raises(SystemExit):
        parser.parse_args(["admin", "grant", "a@b.co", "--role", "owner"])
