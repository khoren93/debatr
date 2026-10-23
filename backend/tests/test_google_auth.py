"""Sign-in with Google (services/google_auth, routes_google). Pure: Google is an
httpx.MockTransport signing with a key made here, Redis and the database are fakes."""

import base64
import hashlib
import json
import time
import uuid
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from starlette.requests import Request

from app.api import routes_google
from app.core.config import settings
from app.models.models import User, UserIdentity
from app.services import google_auth
from app.services.google_auth import Flow, GoogleAccount, GoogleError, UnknownKeyError

CLIENT = "client-123.apps.googleusercontent.com"
NOW = time.time()
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _jwk(kid: str = "k1") -> dict[str, Any]:
    numbers = KEY.public_key().public_numbers()
    return {
        "kty": "RSA",
        "alg": "RS256",
        "kid": kid,
        "n": _b64(numbers.n.to_bytes(256, "big")),
        "e": _b64(numbers.e.to_bytes(3, "big")),
    }


def _token(header: dict[str, Any] | None = None, **claims: Any) -> str:
    head = {"alg": "RS256", "kid": "k1", "typ": "JWT", **(header or {})}
    body = {
        "iss": "https://accounts.google.com",
        "aud": CLIENT,
        "sub": "1098765",
        "email": "Jane@Gmail.com",
        "email_verified": True,
        "name": "Jane Doe",
        "nonce": "n0nce",
        "iat": int(NOW) - 10,
        "exp": int(NOW) + 3600,
        **claims,
    }
    signing = f"{_b64(json.dumps(head).encode())}.{_b64(json.dumps(body).encode())}"
    signature = KEY.sign(signing.encode(), padding.PKCS1v15(), hashes.SHA256())
    return f"{signing}.{_b64(signature)}"


def _text(body: bytes | memoryview) -> str:
    return bytes(body).decode()


def _verify(token: str, keys: list[dict[str, Any]] | None = None) -> GoogleAccount:
    return google_auth.verify_id_token(
        token, keys if keys is not None else [_jwk()], client_id=CLIENT, nonce="n0nce", now=NOW
    )


# --- the ID token -----------------------------------------------------------------------------


def test_a_good_token_names_the_account() -> None:
    account = _verify(_token())
    assert account == GoogleAccount("1098765", "jane@gmail.com", True, "Jane Doe")
    assert _verify(_token(email_verified="true")).email_verified
    assert not _verify(_token(email_verified=False)).email_verified
    assert _verify(_token(iss="accounts.google.com")).subject == "1098765"


@pytest.mark.parametrize(
    "claims",
    [
        {"aud": "another-client"},
        {"aud": [CLIENT, "another-client"]},
        {"iss": "https://evil.example"},
        {"exp": int(NOW) - 3600},
        {"iat": int(NOW) + 3600},
        {"nonce": "replayed"},
        {"sub": ""},
        {"email": None},
    ],
)
def test_bad_claims_are_refused(claims: dict[str, Any]) -> None:
    with pytest.raises(GoogleError):
        _verify(_token(**claims))


def test_bad_signatures_are_refused() -> None:
    head, body, signature = _token().split(".")
    forged = json.loads(base64.urlsafe_b64decode(body + "=="))
    forged["sub"] = "someone-else"
    with pytest.raises(GoogleError, match="bad signature"):
        _verify(f"{head}.{_b64(json.dumps(forged).encode())}.{signature}")
    with pytest.raises(GoogleError, match="algorithm"):
        _verify(_token(header={"alg": "none"}))
    with pytest.raises(UnknownKeyError):
        _verify(_token(header={"kid": "k2"}))
    with pytest.raises(GoogleError, match="unreadable"):
        _verify("not.a-token")


