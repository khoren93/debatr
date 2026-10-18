"""Passkeys of the admin console, end to end through the routes with a software authenticator
(a P-256 key that signs like a real one): adding one, signing in with it, sudo, and the
answers that must not pass (another origin, a wrong signature, a challenge used twice).

Pure: the database and Redis are the console tests' fakes.
"""

import base64
import hashlib
import json
import struct
import uuid
from typing import Any

import cbor2
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import Response

from app.admin.access import AdminContext, ticket_cookie_name
from app.api.admin import routes_auth, routes_passkeys
from app.models.models import AdminAuditLog, User
from app.schemas.admin import PasskeyAddRequest, PasskeyAnswer
from app.services.admin import passkeys, sessions
from app.services.admin.sessions import AdminSession, SignInTicket
from tests.test_admin_console import FakeDB, FakeRedis, _enrolled

ORIGIN = "http://localhost:5173"
RP_ID = "localhost"


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class Authenticator:
    """A passkey on a "device": creates the credential and signs sign-in challenges."""

    def __init__(self, origin: str = ORIGIN, rp_id: str = RP_ID) -> None:
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.credential_id = uuid.uuid4().bytes + uuid.uuid4().bytes
        self.origin = origin
        self.rp_id = rp_id
        self.count = 0

    def _client_data(self, kind: str, challenge: str) -> bytes:
        return json.dumps(
            {"type": kind, "challenge": challenge, "origin": self.origin, "crossOrigin": False}
        ).encode()

    def _rp_hash(self) -> bytes:
        return hashlib.sha256(self.rp_id.encode()).digest()

    def create(self, options: dict[str, Any]) -> dict[str, Any]:
        numbers = self.key.public_key().public_numbers()
        cose = cbor2.dumps(
            {
                1: 2,
                3: -7,
                -1: 1,
                -2: numbers.x.to_bytes(32, "big"),
                -3: numbers.y.to_bytes(32, "big"),
            }
        )
        attested = (
            bytes(16) + struct.pack(">H", len(self.credential_id)) + self.credential_id + cose
        )
        auth_data = self._rp_hash() + bytes([0x45]) + struct.pack(">I", 0) + attested  # UP UV AT
        attestation = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth_data})
        return {
            "id": b64(self.credential_id),
            "rawId": b64(self.credential_id),
            "type": "public-key",
            "clientExtensionResults": {},
            "response": {
                "clientDataJSON": b64(self._client_data("webauthn.create", options["challenge"])),
                "attestationObject": b64(attestation),
                "transports": ["internal", "made-up"],
            },
        }

    def sign(self, options: dict[str, Any], *, tamper: bool = False) -> dict[str, Any]:
        self.count += 1
        auth_data = self._rp_hash() + bytes([0x05]) + struct.pack(">I", self.count)  # UP UV
        client_data = self._client_data("webauthn.get", options["challenge"])
        signed = auth_data + hashlib.sha256(client_data).digest()
        signature = self.key.sign(signed, ec.ECDSA(hashes.SHA256()))
        if tamper:
            signature = self.key.sign(b"something else", ec.ECDSA(hashes.SHA256()))
        return {
            "id": b64(self.credential_id),
            "rawId": b64(self.credential_id),
            "type": "public-key",
            "clientExtensionResults": {},
            "response": {
                "clientDataJSON": b64(client_data),
                "authenticatorData": b64(auth_data),
                "signature": b64(signature),
                "userHandle": None,
            },
        }


class Redis(FakeRedis):
    async def getdel(self, key: str) -> str | None:
        return self.data.pop(key, None)


@pytest.fixture
def redis(monkeypatch: pytest.MonkeyPatch) -> Redis:
    fake = Redis()
    for module in (routes_auth, routes_passkeys):
        monkeypatch.setattr(module, "get_async_redis", lambda: fake)
    return fake


def _request(cookies: dict[str, str] | None = None, origin: str = ORIGIN) -> Request:
    headers = [
        (b"origin", origin.encode()),
        (b"host", b"localhost:8000"),
        (b"user-agent", b"pytest"),
    ]
    if cookies:
        headers.append((b"cookie", "; ".join(f"{k}={v}" for k, v in cookies.items()).encode()))
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/admin/auth/passkey",
            "query_string": b"",
            "headers": headers,
            "client": ("203.0.113.9", 4000),
            "scheme": "http",
            "server": ("localhost", 8000),
        }
    )


