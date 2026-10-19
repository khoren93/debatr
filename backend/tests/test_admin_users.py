"""Admin console accounts: search and filters, the card's statistics, the CSV, credit changes
(idempotent, sudo above the threshold), protected accounts and the user cookie's epoch.

Pure: queries are compiled, not run; the routes get a small in-memory database.
"""

import time
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql
from starlette.requests import Request

from app.admin.access import SUDO_HEADER, AdminContext
from app.api.admin import routes_users
from app.core import auth
from app.core.config import settings
from app.models.models import AdminAuditLog, CreditTransaction, User
from app.schemas import admin as admin_schemas
from app.schemas.admin import CreditChangeRequest, DisableUserRequest, ReasonRequest, UserFilters
from app.services.admin import users as accounts
from app.services.admin.sessions import AdminSession
from app.services.admin.users import DebateFacts, TxFacts
from app.services.credits import check_manual_change

NOW = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)


def _sql(statement: Any) -> str:
    return str(
        statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )


# --- search and filters -----------------------------------------------------------------------


def test_like_pattern_escapes_wildcards() -> None:
    assert accounts.like_pattern("a_b%c\\d") == "%a\\_b\\%c\\\\d%"


def test_search_by_id_or_text() -> None:
    uid = uuid.uuid4()
    by_id = accounts.search_condition(f" {uid} ")
    assert by_id is not None and "users.id =" in _sql(by_id)
    text = accounts.search_condition("50%_off")
    assert text is not None
    sql = _sql(text)
    assert "ILIKE '%%50\\%%\\_off%%'" in sql or "ILIKE '%50\\%\\_off%'" in sql
    assert "ESCAPE" in sql and "display_name" in sql
    assert accounts.search_condition("   ") is None


def test_filters_reach_the_query() -> None:
    filters = UserFilters(
        q="ann",
        paid=True,
        balance="negative",
        own_key=True,
        tokens=False,
        status="disabled",
        staff=False,
        created_from=NOW.date() - timedelta(days=7),
        created_to=NOW.date(),
        active_days=30,
    )
    sql = _sql(accounts.users_query(filters, "spent", True, NOW))
    for piece in (
        "users.credits_usd < 0",
        "users.openrouter_key_enc IS NOT NULL",
        "users.is_active IS false",
        "users.admin_role IS NULL",
        "coalesce(tokens.tokens, 0) = 0",
        "coalesce(ledger.topped_up, 0) > 0",
        "users.created_at >= '2026-10-11 00:00:00+00:00'",
        "users.created_at < '2026-10-19 00:00:00+00:00'",
        "users.last_seen_at >= '2026-09-18 12:00:00+00:00'",
        "ORDER BY coalesce(ledger.spent, 0) DESC NULLS LAST, users.id",
    ):
        assert piece in sql, piece
    # Drafts are not runs.
    assert "debates.status != 'draft'" in sql


def test_no_filters_no_conditions() -> None:
    assert accounts.filter_conditions(UserFilters(), {}, NOW) == []
    sql = _sql(accounts.users_query(UserFilters(), "last_seen", False, NOW))
    assert "ORDER BY users.last_seen_at ASC NULLS LAST" in sql


def test_filter_bounds_are_validated() -> None:
    with pytest.raises(ValueError):
        UserFilters(active_days=0)
    with pytest.raises(ValueError):
        UserFilters.model_validate({"balance": "zero"})


# --- the card's statistics --------------------------------------------------------------------


def _debate(
    days_ago: float,
    status: str = "completed",
    models: tuple[str, ...] = ("openai/gpt-5", "google/gemini-3-pro"),
    **fields: Any,
) -> DebateFacts:
    defaults: dict[str, Any] = {
        "own_key": False,
        "via_token": False,
        "tokens_in": 100,
        "tokens_out": 50,
    }
    return DebateFacts(
        id=uuid.uuid4(),
        created_at=NOW - timedelta(days=days_ago),
        status=status,
        models=models,
        **{**defaults, **fields},
    )


def _tx(days_ago: float, kind: str, amount: float, category: str | None = None) -> TxFacts:
    return TxFacts(
        created_at=NOW - timedelta(days=days_ago),
        kind=kind,
        category=category or {"debate": "models"}.get(kind, kind),
        amount=amount,
    )