async def test_exchange_checks_the_token_and_refetches_rotated_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", CLIENT)
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", "secret")
    monkeypatch.setattr(settings, "SITE_URL", "https://site.example")
    monkeypatch.setattr(google_auth, "_keys", {"at": time.monotonic(), "keys": [_jwk("old")]})
    posted: list[dict[str, list[str]]] = []

    def google(request: httpx.Request) -> httpx.Response:
        if request.url == google_auth.TOKEN_URL:
            posted.append(parse_qs(request.content.decode()))
            return httpx.Response(200, json={"id_token": _token(), "access_token": "x"})
        assert request.url == google_auth.JWKS_URL
        return httpx.Response(200, json={"keys": [_jwk("k1")]})

    flow = Flow(mode="login", verifier="v" * 64, nonce="n0nce")
    account = await google_auth.exchange("code-1", flow, transport=httpx.MockTransport(google))
    assert account.subject == "1098765"
    (form,) = posted
    assert form["code_verifier"] == ["v" * 64] and form["client_secret"] == ["secret"]
    assert form["redirect_uri"] == ["https://site.example/api/auth/google/callback"]

    def refused(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_grant"})

    with pytest.raises(GoogleError, match="invalid_grant"):
        await google_auth.exchange("used", flow, transport=httpx.MockTransport(refused))


# --- the flow ---------------------------------------------------------------------------------


class FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.data[key] = value

    async def getdel(self, key: str) -> str | None:
        return self.data.pop(key, None)


@pytest.fixture
def redis(monkeypatch: pytest.MonkeyPatch) -> FakeRedis:
    fake = FakeRedis()
    monkeypatch.setattr(google_auth, "get_async_redis", lambda: fake)
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", CLIENT)
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", "secret")
    monkeypatch.setattr(settings, "SITE_URL", "https://site.example")
    return fake


async def test_a_flow_is_kept_once_under_the_hash_of_its_state(redis: FakeRedis) -> None:
    user = User(id=uuid.uuid4(), session_epoch=3)
    state, url = await google_auth.begin("link", next_path="/account?tab=security", user=user)
    query = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
    assert url.startswith(google_auth.AUTH_URL)
    assert query["state"] == state and query["client_id"] == CLIENT
    assert query["scope"] == "openid email profile" and query["code_challenge_method"] == "S256"
    assert query["redirect_uri"] == "https://site.example/api/auth/google/callback"
    (key,) = redis.data
    assert state not in key  # only its hash
    flow = await google_auth.take(state)
    assert flow is not None and (flow.mode, flow.uid, flow.epoch) == ("link", str(user.id), 3)
    expected = _b64(hashlib.sha256(flow.verifier.encode()).digest())
    assert query["code_challenge"] == expected and query["nonce"] == flow.nonce
    assert await google_auth.take(state) is None  # used up


# --- what an account means (pure) -------------------------------------------------------------

ACCOUNT = GoogleAccount("sub-1", "jane@gmail.com", True, "Jane")


def _account_user(*, active: bool = True, confirmed: bool = True, epoch: int = 0) -> User:
    return User(
        id=uuid.uuid4(),
        email="jane@gmail.com",
        is_active=active,
        session_epoch=epoch,
        email_verified_at=datetime.now(UTC) if confirmed else None,
    )


def test_sign_in_decisions() -> None:
    decide = google_auth.decide
    tied = _account_user()
    assert decide(ACCOUNT, tied=tied, same_email=None, registration_open=False).action == "sign_in"
    off = decide(ACCOUNT, tied=_account_user(active=False), same_email=None, registration_open=True)
    assert off.error == "disabled"
    unverified = GoogleAccount("sub-1", "jane@gmail.com", False, "Jane")
    assert decide(unverified, tied=None, same_email=None, registration_open=True).error == (
        "unverified"
    )
    joined = decide(ACCOUNT, tied=None, same_email=_account_user(), registration_open=True)
    assert joined.action == "join"
    # Someone may have registered the owner's address without being its owner.
    pending = _account_user(confirmed=False)
    assert decide(ACCOUNT, tied=None, same_email=pending, registration_open=True).error == "exists"
    assert decide(ACCOUNT, tied=None, same_email=None, registration_open=False).error == "closed"
    assert decide(ACCOUNT, tied=None, same_email=None, registration_open=True).action == "create"


def test_link_decisions() -> None:
    user = _account_user(epoch=2)
    flow = Flow(mode="link", verifier="v", nonce="n", uid=str(user.id), epoch=2)
    link = google_auth.decide_link
    assert link(flow, user=user, tied=None, current=None).action == "join"
    assert link(flow, user=user, tied=user, current=None).action == "linked"
    assert link(flow, user=user, tied=_account_user(), current=None).error == "taken"
    other = UserIdentity(user_id=user.id, provider="google", subject="sub-0")
    assert link(flow, user=user, tied=None, current=other).error == "one_google"
    later = _account_user(epoch=3)  # the password changed since the flow started
    assert link(flow, user=later, tied=None, current=None).error == "expired"
    assert link(flow, user=None, tied=None, current=None).error == "expired"


# --- the routes -------------------------------------------------------------------------------


def _request(path: str, cookies: dict[str, str] | None = None) -> Request:
    cookie = "; ".join(f"{k}={v}" for k, v in (cookies or {}).items())
    headers = [(b"cookie", cookie.encode())] if cookie else []
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": headers,
        "session": {},
        "scheme": "http",
        "server": ("localhost", 80),
        "query_string": b"",
    }
    return Request(scope)


