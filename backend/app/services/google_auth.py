"""Sign-in with Google (OpenID Connect, the server-side authorization code flow with PKCE).

- `begin` starts a flow: a random `state` (also kept in a short cookie of the browser that
  started it, so a flow started elsewhere cannot be finished here), a PKCE verifier and a nonce,
  stored in Redis for FLOW_SECONDS under the hash of the state with the mode (`login`, or `link`
  Google to the account signed in), the page to land on and, to link, the account and its
  session epoch. `take` reads a flow once.
- `exchange` trades the code for tokens at Google (client secret + PKCE verifier) and
  `verify_id_token` checks the ID token: RS256 signature against Google's published keys
  (cached; fetched again for an unknown key id), issuer, audience = our client id, expiry and
  the flow's nonce.
- `decide` / `decide_link` (pure) say what a verified Google account means here. A Google
  account is tied to an account by Google's `sub`, never by email, except once: a new Google
  sign-in whose email is an account's *confirmed* email joins that account. An unconfirmed one
  is refused (whoever registered the address first, maybe not its owner, would keep their
  password into the owner's account); its owner signs in with the password (or a reset link)
  and connects Google in Account → Security.
"""

import base64
import binascii
import hashlib
import json
import logging
import secrets
import time
from dataclasses import asdict, dataclass
from typing import Any, Literal
from urllib.parse import urlencode

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicNumbers

from app.core.config import settings
from app.core.redis import get_async_redis, google_flow_key
from app.models.models import User, UserIdentity

logger = logging.getLogger(__name__)

PROVIDER = "google"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
ISSUERS = ("https://accounts.google.com", "accounts.google.com")
SCOPE = "openid email profile"
FLOW_SECONDS = 600
KEYS_SECONDS = 3600
LEEWAY_SECONDS = 60
HTTP_TIMEOUT_SECONDS = 10.0

Mode = Literal["login", "link"]
# What the site tells the visitor when a sign-in does not go through (`?error=google_<code>`):
# cancelled, expired, failed, unverified, disabled, exists, closed, taken, one_google, off.
Refusal = str


class GoogleError(Exception):
    """The exchange or the ID token check failed (logged; the visitor sees "failed")."""


class UnknownKeyError(GoogleError):
    """The token names a key Google's cached list does not have (fetched again once)."""


@dataclass(frozen=True)
class Flow:
    mode: Mode
    verifier: str
    nonce: str
    next: str | None = None
    uid: str | None = None  # link: the account that started it
    epoch: int | None = None  # link: its session epoch then (a password change ends the flow)


@dataclass(frozen=True)
class GoogleAccount:
    subject: str
    email: str
    email_verified: bool
    name: str


def enabled() -> bool:
    return bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET)


def redirect_uri() -> str:
    return f"{settings.SITE_URL.rstrip('/')}/api/auth/google/callback"


def _hash(state: str) -> str:
    return hashlib.sha256(state.encode("utf-8")).hexdigest()


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64url(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def challenge(verifier: str) -> str:
    """The PKCE S256 code challenge of a verifier."""
    return _b64url(hashlib.sha256(verifier.encode("ascii")).digest())


def authorize_url(state: str, flow: Flow) -> str:
    query = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "scope": SCOPE,
        "state": state,
        "nonce": flow.nonce,
        "code_challenge": challenge(flow.verifier),
        "code_challenge_method": "S256",
        "prompt": "select_account",
    }
    return f"{AUTH_URL}?{urlencode(query)}"


async def begin(mode: Mode, *, next_path: str | None, user: User | None = None) -> tuple[str, str]:
    """A new flow: its `state` (for the browser's cookie) and Google's address to go to. Raises
    RedisError when Redis is down."""
    state = secrets.token_urlsafe(32)
    flow = Flow(
        mode=mode,
        verifier=secrets.token_urlsafe(48),
        nonce=secrets.token_urlsafe(16),
        next=next_path,
        uid=str(user.id) if user is not None else None,
        epoch=user.session_epoch if user is not None else None,
    )
    await get_async_redis().set(
        google_flow_key(_hash(state)), json.dumps(asdict(flow)), ex=FLOW_SECONDS
    )
    return state, authorize_url(state, flow)


async def take(state: str) -> Flow | None:
    """The flow of a `state`, once (None: unknown, expired or already used)."""
    if not state or len(state) > 200:
        return None
    raw = await get_async_redis().getdel(google_flow_key(_hash(state)))
    if raw is None:
        return None
    try:
        return Flow(**json.loads(raw))
    except (ValueError, TypeError):
        return None


# --- the ID token -----------------------------------------------------------------------------


def _public_key(jwk: dict[str, Any]) -> Any:
    n = int.from_bytes(_unb64url(str(jwk["n"])), "big")
    e = int.from_bytes(_unb64url(str(jwk["e"])), "big")
    return RSAPublicNumbers(e, n).public_key()