def _ctx(user: User, sudo: bool = True) -> AdminContext:
    session = AdminSession(
        user_id=str(user.id),
        csrf="c",
        created_at=0,
        last_seen_at=0,
        ip="",
        user_agent="",
        epoch=user.session_epoch,
        sudo_until=1e12 if sudo else 0.0,
    )
    return AdminContext(user=user, session=session, session_hash="sess", ip=None, user_agent=None)


def _actions(db: FakeDB) -> list[str]:
    return [row.action for row in db.added if isinstance(row, AdminAuditLog)]


async def _add(db: FakeDB, user: User, device: Authenticator, name: str = "MacBook") -> Any:
    ctx = _ctx(user)
    options = (await routes_passkeys.add_options(_request(), ctx, db)).options  # type: ignore[arg-type]
    body = PasskeyAddRequest(name=name, credential=device.create(options))
    return await routes_passkeys.add_passkey(body, _request(), ctx, db)  # type: ignore[arg-type]


async def _ticket(redis: Redis, user: User) -> dict[str, str]:
    token = await sessions.create_ticket(
        redis,  # type: ignore[arg-type]
        SignInTicket(user_id=str(user.id), epoch=user.session_epoch, ip="", created_at=0),
    )
    return {ticket_cookie_name(_request()): token}


# --- tests ------------------------------------------------------------------------------------


async def test_relying_party(monkeypatch: pytest.MonkeyPatch) -> None:
    assert passkeys.relying_party(_request()) == ("localhost", ORIGIN)
    from app.core.config import settings

    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "ADMIN_HOST", "admin.example.com")
    # Production trusts its configuration, never the request.
    assert passkeys.relying_party(_request(origin="https://evil.example")) == (
        "admin.example.com",
        "https://admin.example.com",
    )


async def test_add_a_passkey_then_sign_in_with_it(
    redis: Redis, monkeypatch: pytest.MonkeyPatch, raised_alerts: list
) -> None:
    monkeypatch.setattr("time.time", lambda: 10.0)  # inside the ticket's lifetime
    user = _enrolled("JBSWY3DPEHPK3PXP")
    db = FakeDB(user)
    device = Authenticator()
    added = await _add(db, user, device)
    assert added.name == "MacBook" and added.transports == ["internal"]
    (row,) = db.passkeys
    assert row.credential_id == b64(device.credential_id) and row.sign_count == 0
    assert "auth.passkey_added" in _actions(db)

    cookies = await _ticket(redis, user)
    options = (await routes_passkeys.sign_in_options(_request(cookies), db)).options  # type: ignore[arg-type]
    assert options["rpId"] == RP_ID and options["userVerification"] == "required"
    assert options["allowCredentials"][0]["id"] == b64(device.credential_id)
    response = Response()
    out = await routes_passkeys.sign_in_with_passkey(
        PasskeyAnswer(credential=device.sign(options)),
        _request(cookies),
        response,
        db,  # type: ignore[arg-type]
    )
    assert out.me.user.email == user.email and out.me.passkeys == 1
    assert row.sign_count == 1 and row.last_used_at is not None
    assert "auth.signed_in" in _actions(db)
    signed_in = next(
        r for r in db.added if isinstance(r, AdminAuditLog) and r.action == "auth.signed_in"
    )
    assert signed_in.after_json == {"second_factor": "the passkey “MacBook”"}
    assert raised_alerts[-1].kind == "signin" and "passkey" in raised_alerts[-1].detail


async def test_the_login_offers_the_passkey(redis: Redis) -> None:
    user = _enrolled("JBSWY3DPEHPK3PXP")
    db = FakeDB(user)
    assert await routes_auth.passkey_count(db, user) == 0  # type: ignore[arg-type]
    await _add(db, user, Authenticator())
    assert await routes_auth.passkey_count(db, user) == 1  # type: ignore[arg-type]


