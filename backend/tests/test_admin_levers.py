"""Levers of the admin console (runtime_settings): values and limits, the per-process cache,
what the public API does with them, the Settings routes (sudo, reason, audit) and the audit
page's filters.

Pure: the `levers` fixture (conftest) stands for the table; routes get small fakes.
"""

import time
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from typing import Any

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import OperationalError
from starlette.requests import Request

from app.admin.access import SUDO_HEADER, AdminContext, current_admin, read_only_db
from app.api import routes_auth, routes_debates, routes_models
from app.api.admin import routes_audit, routes_settings
from app.core.config import settings
from app.core.db import get_db
from app.models.models import AdminAuditLog, ApiToken, Debate, RuntimeSetting, User
from app.schemas.admin import AuditQuery
from app.schemas.auth import RegisterRequest
from app.schemas.schemas import DebateConfig, EstimateOut
from app.services import alert_events, fair_share, free_quota, runtime_settings
from app.services.admin import audit
from app.services.admin.sessions import AdminSession
from app.services.openrouter_client import openrouter_client
from app.services.runtime_settings import LEVER_KEYS, Levers

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)


def _sql(statement: Any) -> str:
    return str(
        statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )


# --- values and limits ------------------------------------------------------------------------


def test_defaults_follow_the_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "SIGNUP_BONUS_USD", 2.5)
    monkeypatch.setattr(settings, "FREE_MODELS_PER_MINUTE", 99)  # out of range: clamped
    levers = runtime_settings.resolve({})
    assert levers.registration_open and not levers.maintenance
    assert levers.signup_bonus_usd == 2.5 and levers.free_models_per_minute == 20
    assert levers.max_active_debates_per_user == settings.MAX_ACTIVE_DEBATES_PER_USER


def test_stored_values_win_and_broken_ones_are_ignored() -> None:
    levers = runtime_settings.resolve(
        {
            "maintenance": True,
            "signup_bonus_usd": 500,  # above the limit
            "max_active_debates_per_user": "many",  # wrong type
            "dropped_lever": 1,  # no longer exists
            "disabled_models": [" openai/gpt-4o ", "openai/gpt-4o", "x-ai/grok-4:free"],
        }
    )
    assert levers.maintenance
    assert levers.signup_bonus_usd == runtime_settings.defaults()["signup_bonus_usd"]
    assert levers.max_active_debates_per_user == settings.MAX_ACTIVE_DEBATES_PER_USER
    assert levers.disabled_models == ["openai/gpt-4o", "x-ai/grok-4:free"]


def test_validate_value_names_the_problem() -> None:
    assert runtime_settings.validate_value("free_models_per_minute", 5) == 5
    assert runtime_settings.validate_value("maintenance_message", "  a   b ") == "a b"
    for key, value in (
        ("free_models_per_minute", 21),
        ("signup_bonus_usd", -1),
        ("disabled_models", ["not a model id!"]),
        ("maintenance_message", "x" * 301),
    ):
        with pytest.raises(ValueError, match=key):
            runtime_settings.validate_value(key, value)
    with pytest.raises(ValueError, match="No such setting"):
        runtime_settings.validate_value("admin_role", "admin")


def test_muted_alerts_take_known_kinds_in_the_catalogue_order() -> None:
    muted = runtime_settings.validate_value("muted_alerts", ["topup", "signin", "topup"])
    assert muted == ["signin", "topup"]
    with pytest.raises(ValueError, match=r"muted_alerts: .*no such alert"):
        runtime_settings.validate_value("muted_alerts", ["test"])  # the test always goes out


def test_maintenance_notice() -> None:
    assert "paused" in Levers(maintenance=True).notice()
    assert Levers(maintenance=True, maintenance_message="Back at 5").notice() == "Back at 5"


async def test_the_cache_and_a_database_outage(
    monkeypatch: pytest.MonkeyPatch, levers: dict
) -> None:
    calls: list[int] = []

    async def read() -> dict:
        calls.append(1)
        return dict(levers)

    monkeypatch.setattr(runtime_settings, "_stored", read)
    monkeypatch.setattr(runtime_settings, "CACHE_SECONDS", 60.0)
    levers["maintenance"] = True
    assert (await runtime_settings.current()).maintenance
    levers["maintenance"] = False
    assert (await runtime_settings.current()).maintenance  # cached
    assert len(calls) == 1
    runtime_settings.invalidate()
    assert not (await runtime_settings.current()).maintenance

    async def broken() -> dict:
        raise OperationalError("SELECT", {}, Exception("down"))

    levers["maintenance"] = True
    assert (await runtime_settings.current()).maintenance is False  # still cached
    monkeypatch.setattr(runtime_settings, "_stored", broken)
    runtime_settings.invalidate()
    assert not (await runtime_settings.current()).maintenance  # defaults, no crash