DEBATES = [
    _debate(1),
    _debate(2, "error", ("openrouter/free", "meta-llama/llama-4:free")),
    _debate(3, "stopped", own_key=True),
    _debate(40, via_token=True),
    _debate(0.5, "draft"),
]
TXS = [
    _tx(60, "bonus", 1.0),
    _tx(45, "topup", 10.0),
    _tx(40, "debate", -0.4),
    _tx(1, "debate", -0.2),
    _tx(1, "media", -0.3, "voices"),
    _tx(2, "media", -0.05, "pictures"),
    _tx(2, "refund", 0.1),
    _tx(2, "adjustment", -0.5),
    _tx(3, "adjustment", 0.25),
]


def test_period_stats_all_time() -> None:
    out = accounts.period_stats(DEBATES, TXS, since=None, cost_system=0.123)
    assert out["debates"] == 4  # the draft left out
    assert (out["completed"], out["failed"], out["stopped"]) == (2, 1, 1)
    assert out["error_rate"] == 0.25
    assert (out["free_debates"], out["paid_debates"]) == (1, 3)
    assert (out["own_key_debates"], out["token_debates"]) == (1, 1)
    assert (out["tokens_in"], out["tokens_out"]) == (400, 200)
    assert out["topped_up"] == 10.0
    assert out["credited"] == 1.35  # bonus + refund + the positive adjustment
    assert out["spent_by"] == {"models": 0.6, "voices": 0.3, "pictures": 0.05, "music": 0.0}
    assert out["spent"] == 0.95  # adjustments are not spending
    assert out["avg_debate_cost"] == 0.15  # model tokens per finished debate
    assert out["cost_system"] == 0.123


def test_period_stats_since() -> None:
    out = accounts.period_stats(DEBATES, TXS, since=NOW - timedelta(days=30), cost_system=0)
    assert out["debates"] == 3 and out["token_debates"] == 0
    assert out["topped_up"] == 0 and out["spent_by"]["models"] == 0.2
    empty = accounts.period_stats([], [], since=None, cost_system=0)
    assert empty["error_rate"] is None and empty["avg_debate_cost"] is None


def test_free_models() -> None:
    assert accounts.is_free_model("openrouter/free")
    assert accounts.is_free_model("deepseek/deepseek-r1:free")
    assert not accounts.is_free_model("openai/gpt-5")


def test_favorite_models_count_debates_not_seats() -> None:
    mirror = _debate(1, models=("openai/gpt-5", "openai/gpt-5"))
    out = accounts.favorite_models([*DEBATES, mirror], limit=3)
    assert out[0] == {"model": "openai/gpt-5", "debates": 4}
    assert out[1] == {"model": "google/gemini-3-pro", "debates": 3}
    assert out[2]["model"] == "meta-llama/llama-4:free"  # ties sorted by name


def test_spend_days() -> None:
    days = accounts.spend_days(TXS, NOW)
    assert len(days) == 30
    assert days[-1]["day"] == NOW.date() and days[0]["day"] == NOW.date() - timedelta(days=29)
    by_day = {d["day"]: d for d in days}
    yesterday = by_day[NOW.date() - timedelta(days=1)]
    assert (yesterday["models"], yesterday["voices"]) == (0.2, 0.3)
    assert by_day[NOW.date() - timedelta(days=2)]["pictures"] == 0.05
    assert sum(d["models"] for d in days) == 0.2  # 40 days ago is outside


# --- CSV, passwords, credit rules -------------------------------------------------------------


def _row(**fields: Any) -> dict[str, Any]:
    base = accounts.row_out(
        User(
            id=uuid.uuid4(),
            email="ann@example.com",
            display_name="Ann",
            credits_usd=Decimal("1.5"),
            is_active=True,
            created_at=NOW,
        ),
        {
            "tokens": 1,
            "topped_up": 5,
            "spent": 2,
            "spent_models": 1.5,
            "spent_voices": 0.5,
            "spent_pictures": 0,
            "spent_music": 0,
            "debates": 3,
            "failed": 1,
            "public": 2,
            "likes": 4,
            "votes": 1,
        },
    )
    return {**base, **fields}


def test_users_csv_escapes_formulas() -> None:
    text = accounts.users_csv([_row(display_name="=HYPERLINK(1)"), _row(email="+1@x.co")])
    lines = text.strip().splitlines()
    assert lines[0].split(",") == accounts.CSV_HEADER
    assert "'=HYPERLINK(1)" in lines[1] and ",'+1@x.co," in lines[2]
    assert "1.500000" in lines[1] and ",active," in lines[1]


def test_temporary_password() -> None:
    password = accounts.temporary_password()
    groups = password.split("-")
    assert len(groups) == 4 and all(len(g) == 4 for g in groups)
    assert set(password.replace("-", "")) <= set(accounts.PASSWORD_ALPHABET)
    assert password != accounts.temporary_password()