def test_landing_pages_stay_on_the_site() -> None:
    assert routes_google.safe_next("/create?draft=1") == "/create?draft=1"
    for bad in ("//evil.example", "/\\evil.example", "https://evil.example", "/login", "/a\nb"):
        assert routes_google.safe_next(bad) is None
    assert routes_google.failure_target("closed", "login", "/create") == (
        "/login?error=google_closed&next=%2Fcreate"
    )
    assert routes_google.failure_target("taken", "link") == "/account?tab=security&google=taken"


def test_the_hop_page_moves_on_by_itself() -> None:
    page = _text(routes_google.hop('/x?a=1&b="</script>').body)
    assert 'location.replace("/x?a=1&b=\\"\\u003c/script>")' in page
    assert 'content="0;url=/x?a=1&amp;b=&quot;&lt;/script&gt;"' in page
    assert "</script></body>" in page and page.count("</script>") == 1


async def test_start_sets_a_lax_state_cookie(redis: FakeRedis) -> None:
    response = await routes_google.google_start(_request("/api/auth/google/start"), next="/create")
    assert response.status_code == 302
    assert response.headers["location"].startswith(google_auth.AUTH_URL)
    cookie = response.headers["set-cookie"]
    assert cookie.startswith("google_state=") and "SameSite=lax" in cookie
    assert "Path=/api/auth/google" in cookie and "HttpOnly" in cookie
    state = cookie.split(";")[0].split("=", 1)[1]
    flow = await google_auth.take(state)
    assert flow is not None and flow.next == "/create" and flow.mode == "login"


async def test_start_without_google_set_up(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "")
    response = await routes_google.google_start(_request("/api/auth/google/start"))
    assert response.headers["location"] == "/login?error=google_off"


async def test_callbacks_need_the_browser_that_started_them(redis: FakeRedis) -> None:
    state, _ = await google_auth.begin("login", next_path="/create")
    alien = await routes_google.google_callback(
        _request("/cb", {"google_state": "another"}),
        code="c",
        state=state,
        db=None,  # type: ignore[arg-type]
    )
    assert "/login?error=google_expired" in _text(alien.body)
    assert redis.data  # a foreign callback does not use the flow up
    cancelled = await routes_google.google_callback(
        _request("/cb", {"google_state": state}),
        state=state,
        error="access_denied",
        db=None,  # type: ignore[arg-type]
    )
    page = _text(cancelled.body)
    assert "/login?error=google_cancelled&amp;next=%2Fcreate" in page
    assert 'google_state=""' in cancelled.headers["set-cookie"]  # the cookie goes


class FakeDB:
    """What a first sign-in asks the database: nobody tied, nobody with the address."""

    def __init__(self) -> None:
        self.added: list[Any] = []
        self.commits = 0

    async def scalar(self, statement: Any) -> Any:
        return None

    async def get(self, model: type, key: Any) -> Any:
        return None

    def add(self, obj: Any) -> None:
        if isinstance(obj, User):
            obj.id = uuid.uuid4()
        self.added.append(obj)

    async def flush(self) -> None: ...

    async def commit(self) -> None:
        self.commits += 1


async def test_a_first_sign_in_makes_a_confirmed_account(
    redis: FakeRedis, monkeypatch: pytest.MonkeyPatch, levers: dict, raised_alerts: list
) -> None:
    levers["signup_bonus_usd"] = 0

    async def exchange(code: str, flow: Flow) -> GoogleAccount:
        assert code == "c"
        return GoogleAccount("sub-9", "new@gmail.com", True, "Debatr")  # a reserved name

    monkeypatch.setattr(google_auth, "exchange", exchange)
    state, _ = await google_auth.begin("login", next_path="/create")
    request = _request("/cb", {"google_state": state})
    db = FakeDB()
    page = await routes_google.google_callback(request, code="c", state=state, db=db)  # type: ignore[arg-type]
    user, identity = db.added
    assert isinstance(user, User) and isinstance(identity, UserIdentity)
    assert user.email == "new@gmail.com" and user.password_hash is None
    assert user.email_verified_at is not None and user.display_name == "New"
    assert (identity.provider, identity.subject, identity.user_id) == ("google", "sub-9", user.id)
    assert request.session["uid"] == str(user.id) and db.commits == 1
    assert 'location.replace("/create")' in _text(page.body)
    assert [a.title for a in raised_alerts] == ["New account: new@gmail.com"]
    assert "via Google" in raised_alerts[0].detail
