"""API tokens: format, Bearer auth, spending limits, private-by-default and the device flow
helpers. Pure: the database is a small fake."""

import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from starlette.requests import Request

from app.api.routes_debates import _billing
from app.core.auth import (
    bearer_token,
    get_current_user,
    request_api_token,
    require_session_user,
)
from app.core.security import (
    API_TOKEN_PREFIX,
    hash_api_token,
    looks_like_api_token,
    mask_api_token,
    new_api_token,
)
from app.models.models import ApiToken, User, utcnow
from app.schemas.auth import CreateApiTokenRequest
from app.schemas.schemas import DebateConfig, EstimateOut
from app.services.api_tokens import (
    USER_CODE_ALPHABET,
    DeviceRequest,
    is_expired,
    new_user_code,
    normalize_user_code,
    pending_estimate,
    remaining_budget,
    token_out,
    with_token_defaults,
)
from app.services.credits import Prices


def _request(authorization: str | None = None, session: dict[str, Any] | None = None) -> Request:
    headers = [(b"authorization", authorization.encode())] if authorization is not None else []
    scope: dict[str, Any] = {
        "type": "http",
        "method": "GET",
        "path": "/api/auth/me",
        "query_string": b"",
        "headers": headers,
    }
    if session is not None:
        scope["session"] = session
    return Request(scope)


def _user(active: bool = True) -> User:
    return User(id=uuid.uuid4(), email="a@b.co", display_name="A", is_active=active)


def _token(user: User, **fields: Any) -> ApiToken:
    defaults: dict[str, Any] = {
        "id": uuid.uuid4(),
        "user_id": user.id,
        "name": "laptop",
        "token_hash": "x" * 64,
        "token_last4": "a1b2",
        "created_at": utcnow(),
    }
    return ApiToken(**{**defaults, **fields})


class _Row:
    def __init__(self, *items: Any) -> None:
        self._items = items

    def tuple(self) -> tuple[Any, ...]:
        return self._items


class _Result:
    def __init__(self, row: _Row | None) -> None:
        self._row = row

    def first(self) -> _Row | None:
        return self._row


class FakeDb:
    """Answers the token lookup with a fixed row and counts commits."""

    def __init__(self, row: _Row | None = None) -> None:
        self.row = row
        self.commits = 0
        self.statements: list[Any] = []

    async def execute(self, stmt: Any) -> _Result:
        self.statements.append(stmt)
        return _Result(self.row)

    async def commit(self) -> None:
        self.commits += 1


# --- token format -------------------------------------------------------------------


def test_new_tokens_are_prefixed_random_and_recognised():
    a, b = new_api_token(), new_api_token()
    assert a != b
    assert a.startswith(API_TOKEN_PREFIX)
    assert looks_like_api_token(a)
    assert len(hash_api_token(a)) == 64
    assert hash_api_token(a) == hash_api_token(a) != hash_api_token(b)


@pytest.mark.parametrize(
    "value",
    ["", "debatr_", "debatr_short", "sk-or-v1-" + "a" * 50, "debatr_" + "é" * 43, "x" * 60],
)
def test_looks_like_api_token_rejects_other_values(value: str):
    assert not looks_like_api_token(value)


def test_mask_api_token():
    assert mask_api_token("a1b2") == "debatr_…a1b2"


# --- Bearer header ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (None, None),
        ("Bearer abc", "abc"),
        ("bearer   abc  ", "abc"),
        ("Basic dXNlcjpwYXNz", None),
        ("Bearer", ""),
    ],
)
def test_bearer_token(header: str | None, expected: str | None):
    assert bearer_token(_request(header)) == expected


async def test_valid_token_signs_in_and_touches_last_used():
    user = _user()
    token = _token(user)
    db = FakeDb(_Row(token, user))
    request = _request(f"Bearer {new_api_token()}")
    assert await get_current_user(request, db) is user  # type: ignore[arg-type]
    assert request_api_token(request) is token
    assert token.last_used_at is not None
    assert db.commits == 1


async def test_recently_used_token_is_not_written_again():
    user = _user()
    token = _token(user, last_used_at=utcnow() - timedelta(seconds=5))
    db = FakeDb(_Row(token, user))
    await get_current_user(_request(f"Bearer {new_api_token()}"), db)  # type: ignore[arg-type]
    assert db.commits == 0


@pytest.mark.parametrize(
    ("header", "row_factory", "detail"),
    [
        ("Bearer nope", None, "Invalid API token"),
        ("Bearer ", None, "Invalid API token"),
        ("Bearer {token}", lambda u: None, "Invalid or revoked API token"),
        (
            "Bearer {token}",
            lambda u: _Row(_token(u, expires_at=utcnow() - timedelta(minutes=1)), u),
            "This API token has expired",
        ),
    ],
)
async def test_bad_tokens_are_401_not_anonymous(header, row_factory, detail):
    user = _user()
    db = FakeDb(row_factory(user) if row_factory else None)
    request = _request(header.format(token=new_api_token()))
    with pytest.raises(HTTPException) as err:
        await get_current_user(request, db)  # type: ignore[arg-type]
    assert err.value.status_code == 401
    assert err.value.detail == detail
    assert (err.value.headers or {}).get("WWW-Authenticate", "").startswith("Bearer")
    assert request_api_token(request) is None


async def test_token_of_disabled_account_is_rejected():
    user = _user(active=False)
    db = FakeDb(_Row(_token(user), user))
    with pytest.raises(HTTPException) as err:
        await get_current_user(_request(f"Bearer {new_api_token()}"), db)  # type: ignore[arg-type]
    assert err.value.status_code == 401