# --- the public API ---------------------------------------------------------------------------


def _config(*models: str) -> DebateConfig:
    return DebateConfig.model_validate(
        {
            "topic": "Tabs or spaces?",
            "participants": [
                {"role": "moderator", "model_id": models[0], "display_name": "Host"},
                *(
                    {"role": "debater", "model_id": m, "display_name": f"D{i}"}
                    for i, m in enumerate(models)
                ),
            ],
        }
    )


async def test_closed_sign_ups(levers: dict) -> None:
    levers["registration_open"] = False
    body = RegisterRequest(email="new@example.com", password="long enough pass")
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})
    with pytest.raises(HTTPException) as caught:
        await routes_auth.register(body, request, db=None)  # type: ignore[arg-type]
    assert caught.value.status_code == 403 and "closed" in caught.value.detail


async def test_the_signup_bonus_comes_from_the_lever(
    monkeypatch: pytest.MonkeyPatch, levers: dict, raised_alerts: list
) -> None:
    levers["signup_bonus_usd"] = 3
    granted: list[float] = []

    async def apply(db: Any, user_id: Any, amount: float, kind: str, **kw: Any) -> None:
        granted.append(amount)

    class DB:
        async def scalar(self, statement: Any) -> None:
            return None

        def add(self, obj: Any) -> None:
            obj.id = uuid.uuid4()

        async def flush(self) -> None: ...

        async def commit(self) -> None: ...

        async def refresh(self, obj: Any) -> None:
            obj.credits_usd = 3
            obj.created_at = NOW

    monkeypatch.setattr(routes_auth, "apply_transaction", apply)
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": [], "session": {}})
    body = RegisterRequest(email="new@example.com", password="long enough pass")
    await routes_auth.register(body, request, db=DB())  # type: ignore[arg-type]
    assert granted == [3]
    (alert,) = raised_alerts
    assert alert.kind == "signup" and alert.title == "New account: new@example.com"
    assert alert.detail == "New · $3.00 welcome credits"


def test_a_starting_debate_is_announced(raised_alerts: list) -> None:
    config = _config("openai/gpt-4o-mini", "x-ai/grok-4")
    debate = Debate(id=uuid.uuid4(), title="Tabs or spaces?")
    user = User(email="ann@example.com")
    est = EstimateOut.model_construct(credits_cost_usd=0.25)
    token = ApiToken(name="laptop")
    routes_debates._announce(debate, config, user, est, False, token, from_draft=True)
    (alert,) = raised_alerts
    assert alert.kind == "debate" and alert.path == f"/admin/debates/{debate.id}"
    assert alert.detail == (
        "ann@example.com · gpt-4o-mini vs grok-4 · 3 rounds · about $0.25 · "
        "API token “laptop” · from a draft"
    )


async def test_maintenance_and_turned_off_models(levers: dict) -> None:
    config = _config("openai/gpt-4o-mini", "x-ai/grok-4")
    await routes_debates._require_runnable(config)
    levers["disabled_models"] = ["x-ai/grok-4"]
    with pytest.raises(HTTPException) as caught:
        await routes_debates._require_runnable(config, starting=False)
    assert caught.value.status_code == 400 and "x-ai/grok-4 is turned off" in caught.value.detail
    levers["disabled_models"] = []
    levers["maintenance"] = True
    levers["maintenance_message"] = "Back in 10 minutes"
    await routes_debates._require_runnable(config, starting=False)  # estimates still work
    with pytest.raises(HTTPException) as caught:
        await routes_debates._require_runnable(config)
    assert (caught.value.status_code, caught.value.detail) == (503, "Back in 10 minutes")


async def test_the_model_list_hides_turned_off_models(
    monkeypatch: pytest.MonkeyPatch, levers: dict
) -> None:
    def model(model_id: str) -> dict[str, Any]:
        return {
            "id": model_id,
            "name": model_id,
            "context_length": 1000,
            "pricing": {"prompt": "0", "completion": "0"},
            "is_free": True,
        }

    async def catalogue() -> list[dict[str, Any]]:
        return [model("openai/gpt-4o-mini"), model("x-ai/grok-4")]

    monkeypatch.setattr(openrouter_client, "get_models", catalogue)
    levers["disabled_models"] = ["x-ai/grok-4"]
    out = await routes_models.get_models()
    assert [m.id for m in out.data] == ["openai/gpt-4o-mini"]