def verify_id_token(
    token: str, keys: list[dict[str, Any]], *, client_id: str, nonce: str, now: float
) -> GoogleAccount:
    """The account an ID token stands for, after checking its signature and claims."""
    try:
        head_b64, body_b64, signature_b64 = token.split(".")
        header = json.loads(_unb64url(head_b64))
        claims = json.loads(_unb64url(body_b64))
        signature = _unb64url(signature_b64)
    except (ValueError, binascii.Error, AttributeError) as e:
        raise GoogleError("unreadable ID token") from e
    if not isinstance(header, dict) or not isinstance(claims, dict):
        raise GoogleError("unreadable ID token")
    if header.get("alg") != "RS256":
        raise GoogleError(f"unexpected algorithm {header.get('alg')!r}")
    jwk = next(
        (k for k in keys if k.get("kid") == header.get("kid") and k.get("kty") == "RSA"), None
    )
    if jwk is None:
        raise UnknownKeyError(f"unknown key {header.get('kid')!r}")
    try:
        _public_key(jwk).verify(
            signature, f"{head_b64}.{body_b64}".encode(), padding.PKCS1v15(), hashes.SHA256()
        )
    except (InvalidSignature, KeyError, ValueError) as e:
        raise GoogleError("bad signature") from e
    if claims.get("iss") not in ISSUERS:
        raise GoogleError(f"unexpected issuer {claims.get('iss')!r}")
    audience = claims.get("aud")
    if (audience if isinstance(audience, list) else [audience]) != [client_id]:
        raise GoogleError("issued for another client")
    try:
        expires, issued = float(claims["exp"]), float(claims.get("iat", now))
    except (KeyError, TypeError, ValueError) as e:
        raise GoogleError("no expiry") from e
    if expires < now - LEEWAY_SECONDS or issued > now + LEEWAY_SECONDS:
        raise GoogleError("expired or not yet valid")
    if not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
        raise GoogleError("nonce does not match")
    subject, email = claims.get("sub"), claims.get("email")
    if (
        not isinstance(subject, str)
        or not subject
        or not isinstance(email, str)
        or "@" not in email
    ):
        raise GoogleError("no subject or email")
    verified = claims.get("email_verified")
    return GoogleAccount(
        subject=subject[:255],
        email=email.strip().lower()[:320],
        email_verified=verified is True or verified == "true",
        name=str(claims.get("name") or "").strip()[:100],
    )


_keys: dict[str, Any] = {"at": 0.0, "keys": []}


async def google_keys(
    *, refresh: bool = False, transport: httpx.AsyncBaseTransport | None = None
) -> list[dict[str, Any]]:
    """Google's signing keys, cached for KEYS_SECONDS in the process."""
    if not refresh and _keys["keys"] and time.monotonic() - _keys["at"] < KEYS_SECONDS:
        return _keys["keys"]
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS, transport=transport) as client:
        response = await client.get(JWKS_URL)
    response.raise_for_status()
    keys = response.json().get("keys")
    if not isinstance(keys, list):
        raise GoogleError("no keys from Google")
    _keys.update(at=time.monotonic(), keys=keys)
    return keys


async def exchange(
    code: str, flow: Flow, *, transport: httpx.AsyncBaseTransport | None = None
) -> GoogleAccount:
    """Trade the code Google sent back for the verified account (raises GoogleError or
    httpx.HTTPError)."""
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS, transport=transport) as client:
        response = await client.post(
            TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET or "",
                "redirect_uri": redirect_uri(),
                "grant_type": "authorization_code",
                "code_verifier": flow.verifier,
            },
        )
    try:
        answer = response.json()
    except ValueError:
        answer = {}
    if response.status_code != 200 or not isinstance(answer, dict):
        error = answer.get("error") if isinstance(answer, dict) else None
        raise GoogleError(f"token endpoint answered {response.status_code} ({error or 'no error'})")
    token = answer.get("id_token")
    if not isinstance(token, str):
        raise GoogleError("no ID token")
    check = {"client_id": settings.GOOGLE_CLIENT_ID, "nonce": flow.nonce}
    try:
        keys = await google_keys(transport=transport)
        return verify_id_token(token, keys, now=time.time(), **check)
    except UnknownKeyError:
        keys = await google_keys(refresh=True, transport=transport)  # Google rotated its keys
        return verify_id_token(token, keys, now=time.time(), **check)


# --- what a Google account means here (pure) --------------------------------------------------


@dataclass(frozen=True)
class Decision:
    # sign_in: the account it is tied to; join: tie it to the account with its confirmed email;
    # create: a new account; linked: already tied to this account; refuse: `error` says why.
    action: Literal["sign_in", "join", "create", "linked", "refuse"]
    error: Refusal | None = None


def _refuse(error: Refusal) -> Decision:
    return Decision("refuse", error)


def decide(
    account: GoogleAccount,
    *,
    tied: User | None,
    same_email: User | None,
    registration_open: bool,
) -> Decision:
    """A sign-in with Google: `tied` = the account this Google account is tied to, `same_email` =
    the account with its email (looked up only when none is tied)."""
    if tied is not None:
        return Decision("sign_in") if tied.is_active else _refuse("disabled")
    if not account.email_verified:
        return _refuse("unverified")
    if same_email is not None:
        if not same_email.is_active:
            return _refuse("disabled")
        if same_email.email_verified_at is None:
            return _refuse("exists")
        return Decision("join")
    if not registration_open:
        return _refuse("closed")
    return Decision("create")


def decide_link(
    flow: Flow,
    *,
    user: User | None,
    tied: User | None,
    current: UserIdentity | None,
) -> Decision:
    """Connecting Google to the signed-in account (`flow.uid`): `tied` = the account this Google
    account is tied to now, `current` = the account's own Google identity."""
    if user is None or not user.is_active or user.session_epoch != flow.epoch:
        return _refuse("expired")
    if tied is not None:
        return Decision("linked") if tied.id == user.id else _refuse("taken")
    if current is not None:
        return _refuse("one_google")
    return Decision("join")