async def test_bad_answers_do_not_pass(redis: Redis, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("time.time", lambda: 10.0)
    user = _enrolled("JBSWY3DPEHPK3PXP")
    db = FakeDB(user)
    device = Authenticator()
    await _add(db, user, device)
    cookies = await _ticket(redis, user)

    async def attempt(credential: dict[str, Any] | None = None, *, tamper: bool = False) -> int:
        options = (await routes_passkeys.sign_in_options(_request(cookies), db)).options  # type: ignore[arg-type]
        answer = credential or device.sign(options, tamper=tamper)
        with pytest.raises(HTTPException) as caught:
            await routes_passkeys.sign_in_with_passkey(
                PasskeyAnswer(credential=answer),
                _request(cookies),
                Response(),
                db,  # type: ignore[arg-type]
            )
        return caught.value.status_code

    assert await attempt(tamper=True) == 400
    phishing = Authenticator(origin="https://debatr-login.example")
    phishing.key, phishing.credential_id = device.key, device.credential_id
    options = (await routes_passkeys.sign_in_options(_request(cookies), db)).options  # type: ignore[arg-type]
    assert await attempt(phishing.sign(options)) == 400
    stranger = Authenticator()
    options = (await routes_passkeys.sign_in_options(_request(cookies), db)).options  # type: ignore[arg-type]
    assert await attempt(stranger.sign(options)) == 400
    assert _actions(db).count("auth.passkey_failed") == 3
    failures = [r for r in db.added if isinstance(r, AdminAuditLog) and not r.ok]
    assert "not registered" in (failures[-1].reason or "")
    assert await sessions.code_failures(redis, str(user.id)) == 3  # type: ignore[arg-type]


async def test_a_challenge_works_once(redis: Redis, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("time.time", lambda: 10.0)
    user = _enrolled("JBSWY3DPEHPK3PXP")
    db = FakeDB(user)
    device = Authenticator()
    await _add(db, user, device)
    cookies = await _ticket(redis, user)
    options = (await routes_passkeys.sign_in_options(_request(cookies), db)).options  # type: ignore[arg-type]
    answer = device.sign(options, tamper=True)
    with pytest.raises(HTTPException):
        await routes_passkeys.sign_in_with_passkey(
            PasskeyAnswer(credential=answer),
            _request(cookies),
            Response(),
            db,  # type: ignore[arg-type]
        )
    with pytest.raises(HTTPException) as caught:  # the same challenge again, even signed well
        await routes_passkeys.sign_in_with_passkey(
            PasskeyAnswer(credential=device.sign(options)),
            _request(cookies),
            Response(),
            db,  # type: ignore[arg-type]
        )
    assert caught.value.status_code == 409


async def test_no_passkey_no_options(redis: Redis, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("time.time", lambda: 10.0)
    user = _enrolled("JBSWY3DPEHPK3PXP")
    db = FakeDB(user)
    cookies = await _ticket(redis, user)
    with pytest.raises(HTTPException) as caught:
        await routes_passkeys.sign_in_options(_request(cookies), db)  # type: ignore[arg-type]
    assert caught.value.status_code == 409


async def test_the_same_passkey_twice_is_refused(redis: Redis) -> None:
    user = _enrolled("JBSWY3DPEHPK3PXP")
    db = FakeDB(user)
    device = Authenticator()
    await _add(db, user, device)
    with pytest.raises(HTTPException) as caught:
        await _add(db, user, device, name="Again")
    assert caught.value.status_code == 409 and len(db.passkeys) == 1


async def test_sudo_with_a_passkey(redis: Redis) -> None:
    user = _enrolled("JBSWY3DPEHPK3PXP")
    db = FakeDB(user)
    device = Authenticator()
    await _add(db, user, device)
    ctx = _ctx(user, sudo=False)
    options = (await routes_passkeys.sudo_options(_request(), ctx, db)).options  # type: ignore[arg-type]
    out = await routes_passkeys.sudo_with_passkey(
        PasskeyAnswer(credential=device.sign(options)),
        _request(),
        ctx,
        db,  # type: ignore[arg-type]
    )
    assert ctx.session.sudo_until > 0 and out.sudo_until
    assert _actions(db)[-1] == "auth.sudo"


async def test_remove_only_your_own(redis: Redis) -> None:
    user, other = _enrolled("JBSWY3DPEHPK3PXP"), _enrolled("JBSWY3DPEHPK3PXP")
    db = FakeDB(user, other)
    await _add(db, user, Authenticator())
    (row,) = db.passkeys
    with pytest.raises(HTTPException) as caught:
        await routes_passkeys.remove_passkey(str(row.id), _request(), _ctx(other), db)  # type: ignore[arg-type]
    assert caught.value.status_code == 404
    await routes_passkeys.remove_passkey(str(row.id), _request(), _ctx(user), db)  # type: ignore[arg-type]
    assert db.passkeys == [] and _actions(db)[-1] == "auth.passkey_removed"


def test_credentials_have_a_size_limit() -> None:
    with pytest.raises(ValueError):
        PasskeyAnswer(credential={"id": "x" * 30_000})
    assert PasskeyAddRequest(name="  My   key ", credential={}).name == "My key"