async def test_site_status(levers: dict) -> None:
    from app.api.routes_status import site_status

    assert (await site_status()).model_dump() == {
        "registration_open": True,
        "maintenance": False,
        "maintenance_message": None,
        "free_debates": {
            "per_day": 5,
            "max_rounds": 3,
            "max_debaters": 4,
            "lengths": ["very_short", "short"],
        },
    }
    levers.update(registration_open=False, maintenance=True)
    out = await site_status()
    assert not out.registration_open and out.maintenance and out.maintenance_message


async def test_limits_follow_the_levers(levers: dict) -> None:
    levers.update(max_active_debates_per_user=0, max_active_media_per_user=0)
    # 0 = no limit: no database needed.
    await fair_share.require_debate_slot(None, uuid.uuid4())  # type: ignore[arg-type]
    await fair_share.require_media_slot(None, uuid.uuid4())  # type: ignore[arg-type]
    levers["free_models_per_minute"] = 0
    assert free_quota.wait_for_slot(time.monotonic() + 1)


# --- the Settings routes ----------------------------------------------------------------------


class SettingsDB:
    def __init__(self) -> None:
        self.rows: dict[str, RuntimeSetting] = {}
        self.added: list[Any] = []
        self.commits = 0

    async def scalars(self, statement: Any) -> Any:
        rows = list(self.rows.values())

        class Rows:
            def all(self) -> list[Any]:
                return rows

        return Rows()

    async def get(self, model: type, key: Any, **kw: Any) -> Any:
        return self.rows.get(key) if model is RuntimeSetting else None

    def add(self, obj: Any) -> None:
        self.added.append(obj)
        if isinstance(obj, RuntimeSetting):
            self.rows[obj.key] = obj

    async def delete(self, obj: Any) -> None:
        self.rows.pop(obj.key, None)

    async def commit(self) -> None:
        self.commits += 1

    def audit(self) -> list[AdminAuditLog]:
        return [row for row in self.added if isinstance(row, AdminAuditLog)]


def _ctx(role: str = "admin", sudo: bool = False) -> AdminContext:
    user = User(id=uuid.uuid4(), email=f"{role}@example.com", admin_role=role, session_epoch=0)
    session = AdminSession(
        user_id=str(user.id),
        csrf="c",
        created_at=time.time(),
        last_seen_at=time.time(),
        ip="",
        user_agent="",
        epoch=0,
        sudo_until=time.time() + 60 if sudo else 0.0,
    )
    return AdminContext(user=user, session=session, session_hash="h", ip=None, user_agent=None)


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch) -> tuple[FastAPI, SettingsDB]:
    db = SettingsDB()

    async def fake_db() -> AsyncIterator[Any]:
        yield db

    async def catalogue() -> list[dict[str, Any]]:
        return [{"id": "x-ai/grok-4", "name": "Grok 4"}]

    monkeypatch.setattr(openrouter_client, "get_models", catalogue)
    app = FastAPI()
    app.include_router(routes_settings.router, prefix="/api/admin")
    app.include_router(routes_audit.router, prefix="/api/admin")
    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[read_only_db] = fake_db
    return app, db


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


def test_every_lever_has_a_kind() -> None:
    assert set(routes_settings.KINDS) == set(LEVER_KEYS)
    assert routes_settings.bounds("free_models_per_minute") == (0, 20)
    assert routes_settings.bounds("maintenance") == (None, None)


async def test_moderators_see_neither_settings_nor_the_log(
    api: tuple[FastAPI, SettingsDB],
) -> None:
    app, _db = api
    app.dependency_overrides[current_admin] = lambda: _ctx("moderator")
    async with _client(app) as client:
        for path in ("settings", "alerts", "audit", "audit/facets", "audit/security"):
            assert (await client.get(f"/api/admin/{path}")).status_code == 403, path


async def test_changing_a_lever_needs_sudo_and_a_reason(
    api: tuple[FastAPI, SettingsDB],
) -> None:
    app, db = api
    app.dependency_overrides[current_admin] = lambda: _ctx("admin")
    body = {"value": True, "reason": "deploying 0.9"}
    async with _client(app) as client:
        listed = (await client.get("/api/admin/settings")).json()
        assert [lever["key"] for lever in listed["levers"]] == list(LEVER_KEYS)
        assert listed["models"] == [{"id": "x-ai/grok-4", "name": "Grok 4"}]
        refused = await client.put("/api/admin/settings/maintenance", json=body)
        assert refused.status_code == 403 and refused.headers.get(SUDO_HEADER) == "required"
        app.dependency_overrides[current_admin] = lambda: _ctx("admin", sudo=True)
        no_reason = await client.put("/api/admin/settings/maintenance", json={"value": True})
        assert no_reason.status_code == 422
        bad = await client.put(
            "/api/admin/settings/free_models_per_minute", json={"value": 50, "reason": "more"}
        )
        assert bad.status_code == 422 and "free_models_per_minute" in bad.json()["detail"]
        assert (await client.put("/api/admin/settings/nope", json=body)).status_code == 404
        done = await client.put("/api/admin/settings/maintenance", json=body)
    assert done.status_code == 200, done.text
    lever = next(item for item in done.json()["levers"] if item["key"] == "maintenance")
    assert lever["value"] is True and lever["overridden"] and lever["default"] is False
    assert lever["updated_by"] == "admin@example.com"
    (entry,) = db.audit()
    assert (entry.action, entry.target_type, entry.target_id) == (
        "settings.changed",
        "setting",
        "maintenance",
    )
    assert entry.before_json == {"maintenance": False} and entry.after_json == {"maintenance": True}
    assert entry.reason == "deploying 0.9" and db.commits == 1