async def test_without_bearer_the_session_cookie_is_used():
    db = FakeDb()
    assert await get_current_user(_request(session={}), db) is None  # type: ignore[arg-type]
    assert db.statements == []


async def test_account_management_needs_the_browser_session():
    user = _user()
    request = _request(session={})
    assert await require_session_user(request, user) is user
    request.state.api_token = _token(user)
    with pytest.raises(HTTPException) as err:
        await require_session_user(request, user)
    assert err.value.status_code == 403


# --- spending limit ---------------------------------------------------------------------


def test_remaining_budget():
    assert remaining_budget(None, Decimal("3"), Decimal("1")) is None
    assert remaining_budget(Decimal("5"), Decimal("1.2"), Decimal("0.5")) == Decimal("3.3")
    assert remaining_budget(Decimal("1"), Decimal("2"), Decimal("0")) == Decimal("0")
    assert remaining_budget(Decimal("0"), Decimal("0"), Decimal("0")) == Decimal("0")


def test_pending_estimate_counts_runs_and_their_media_builds():
    billing = {"billing": {"estimate_usd": 0.4, "media_estimate_usd": 0.1}}
    assert pending_estimate("running", "none", billing) == Decimal("0.4")
    assert pending_estimate("queued", "none", billing) == Decimal("0.4")
    assert pending_estimate("completed", "running", billing) == Decimal("0.1")
    assert pending_estimate("completed", "ready", billing) == Decimal("0")
    assert pending_estimate("running", "none", {}) == Decimal("0")


def _estimate(**fields: Any) -> EstimateOut:
    base: dict[str, Any] = {
        "turns": 7,
        "words": 900,
        "tokens_in": 1,
        "tokens_out": 1,
        "llm_cost_usd": 0.1,
        "tts_chars": 5000,
        "tts_cost_usd": 0.75,
        "images_cost_usd": 0.05,
        "credits_cost_usd": 0.93,
        "duration_ms": 1,
        "render_ms": 1,
    }
    return EstimateOut(**{**base, **fields})


def test_billing_stores_the_estimate_its_media_part_and_the_prices():
    prices = Prices(markup=3.0, min_charge=0.05, voices_per_1k=0.25)
    assert _billing(False, None) == {"own_key": False}
    billing = _billing(True, _estimate(), prices)
    assert billing["own_key"] is True
    assert billing["estimate_usd"] == 0.93
    assert billing["media_estimate_usd"] == pytest.approx(0.75 + 0.05 * 3.0)
    assert billing["prices"] == {"markup": 3.0, "min_charge": 0.05, "voices_per_1k": 0.25}
    own_tts = _billing(False, _estimate(own_tts_key=True), prices)
    assert own_tts["media_estimate_usd"] == pytest.approx(0.05 * 3.0)


def test_token_out_and_expiry():
    user = _user()
    token = _token(user, spend_limit_usd=Decimal("5"))
    out = token_out(token, Decimal("1.25"))
    assert out.token_hint == "debatr_…a1b2"
    assert out.spend_limit_usd == 5.0
    assert out.spent_usd == 1.25
    assert not out.expired
    assert is_expired(_token(user, expires_at=utcnow() - timedelta(seconds=1)))
    assert not is_expired(_token(user, expires_at=utcnow() + timedelta(days=1)))


# --- private by default ----------------------------------------------------------------


def _config(**extra: Any) -> DebateConfig:
    return DebateConfig.model_validate(
        {
            "topic": "Cats or dogs?",
            "participants": [{"role": "debater", "model_id": "m", "display_name": "A"}],
            **extra,
        }
    )


def test_token_debates_are_private_unless_asked():
    assert _config().auto_publish is True  # browsers keep the wizard default
    assert with_token_defaults(_config()).auto_publish is False
    assert with_token_defaults(_config(auto_publish=True)).auto_publish is True
    assert with_token_defaults(_config(auto_publish=False)).auto_publish is False


# --- requests and device codes -----------------------------------------------------------


def test_create_token_request_validation():
    assert CreateApiTokenRequest(name="  my   laptop ").name == "my laptop"
    with pytest.raises(ValidationError):
        CreateApiTokenRequest(name="   ")
    with pytest.raises(ValidationError):
        CreateApiTokenRequest(name="x", spend_limit_usd=-1)
    with pytest.raises(ValidationError):
        CreateApiTokenRequest(name="x", expires_in_days=0)
    assert CreateApiTokenRequest(name="x", spend_limit_usd=0).spend_limit_usd == 0


def test_user_codes():
    code = new_user_code()
    assert len(code) == 9 and code[4] == "-"
    assert all(ch in USER_CODE_ALPHABET for ch in code.replace("-", ""))
    assert normalize_user_code(code.lower().replace("-", " ")) == code
    assert normalize_user_code("WDJBMJHT") == "WDJB-MJHT"
    assert normalize_user_code(" wdjb-mjht ") == "WDJB-MJHT"
    assert normalize_user_code("WDJB-MJH") is None  # too short
    assert normalize_user_code("ABCD-EFGH") is None  # vowels are never used
    assert normalize_user_code("../../etc") is None


def test_device_request_roundtrip():
    request = DeviceRequest(
        user_code="WDJB-MJHT",
        client_name="Debatr CLI on mac",
        status="pending",
        created_at=utcnow(),
    )
    loaded = DeviceRequest.load(request.dump())
    assert loaded == request
    assert loaded is not None and loaded.expires_at > loaded.created_at
    assert DeviceRequest.load(request.dump().encode()) == request
    assert DeviceRequest.load(None) is None
    assert DeviceRequest.load("{not json") is None
    assert DeviceRequest.load('{"user_code": "X"}') is None
