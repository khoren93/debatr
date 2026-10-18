"""Admin console debates: filters, the card's pure parts, moderation decisions, refunds
(idempotent, capped, sudo above the threshold), roles and the free media build flag.

Pure: queries are compiled, not run; routes get small in-memory fakes.
"""

import time
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from sqlalchemy.dialects import postgresql
from starlette.requests import Request

from app.admin.access import SUDO_HEADER, AdminContext, can, current_admin, read_only_db
from app.api.admin import routes_debates
from app.core.config import settings
from app.models.models import AdminAuditLog, CreditTransaction, Debate, TrendingBatch, Turn, User
from app.schemas import admin as admin_schemas
from app.schemas.admin import DebateFilters, ReasonRequest, RefundRequest
from app.services.admin import debates as admin_debates
from app.services.admin.sessions import AdminSession
from app.services.media.state import free_build

NOW = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)


def _sql(statement: Any) -> str:
    return str(
        statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )


# --- filters ----------------------------------------------------------------------------------


def test_search_by_id_title_or_slug() -> None:
    did = uuid.uuid4()
    by_id = admin_debates.search_condition(str(did))
    assert by_id is not None and "debates.id =" in _sql(by_id)
    text = admin_debates.search_condition("AI_50%")
    assert text is not None
    sql = _sql(text)
    assert "ILIKE" in sql and "ESCAPE" in sql and "debates.slug = 'AI_50%%'" in sql
    assert admin_debates.search_condition("  ") is None


def test_filters_reach_the_query() -> None:
    owner = uuid.uuid4()
    filters = DebateFilters(
        status="completed",
        moderation="flagged",
        media="error",
        public=False,
        own_key=True,
        via_token=False,
        model="openai/gpt-5.5",
        user_id=owner,
        created_from=NOW.date(),
        failed=False,
        active=False,
    )
    sql = _sql(admin_debates.debates_query(filters, "cost", True))
    for piece in (
        "debates.status = 'completed'",
        "debates.moderation_status = 'flagged'",
        "debates.media_status = 'error'",
        "debates.is_public IS false",
        "coalesce(CAST((debates.config_json #>> '{billing, own_key}') AS VARCHAR), 'false') = 'true'",
        "debates.api_token_id IS NULL",
        "debate_participants.model_id = 'openai/gpt-5.5'",
        f"debates.user_id = '{owner}'",
        "debates.created_at >= '2026-10-18 00:00:00+00:00'",
        "debates.status NOT IN ('queued', 'running')",
        "debates.status != 'error'",
        "ORDER BY coalesce(costs.cost, 0) DESC NULLS LAST, debates.id",
    ):
        assert piece in sql, piece
    # Only the system keys count as our cost.
    assert "provider_usage.key_owner = 'system'" in sql


def test_no_filters_no_conditions() -> None:
    assert admin_debates.filter_conditions(DebateFilters()) == []


# --- the card's pure parts --------------------------------------------------------------------


def _debate(**fields: Any) -> Debate:
    defaults: dict[str, Any] = {
        "id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "title": "Tabs or spaces?",
        "status": "completed",
        "config_json": {"topic": "Tabs or spaces?", "billing": {"own_key": False}},
        "moderation_status": "none",
        "moderation_json": {},
        "media_status": "none",
        "media_json": {},
        "is_public": False,
        "slug": None,
        "views": 3,
        "likes_count": 2,
        "votes_count": 1,
        "created_at": NOW,
        "started_at": NOW,
        "ended_at": NOW + timedelta(minutes=4, seconds=2),
        "api_token_id": None,
        "error_message": None,
        "totals_json": {},
        "verdict_json": {},
    }
    return Debate(**{**defaults, **fields})


def test_row_hides_money_without_the_permission() -> None:
    debate = _debate()
    extra = {"owner_email": "ann@x.co", "owner_name": "Ann", "turns": 7, "cost": 0.5, "charged": 1}
    row = admin_debates.row_out(debate, extra, ["a/b"], with_money=False)
    assert row["cost"] is None and row["charged"] is None
    assert row["duration_ms"] == 242_000 and row["turns"] == 7
    assert row["owner"] == {"id": str(debate.user_id), "email": "ann@x.co", "display_name": "Ann"}
    money = admin_debates.row_out(debate, extra, [], with_money=True)
    assert (money["cost"], money["charged"]) == (0.5, 1.0)
    legacy = admin_debates.row_out(_debate(user_id=None), {}, [], with_money=True)
    assert legacy["owner"] is None and legacy["cost"] == 0.0