def test_manual_credit_rules() -> None:
    check_manual_change(Decimal("-2"), "adjustment")
    check_manual_change(Decimal("5"), "refund")
    for amount, kind in (
        (Decimal("0"), "adjustment"),
        (Decimal("0.0000001"), "adjustment"),  # rounds to zero
        (Decimal("1000.01"), "bonus"),
        (Decimal("-1"), "refund"),
        (Decimal("1"), "topup"),
    ):
        with pytest.raises(ValueError):
            check_manual_change(amount, kind)


def test_reason_is_required() -> None:
    with pytest.raises(ValueError):
        ReasonRequest(reason="   ok   ")
    assert ReasonRequest(reason="  fraud  ").reason == "fraud"


def test_response_models_carry_no_secrets() -> None:
    forbidden = {"password", "password_hash", "openrouter_key_enc", "totp_secret_enc", "token"}
    forbidden |= {"recovery_codes_json", "token_hash", "session_epoch"}
    for name in (
        "AdminUserRow",
        "AdminUserProfile",
        "AdminUserCard",
        "AdminLedgerRow",
        "AdminUserDebate",
        "AuditEntryOut",
        "ReactionOwner",
    ):
        model = getattr(admin_schemas, name)
        assert not set(model.model_fields) & forbidden, name


# --- routes (in-memory database) --------------------------------------------------------------


class FakeDB:
    def __init__(self, *users: User) -> None:
        self.users = {u.id: u for u in users}
        self.txs: list[CreditTransaction] = []
        self.added: list[Any] = []
        self.commits = 0
        self.rollbacks = 0

    async def get(self, model: type, key: Any) -> Any:
        return self.users.get(key) if model is User else None

    async def scalar(self, statement: Any) -> Any:
        # The only scalar lookup of the credit route: a transaction by provider_ref.
        sql = _sql(statement)
        return next((tx for tx in self.txs if f"'{tx.provider_ref}'" in sql), None)

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1

    def audit(self) -> list[str]:
        return [row.action for row in self.added if isinstance(row, AdminAuditLog)]


def _fake(*users: User) -> Any:
    return FakeDB(*users)


def _user(**fields: Any) -> User:
    defaults: dict[str, Any] = {
        "id": uuid.uuid4(),
        "email": "ann@example.com",
        "display_name": "Ann",
        "password_hash": "x",
        "credits_usd": Decimal("2"),
        "is_active": True,
        "admin_role": None,
        "session_epoch": 0,
        "created_at": NOW,
    }
    return User(**{**defaults, **fields})


def _ctx(admin: User, sudo: bool = False) -> AdminContext:
    session = AdminSession(
        user_id=str(admin.id),
        csrf="c",
        created_at=time.time(),
        last_seen_at=time.time(),
        ip="",
        user_agent="",
        epoch=0,
        sudo_until=time.time() + 60 if sudo else 0.0,
    )
    return AdminContext(user=admin, session=session, session_hash="h", ip=None, user_agent=None)


def _request() -> Request:
    return Request({"type": "http", "method": "POST", "path": "/", "headers": [], "client": None})