async def test_reset_goes_back_to_the_env(api: tuple[FastAPI, SettingsDB]) -> None:
    app, db = api
    app.dependency_overrides[current_admin] = lambda: _ctx("admin", sudo=True)
    reason = {"reason": "back to normal"}
    async with _client(app) as client:
        assert (
            await client.post("/api/admin/settings/maintenance/reset", json=reason)
        ).status_code == 409
        await client.put(
            "/api/admin/settings/disabled_models",
            json={"value": ["x-ai/grok-4"], "reason": "breaks debates"},
        )
        done = await client.post("/api/admin/settings/disabled_models/reset", json=reason)
    assert done.status_code == 200
    assert "disabled_models" not in db.rows
    reset = db.audit()[-1]
    assert reset.action == "settings.reset"
    assert reset.before_json == {"disabled_models": ["x-ai/grok-4"]}
    assert reset.after_json == {"disabled_models": []}


async def test_muting_alerts_is_itself_an_alert(
    api: tuple[FastAPI, SettingsDB], raised_alerts: list
) -> None:
    app, db = api
    app.dependency_overrides[current_admin] = lambda: _ctx("admin", sudo=True)
    async with _client(app) as client:
        listed = (await client.get("/api/admin/settings")).json()
        assert [e["kind"] for e in listed["alert_events"]] == list(alert_events.KINDS)
        assert listed["alert_events"][0]["group"] == "security"
        bad = await client.put(
            "/api/admin/settings/muted_alerts", json={"value": ["nope"], "reason": "quiet"}
        )
        assert bad.status_code == 422
        done = await client.put(
            "/api/admin/settings/muted_alerts",
            json={"value": ["debate", "signin"], "reason": "too many"},
        )
        assert done.status_code == 200, done.text
        await client.post("/api/admin/settings/muted_alerts/reset", json={"reason": "back"})
    assert db.rows == {}
    muted, restored = raised_alerts
    assert muted.kind == "mutes" and muted.severity == "warning"
    assert muted.detail == "by admin@example.com; muted: Console sign-in, New debate"
    assert restored.detail.endswith("on again: Console sign-in, New debate")


# --- the audit page ---------------------------------------------------------------------------


def test_audit_filters_reach_the_query() -> None:
    query = AuditQuery(
        tab="security",
        q="50%_off",
        actor="boss@example.com",
        action="auth.",
        target_type="user",
        target_id="abc",
        ok=False,
        created_from=date(2026, 10, 1),
        created_to=date(2026, 10, 18),
    )
    sql = " ".join(_sql(c) for c in audit.audit_conditions(query))
    for piece in (
        "admin_audit_log.action LIKE 'auth.' || '%%'",
        "admin_audit_log.action LIKE 'role.' || '%%'",
        "admin_audit_log.actor_email = 'boss@example.com'",
        "admin_audit_log.target_type = 'user'",
        "admin_audit_log.target_id = 'abc'",
        "admin_audit_log.ok IS false",
        "admin_audit_log.created_at >= '2026-10-01 00:00:00+00:00'",
        "admin_audit_log.created_at < '2026-10-19 00:00:00+00:00'",
        "ESCAPE",
    ):
        assert piece in sql, piece
    assert "\\%%\\_off" in sql or "\\%\\_off" in sql
    exact = " ".join(_sql(c) for c in audit.audit_conditions(AuditQuery(action="auth.sudo")))
    assert "admin_audit_log.action = 'auth.sudo'" in exact
    assert audit.audit_conditions(AuditQuery()) == []


def test_audit_entries_keep_the_browser() -> None:
    entry = AdminAuditLog(
        id=uuid.uuid4(),
        action="auth.signed_in",
        actor_user_id=uuid.uuid4(),
        actor_email="a@b.co",
        user_agent="Mozilla/5.0",
        ok=True,
    )
    out = audit.entry_out(entry)
    assert out["user_agent"] == "Mozilla/5.0" and out["actor_user_id"] == str(entry.actor_user_id)