def test_turn_row() -> None:
    turn = Turn(
        seq_index=2,
        round_id="round_1",
        turn_type="rebuttal",
        speaker_name="Claude",
        model_used="anthropic/claude-opus-4.7",
        text="No.",
        error=None,
        usage_json={
            "prompt_tokens": 900,
            "completion_tokens": 120,
            "cost": 0.0123,
            "duration_ms": 8100,
            "ttft_ms": 950,
        },
        visuals_json={},
        created_at=NOW,
    )
    row = admin_debates.turn_row(turn)
    assert (row["tokens_in"], row["tokens_out"], row["cost"]) == (900, 120, 0.0123)
    assert (row["duration_ms"], row["ttft_ms"], row["error_kind"]) == (8100, 950, None)
    assert (row["scenes"], row["checks"], row["visuals_status"]) == (0, {}, "none")


def test_config_never_carries_keys() -> None:
    dirty = {
        "topic": "x",
        "user_provider_key": "sk-or-1",
        "participants": [{"model_id": "a/b", "user_tts_key": "el"}],
        "billing": {"own_key": True},
    }
    assert admin_debates.clean_config(dirty) == {
        "topic": "x",
        "participants": [{"model_id": "a/b"}],
        "billing": {"own_key": True},
    }


def test_resume_and_refund_rules() -> None:
    assert admin_debates.can_resume(_debate(status="error"), own_key=False)
    assert not admin_debates.can_resume(_debate(status="error"), own_key=True)
    assert not admin_debates.can_resume(_debate(status="completed"), own_key=False)
    assert not admin_debates.can_resume(_debate(status="error", media_status="running"), False)
    assert admin_debates.refundable(0.42) == 0.42 and admin_debates.refundable(-0.1) == 0.0


def test_private_debates() -> None:
    assert admin_debates.is_private(_debate())
    assert not admin_debates.is_private(_debate(is_public=True))
    assert not admin_debates.is_private(_debate(user_id=None))  # legacy rows: link-readable


def test_batch_row() -> None:
    batch = TrendingBatch(
        id=uuid.uuid4(),
        created_at=NOW,
        model="google/gemini-3-flash",
        topic_count=12,
        cost_usd=Decimal("0.021"),
        stats_json={
            "feeds_ok": 11,
            "feeds_total": 12,
            "headlines_fresh": "300",
            "dropped": [{"question": "q", "reason": "r"}],
        },
    )
    row = admin_debates.batch_row(batch, hidden=2, current=True)
    assert (row["feeds_ok"], row["headlines_fresh"], row["headlines_sent"]) == (11, 300, None)
    assert (row["dropped"], row["hidden"], row["current"], row["cost_usd"]) == (1, 2, True, 0.021)


def test_free_media_builds() -> None:
    assert free_build(_debate(media_json={"free": True}))
    assert not free_build(_debate(media_json={"free": False}))
    assert not free_build(_debate())


def test_roles() -> None:
    assert can("moderator", "debates.read") and can("moderator", "moderation")
    assert not can("moderator", "debates") and not can("moderator", "money")
    assert can("admin", "debates") and can("admin", "money")


def test_response_models_carry_no_secrets() -> None:
    forbidden = {"password_hash", "openrouter_key_enc", "token_hash", "user_provider_key"}
    for name in ("AdminDebateRow", "AdminDebateCard", "AdminTurn", "ModerationItem"):
        assert not set(getattr(admin_schemas, name).model_fields) & forbidden, name


# --- routes -----------------------------------------------------------------------------------


def _admin(role: str = "admin") -> User:
    return User(id=uuid.uuid4(), email=f"{role}@x.co", display_name=role, admin_role=role)


def _ctx(user: User, sudo: bool = False) -> AdminContext:
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


def _request() -> Request:
    return Request({"type": "http", "method": "POST", "path": "/", "headers": [], "client": None})