@pytest.fixture
def ledger(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Calls of apply_transaction (which adds the row the next lookup finds)."""
    calls: list[dict[str, Any]] = []

    async def lock_balance(db: FakeDB, user_id: uuid.UUID) -> Decimal | None:
        user = db.users.get(user_id)
        return Decimal(user.credits_usd) if user else None

    async def apply(db: FakeDB, user_id: uuid.UUID, amount: Decimal, kind: str, **kw: Any) -> Any:
        calls.append({"user_id": user_id, "amount": amount, "kind": kind, **kw})
        user = db.users[user_id]
        user.credits_usd = Decimal(user.credits_usd) + amount
        tx = CreditTransaction(
            id=uuid.uuid4(),
            user_id=user_id,
            amount_usd=amount,
            balance_after_usd=user.credits_usd,
            kind=kind,
            provider_ref=kw["provider_ref"],
        )
        db.txs.append(tx)
        await db.commit()
        return tx

    monkeypatch.setattr(routes_users, "lock_balance", lock_balance)
    monkeypatch.setattr(routes_users, "apply_transaction", apply)
    return calls


async def test_credit_change_is_idempotent(ledger: list[dict[str, Any]]) -> None:
    admin, ann = _user(email="boss@example.com", admin_role="admin"), _user()
    db: Any = FakeDB(admin, ann)
    body = CreditChangeRequest(
        amount=Decimal("1.25"), kind="bonus", reason="beta tester", idempotency_key=uuid.uuid4()
    )
    first = await routes_users.change_credits(
        str(ann.id),
        body,
        _request(),
        _ctx(admin),
        db,
    )
    assert (first.balance_before, first.balance_after, first.duplicate) == (2.0, 3.25, False)
    assert ledger[0]["provider_ref"] == f"admin:{body.idempotency_key}"
    assert ledger[0]["description"] == "Bonus credits"
    assert ledger[0]["meta"]["reason"] == "beta tester"
    assert db.audit() == ["credits.changed"]
    again = await routes_users.change_credits(
        str(ann.id),
        body,
        _request(),
        _ctx(admin),
        db,
    )
    assert again.duplicate and again.transaction_id == first.transaction_id
    assert (again.balance_before, again.balance_after) == (2.0, 3.25)
    assert len(ledger) == 1 and db.audit() == ["credits.changed"]


async def test_credit_key_of_another_account_is_refused(ledger: list[dict[str, Any]]) -> None:
    admin, ann, bob = _user(admin_role="admin"), _user(), _user(email="bob@example.com")
    db: Any = FakeDB(admin, ann, bob)
    body = CreditChangeRequest(amount=Decimal("1"), reason="test", idempotency_key=uuid.uuid4())
    await routes_users.change_credits(str(ann.id), body, _request(), _ctx(admin), db)
    with pytest.raises(HTTPException) as caught:
        await routes_users.change_credits(str(bob.id), body, _request(), _ctx(admin), db)
    assert caught.value.status_code == 409


async def test_large_credit_changes_need_sudo(ledger: list[dict[str, Any]]) -> None:
    admin, ann = _user(admin_role="admin"), _user()
    db: Any = FakeDB(admin, ann)
    amount = Decimal(str(settings.ADMIN_SUDO_USD)) + 1
    body = CreditChangeRequest(amount=-amount, reason="chargeback", idempotency_key=uuid.uuid4())
    with pytest.raises(HTTPException) as caught:
        await routes_users.change_credits(str(ann.id), body, _request(), _ctx(admin), db)
    assert caught.value.status_code == 403
    assert (caught.value.headers or {}).get(SUDO_HEADER) == "required"
    assert not ledger and not db.audit()
    done = await routes_users.change_credits(
        str(ann.id),
        body,
        _request(),
        _ctx(admin, sudo=True),
        db,
    )
    assert done.balance_after == float(Decimal("2") - amount)


async def test_bad_amounts_are_refused(ledger: list[dict[str, Any]]) -> None:
    admin, ann = _user(admin_role="admin"), _user()
    body = CreditChangeRequest(
        amount=Decimal("-1"), kind="refund", reason="oops", idempotency_key=uuid.uuid4()
    )
    with pytest.raises(HTTPException) as caught:
        await routes_users.change_credits(
            str(ann.id), body, _request(), _ctx(admin), _fake(admin, ann)
        )
    assert caught.value.status_code == 422 and not ledger


async def test_admin_accounts_and_your_own_are_protected() -> None:
    admin, other_admin = _user(admin_role="admin"), _user(admin_role="moderator")
    db: Any = FakeDB(admin, other_admin)
    body = DisableUserRequest(reason="testing", stop_debates=False)
    for target in (admin, other_admin):
        with pytest.raises(HTTPException) as caught:
            await routes_users.disable_user(str(target.id), body, _request(), _ctx(admin), db)
        assert caught.value.status_code == 409
    with pytest.raises(HTTPException) as caught:
        await routes_users.set_temporary_password(
            str(other_admin.id),
            ReasonRequest(reason="lost it"),
            _request(),
            _ctx(admin, sudo=True),
            db,
        )
    assert caught.value.status_code == 409
    assert other_admin.is_active and not db.audit()


async def test_temporary_password_needs_sudo_and_ends_sessions() -> None:
    admin, ann = _user(admin_role="admin"), _user()
    db: Any = FakeDB(admin, ann)
    reason = ReasonRequest(reason="locked out")
    with pytest.raises(HTTPException) as caught:
        await routes_users.set_temporary_password(str(ann.id), reason, _request(), _ctx(admin), db)
    assert caught.value.status_code == 403
    out = await routes_users.set_temporary_password(
        str(ann.id),
        reason,
        _request(),
        _ctx(admin, sudo=True),
        db,
    )
    from app.core.security import verify_password

    assert verify_password(out.temporary_password, ann.password_hash)
    assert ann.session_epoch == 1 and db.audit() == ["user.temporary_password"]


async def test_sign_out_everywhere_bumps_the_epoch() -> None:
    admin, ann = _user(admin_role="admin"), _user(session_epoch=3)
    db: Any = FakeDB(admin, ann)
    await routes_users.sign_out_everywhere(
        str(ann.id),
        ReasonRequest(reason="stolen laptop"),
        _request(),
        _ctx(admin),
        db,
    )
    assert ann.session_epoch == 4 and db.commits == 1
    (entry,) = [row for row in db.added if isinstance(row, AdminAuditLog)]
    assert (entry.target_type, entry.target_id, entry.reason) == (
        "user",
        str(ann.id),
        "stolen laptop",
    )


# --- the site cookie --------------------------------------------------------------------------


class UserDB:
    def __init__(self, user: User) -> None:
        self.user = user

    async def get(self, model: type, key: Any) -> Any:
        return self.user if key == self.user.id else None


def _users(user: User) -> Any:
    return UserDB(user)


def _site_request(session: dict[str, Any]) -> Request:
    scope: dict[str, Any] = {
        "type": "http",
        "method": "GET",
        "path": "/api/auth/me",
        "headers": [],
        "session": session,
    }
    return Request(scope)


async def test_a_new_epoch_ends_older_cookies() -> None:
    ann = _user()
    session: dict[str, Any] = {}
    auth.login_session(_site_request(session), ann)
    assert session == {"uid": str(ann.id), "epoch": 0}
    assert await auth.get_current_user(_site_request(session), _users(ann)) is ann
    ann.session_epoch = 1
    assert await auth.get_current_user(_site_request(session), _users(ann)) is None
    assert session == {}  # signed out
    # A cookie from before epochs counts as epoch 0.
    fresh = _user()
    legacy = {"uid": str(fresh.id)}
    assert await auth.get_current_user(_site_request(legacy), _users(fresh)) is fresh
    assert not auth.session_epoch_matches({"epoch": "x"}, fresh)


def test_site_cookie_takes_the_host_prefix_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    assert auth.session_cookie_options()["session_cookie"] == "session"
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    options = auth.session_cookie_options()
    assert options["session_cookie"] == "__Host-session" and options["https_only"]


# --- query parameters over HTTP ---------------------------------------------------------------


@pytest.fixture
def users_api(monkeypatch: pytest.MonkeyPatch) -> tuple[Any, list[dict[str, Any]]]:
    """The users router on a bare app: a signed-in admin, list_users captured."""
    import httpx
    from fastapi import FastAPI

    from app.admin.access import read_only_db

    calls: list[dict[str, Any]] = []

    async def list_users(db: Any, filters: UserFilters, **kw: Any) -> tuple[int, list[Any]]:
        calls.append({"filters": filters, **kw})
        return 0, []

    async def no_db() -> Any:
        yield None

    monkeypatch.setattr(accounts, "list_users", list_users)
    app = FastAPI()
    app.include_router(routes_users.router, prefix="/api/admin")
    admin = _user(admin_role="admin")
    app.dependency_overrides[routes_users.read_users] = lambda: _ctx(admin)
    app.dependency_overrides[read_only_db] = no_db
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test"), calls


async def test_list_query_parameters(users_api: tuple[Any, list[dict[str, Any]]]) -> None:
    client, calls = users_api
    async with client:
        ok = await client.get(
            "/api/admin/users",
            params={
                "q": "ann",
                "balance": "negative",
                "paid": "true",
                "sort": "spent",
                "order": "asc",
                "limit": 10,
                "offset": 20,
                "active_days": 7,
            },
        )
        assert ok.status_code == 200, ok.text
        assert ok.json() == {"total": 0, "limit": 10, "offset": 20, "rows": []}
        call = calls[-1]
        assert (call["sort"], call["descending"], call["limit"], call["offset"]) == (
            "spent",
            False,
            10,
            20,
        )
        filters: UserFilters = call["filters"]
        assert (filters.q, filters.balance, filters.paid, filters.active_days) == (
            "ann",
            "negative",
            True,
            7,
        )
        assert (await client.get("/api/admin/users")).status_code == 200
        assert calls[-1]["sort"] == "created" and calls[-1]["descending"]
        for bad in ({"balance": "zero"}, {"limit": 500}, {"sort": "password"}, {"order": "up"}):
            assert (await client.get("/api/admin/users", params=bad)).status_code == 422, bad