class FakeDB:
    """The statements the moderation and refund routes run, answered from memory."""

    def __init__(self, debate: Debate, owner_balance: str = "1.00") -> None:
        self.debate = debate
        self.balance = Decimal(owner_balance)
        self.txs: list[CreditTransaction] = []
        self.added: list[Any] = []
        self.commits = 0

    async def scalar(self, statement: Any) -> Any:
        sql = _sql(statement)
        if "provider_ref =" in sql:
            return next((t for t in self.txs if f"'{t.provider_ref}'" in sql), None)
        if "sum(credit_transactions.amount_usd)" in sql:
            return sum((t.amount_usd for t in self.txs), Decimal("-0.50"))  # the debate's charge
        if "debates.slug =" in sql:
            return None  # every slug is free
        return self.debate

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        return None

    def audit(self) -> list[str]:
        return [row.action for row in self.added if isinstance(row, AdminAuditLog)]


def _fake(debate: Debate) -> Any:
    return FakeDB(debate)


@pytest.fixture
def ledger(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def lock_balance(db: FakeDB, user_id: uuid.UUID) -> Decimal:
        return db.balance

    async def apply(db: FakeDB, user_id: uuid.UUID, amount: Decimal, kind: str, **kw: Any) -> Any:
        calls.append({"amount": amount, "kind": kind, **kw})
        db.balance += amount
        tx = CreditTransaction(
            id=uuid.uuid4(),
            user_id=user_id,
            amount_usd=amount,
            balance_after_usd=db.balance,
            kind=kind,
            debate_id=kw.get("debate_id"),
            provider_ref=kw["provider_ref"],
        )
        db.txs.append(tx)
        return tx

    monkeypatch.setattr(routes_debates, "lock_balance", lock_balance)
    monkeypatch.setattr(routes_debates, "apply_transaction", apply)
    return calls


async def test_refund_is_idempotent_and_capped(ledger: list[dict[str, Any]]) -> None:
    debate = _debate()
    db: Any = FakeDB(debate)
    admin = _admin()
    body = RefundRequest(reason="provider outage", idempotency_key=uuid.uuid4())
    first = await routes_debates.refund(str(debate.id), body, _request(), _ctx(admin), db)
    assert (first.amount, first.balance_after, first.duplicate) == (0.5, 1.5, False)
    assert ledger[0]["kind"] == "refund" and ledger[0]["debate_id"] == debate.id
    assert ledger[0]["provider_ref"] == f"admin:refund:{debate.id}:{body.idempotency_key}"
    again = await routes_debates.refund(str(debate.id), body, _request(), _ctx(admin), db)
    assert again.duplicate and again.transaction_id == first.transaction_id and len(ledger) == 1
    other = RefundRequest(reason="again", idempotency_key=uuid.uuid4())
    with pytest.raises(HTTPException) as caught:
        await routes_debates.refund(str(debate.id), other, _request(), _ctx(admin), db)
    assert caught.value.status_code == 409  # nothing left: the charge was refunded in full
    assert db.audit() == ["debate.refunded"]


async def test_refund_limits(ledger: list[dict[str, Any]]) -> None:
    debate = _debate()
    admin = _admin()
    too_much = RefundRequest(reason="x" * 3, amount=Decimal("0.6"), idempotency_key=uuid.uuid4())
    with pytest.raises(HTTPException) as caught:
        await routes_debates.refund(
            str(debate.id), too_much, _request(), _ctx(admin), _fake(debate)
        )
    assert caught.value.status_code == 422
    negative = RefundRequest(reason="oops", amount=Decimal("-1"), idempotency_key=uuid.uuid4())
    with pytest.raises(HTTPException) as caught:
        await routes_debates.refund(
            str(debate.id), negative, _request(), _ctx(admin), _fake(debate)
        )
    assert caught.value.status_code == 422
    legacy = _debate(user_id=None)
    with pytest.raises(HTTPException) as caught:
        await routes_debates.refund(
            str(legacy.id), too_much, _request(), _ctx(admin), _fake(legacy)
        )
    assert caught.value.status_code == 409 and not ledger


async def test_large_refunds_need_sudo(
    ledger: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "ADMIN_SUDO_USD", 0.1)
    debate = _debate()
    db: Any = FakeDB(debate)
    body = RefundRequest(reason="outage", idempotency_key=uuid.uuid4())
    with pytest.raises(HTTPException) as caught:
        await routes_debates.refund(str(debate.id), body, _request(), _ctx(_admin()), db)
    assert caught.value.status_code == 403
    assert (caught.value.headers or {}).get(SUDO_HEADER) == "required" and not ledger
    done = await routes_debates.refund(str(debate.id), body, _request(), _ctx(_admin(), True), db)
    assert done.amount == 0.5


async def test_approve_publishes_only_what_the_owner_wants() -> None:
    wanted = _debate(moderation_status="flagged", moderation_json={"publish_requested": True})
    db: Any = FakeDB(wanted)
    out = await routes_debates.approve(
        str(wanted.id), ReasonRequest(reason="satire, fine"), _request(), _ctx(_admin()), db
    )
    assert out.status == "approved" and wanted.is_public and wanted.slug
    assert wanted.moderation_status == "approved"
    assert wanted.moderation_json["admin_reason"] == "satire, fine"
    private = _debate(moderation_status="flagged")
    db = FakeDB(private)
    await routes_debates.approve(
        str(private.id), ReasonRequest(reason="fine"), _request(), _ctx(_admin()), db
    )
    assert not private.is_public and db.audit() == ["moderation.approved"]


async def test_reject_takes_it_down() -> None:
    debate = _debate(is_public=True, slug="abc", moderation_status="approved")
    db: Any = FakeDB(debate)
    await routes_debates.reject(
        str(debate.id), ReasonRequest(reason="hate speech"), _request(), _ctx(_admin()), db
    )
    assert not debate.is_public and debate.moderation_status == "rejected"
    assert db.audit() == ["moderation.rejected"]


async def test_publish_respects_the_owner_and_moderation() -> None:
    for debate in (
        _debate(),  # the owner keeps it private
        _debate(moderation_status="flagged", moderation_json={"publish_requested": True}),
        _debate(status="error", config_json={"auto_publish": True}),
    ):
        with pytest.raises(HTTPException) as caught:
            await routes_debates.publish(
                str(debate.id),
                ReasonRequest(reason="go live"),
                _request(),
                _ctx(_admin()),
                _fake(debate),
            )
        assert caught.value.status_code == 409
    ok = _debate(config_json={"auto_publish": True})
    await routes_debates.publish(
        str(ok.id), ReasonRequest(reason="go live"), _request(), _ctx(_admin()), _fake(ok)
    )
    assert ok.is_public and ok.published_at is not None


# --- roles and query parameters over HTTP -----------------------------------------------------


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch) -> tuple[FastAPI, list[dict[str, Any]]]:
    calls: list[dict[str, Any]] = []

    async def list_debates(db: Any, filters: DebateFilters, **kw: Any) -> tuple[int, list[Any]]:
        calls.append({"filters": filters, **kw})
        return 0, []

    async def no_db() -> AsyncIterator[None]:
        yield None

    monkeypatch.setattr(admin_debates, "list_debates", list_debates)
    app = FastAPI()
    app.include_router(routes_debates.router, prefix="/api/admin")
    app.dependency_overrides[read_only_db] = no_db
    from app.core.db import get_db

    app.dependency_overrides[get_db] = no_db
    return app, calls


async def test_list_parameters_and_roles(api: tuple[FastAPI, list[dict[str, Any]]]) -> None:
    app, calls = api
    app.dependency_overrides[current_admin] = lambda: _ctx(_admin("moderator"))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        ok = await client.get(
            "/api/admin/debates",
            params={
                "status": "error",
                "own_key": "false",
                "model": "a/b",
                "sort": "charged",
                "order": "asc",
                "limit": 5,
            },
        )
        assert ok.status_code == 200, ok.text
        call = calls[-1]
        assert (call["sort"], call["descending"], call["limit"]) == ("charged", False, 5)
        assert call["with_money"] is False  # a moderator sees no money
        f: DebateFilters = call["filters"]
        assert (f.status, f.own_key, f.model) == ("error", False, "a/b")
        for bad in ({"status": "lost"}, {"media": "x"}, {"limit": 0}, {"sort": "owner"}):
            assert (await client.get("/api/admin/debates", params=bad)).status_code == 422, bad
        # A moderator moderates but does not stop, delete or refund.
        for action in ("stop", "delete", "resume", "media", "recount"):
            r = await client.post(
                f"/api/admin/debates/{uuid.uuid4()}/{action}", json={"reason": "x" * 5}
            )
            assert r.status_code == 403, action
        refund = await client.post(
            f"/api/admin/debates/{uuid.uuid4()}/refund",
            json={"reason": "outage", "idempotency_key": str(uuid.uuid4())},
        )
        assert refund.status_code == 403
