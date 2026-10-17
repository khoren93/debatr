"""Personal API tokens (CLI, scripts, MCP agents) and the `debatr login` device flow.

Tokens are `debatr_` + 256 random bits; only their SHA-256 hash is stored (`api_tokens`). A token
can expire and can have a spending limit: before a run starts, the credits already charged for
the runs the token started (with their voices and pictures) plus the estimates of its runs still
in progress plus the new estimate must fit in the limit. Like the balance, the final charge may
overshoot a little when a run costs more than estimated.

Device flow (as in `gh auth login`, RFC 8628): the CLI asks for a request (`start_device`) and
opens `/device?code=WDJB-MJHT`, where the signed-in user approves it (a token is created for
them) or denies it; meanwhile the CLI polls with its secret device code and receives the token
exactly once. Requests live in Redis for DEVICE_TTL seconds, the token Fernet-encrypted.
"""

import hashlib
import json
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import (
    device_claim_key,
    device_request_key,
    device_user_code_key,
    get_async_redis,
)
from app.core.security import (
    decrypt_secret,
    encrypt_secret,
    hash_api_token,
    key_last4,
    mask_api_token,
    new_api_token,
)
from app.models.models import ApiToken, CreditTransaction, Debate, User, utcnow
from app.schemas.auth import ApiTokenOut, DeviceStatus
from app.schemas.schemas import DebateConfig
from app.services.credits import ZERO, to_usd

MAX_TOKENS_PER_USER = 50
DEVICE_TTL = 600  # seconds a login request stays valid
DEVICE_POLL_INTERVAL = 3  # seconds between CLI polls
# No vowels (no accidental words) and no look-alike characters; 20^8 ≈ 2.6e10 codes.
USER_CODE_ALPHABET = "BCDFGHJKLMNPQRSTVWXZ"
USER_CODE_LENGTH = 8
ACTIVE_RUN_STATUSES = ("queued", "running")
ACTIVE_MEDIA_STATUSES = ("queued", "running")


# --- tokens -------------------------------------------------------------------


def is_expired(token: ApiToken, now: datetime | None = None) -> bool:
    return token.expires_at is not None and token.expires_at <= (now or utcnow())


def token_out(token: ApiToken, spent: Decimal = ZERO) -> ApiTokenOut:
    return ApiTokenOut(
        id=str(token.id),
        name=token.name,
        token_hint=mask_api_token(token.token_last4),
        created_at=token.created_at,
        last_used_at=token.last_used_at,
        expires_at=token.expires_at,
        expired=is_expired(token),
        spend_limit_usd=float(token.spend_limit_usd) if token.spend_limit_usd is not None else None,
        spent_usd=float(spent),
    )


async def count_active_tokens(db: AsyncSession, user_id: uuid.UUID) -> int:
    now = utcnow()
    stmt = select(func.count(ApiToken.id)).where(
        ApiToken.user_id == user_id,
        or_(ApiToken.expires_at.is_(None), ApiToken.expires_at > now),
    )
    return int(await db.scalar(stmt) or 0)


async def create_token(
    db: AsyncSession,
    user: User,
    *,
    name: str,
    expires_in_days: int | None,
    spend_limit_usd: float | None,
) -> tuple[ApiToken, str]:
    """Create a token for the user; returns the row and the plaintext (shown once)."""
    secret = new_api_token()
    token = ApiToken(
        user_id=user.id,
        name=name[:100],
        token_hash=hash_api_token(secret),
        token_last4=key_last4(secret),
        spend_limit_usd=to_usd(spend_limit_usd) if spend_limit_usd is not None else None,
        created_at=utcnow(),
        expires_at=utcnow() + timedelta(days=expires_in_days) if expires_in_days else None,
    )
    db.add(token)
    await db.commit()
    await db.refresh(token)
    return token, secret


async def spent_by_tokens(db: AsyncSession, token_ids: list[uuid.UUID]) -> dict[uuid.UUID, Decimal]:
    """Credits charged for the runs each token started: the net of every ledger row of those
    debates (charges minus refunds), never below zero."""
    if not token_ids:
        return {}
    stmt = (
        select(Debate.api_token_id, func.coalesce(func.sum(CreditTransaction.amount_usd), 0))
        .join(CreditTransaction, CreditTransaction.debate_id == Debate.id)
        .where(Debate.api_token_id.in_(token_ids))
        .group_by(Debate.api_token_id)
    )
    out: dict[uuid.UUID, Decimal] = {}
    for token_id, total in (await db.execute(stmt)).all():
        if token_id is not None:
            out[token_id] = max(ZERO, -to_usd(total))
    return out


def pending_estimate(debate_status: str, media_status: str, config: dict[str, Any]) -> Decimal:
    """Credits a run of a token will still be charged: the whole estimate while it runs, the
    media part (premium voices, AI pictures) while its automatic media build runs."""
    billing = config.get("billing") or {}
    if debate_status in ACTIVE_RUN_STATUSES:
        return to_usd(billing.get("estimate_usd") or 0)
    if media_status in ACTIVE_MEDIA_STATUSES:
        return to_usd(billing.get("media_estimate_usd") or 0)
    return ZERO


async def reserved_by_token(db: AsyncSession, token_id: uuid.UUID) -> Decimal:
    stmt = select(Debate.status, Debate.media_status, Debate.config_json).where(
        Debate.api_token_id == token_id,
        or_(
            Debate.status.in_(ACTIVE_RUN_STATUSES),
            Debate.media_status.in_(ACTIVE_MEDIA_STATUSES),
        ),
    )
    total = ZERO
    for status, media_status, config in (await db.execute(stmt)).all():
        total += pending_estimate(status, media_status or "none", config or {})
    return total


def remaining_budget(limit: Decimal | None, spent: Decimal, reserved: Decimal) -> Decimal | None:
    """What a token may still spend; None without a limit."""
    if limit is None:
        return None
    return max(ZERO, to_usd(limit) - spent - reserved)


async def budget_left(db: AsyncSession, token: ApiToken | None) -> Decimal | None:
    if token is None or token.spend_limit_usd is None:
        return None
    spent = (await spent_by_tokens(db, [token.id])).get(token.id, ZERO)
    return remaining_budget(token.spend_limit_usd, spent, await reserved_by_token(db, token.id))


def with_token_defaults(config: DebateConfig) -> DebateConfig:
    """Debates created with an API token stay private unless the request asks to publish them
    (`auto_publish` sent explicitly), so scripts and agents don't fill the gallery by accident."""
    if "auto_publish" in config.model_fields_set:
        return config
    return config.model_copy(update={"auto_publish": False})


# --- device flow ----------------------------------------------------------------


def new_user_code() -> str:
    chars = "".join(secrets.choice(USER_CODE_ALPHABET) for _ in range(USER_CODE_LENGTH))
    return f"{chars[:4]}-{chars[4:]}"


def normalize_user_code(raw: str) -> str | None:
    """ "wdjb mjht" / "WDJBMJHT" / "WDJB-MJHT" -> "WDJB-MJHT"; None when it cannot be a code."""
    chars = "".join(ch for ch in raw.upper() if ch.isalnum())
    if len(chars) != USER_CODE_LENGTH or any(ch not in USER_CODE_ALPHABET for ch in chars):
        return None
    return f"{chars[:4]}-{chars[4:]}"


def _text(value: bytes | str | None) -> str | None:
    """Redis replies are str (decode_responses=True); typed as bytes | str by redis-py."""
    return value.decode("utf-8") if isinstance(value, bytes) else value


def _device_hash(device_code: str) -> str:
    return hashlib.sha256(device_code.encode("utf-8")).hexdigest()


@dataclass
class DeviceRequest:
    user_code: str
    client_name: str
    status: DeviceStatus
    created_at: datetime
    token_enc: str | None = None
    token_id: str | None = None

    @property
    def expires_at(self) -> datetime:
        return self.created_at + timedelta(seconds=DEVICE_TTL)

    def dump(self) -> str:
        return json.dumps(
            {
                "user_code": self.user_code,
                "client_name": self.client_name,
                "status": self.status,
                "created_at": self.created_at.isoformat(),
                "token_enc": self.token_enc,
                "token_id": self.token_id,
            }
        )

    @classmethod
    def load(cls, raw: bytes | str | None) -> "DeviceRequest | None":
        raw = _text(raw)
        if not raw:
            return None
        try:
            data = json.loads(raw)
            return cls(
                user_code=str(data["user_code"]),
                client_name=str(data["client_name"]),
                status=data["status"],
                created_at=datetime.fromisoformat(data["created_at"]),
                token_enc=data.get("token_enc"),
                token_id=data.get("token_id"),
            )
        except (ValueError, KeyError, TypeError):
            return None


async def start_device(client_name: str) -> tuple[str, DeviceRequest]:
    """A new login request: (secret device code, request)."""
    redis = get_async_redis()
    device_code = secrets.token_urlsafe(32)
    digest = _device_hash(device_code)
    for _ in range(5):
        user_code = new_user_code()
        # NX: never hand out a code that is still pending for another device.
        if await redis.set(device_user_code_key(user_code), digest, nx=True, ex=DEVICE_TTL):
            break
    else:  # pragma: no cover - 5 collisions in a 2.6e10 space
        raise RuntimeError("Could not allocate a device code")
    request = DeviceRequest(
        user_code=user_code, client_name=client_name, status="pending", created_at=utcnow()
    )
    await redis.set(device_request_key(digest), request.dump(), ex=DEVICE_TTL)
    return device_code, request


async def _lookup(user_code: str) -> tuple[str, DeviceRequest] | None:
    redis = get_async_redis()
    digest = _text(await redis.get(device_user_code_key(user_code)))
    if not digest:
        return None
    request = DeviceRequest.load(await redis.get(device_request_key(digest)))
    return (digest, request) if request is not None else None


async def find_device(user_code: str) -> DeviceRequest | None:
    found = await _lookup(user_code)
    return found[1] if found else None


async def _claim(digest: str) -> bool:
    """True for the first approve / deny of a request; later ones lose."""
    return bool(await get_async_redis().set(device_claim_key(digest), "1", nx=True, ex=DEVICE_TTL))


async def approve_device(
    db: AsyncSession,
    user: User,
    user_code: str,
    *,
    name: str,
    expires_in_days: int | None,
    spend_limit_usd: float | None,
) -> ApiToken | None:
    """Create the token for a pending request; None when the request is gone or decided."""
    found = await _lookup(user_code)
    if found is None or found[1].status != "pending":
        return None
    digest, request = found
    if not await _claim(digest):
        return None
    token, secret = await create_token(
        db, user, name=name, expires_in_days=expires_in_days, spend_limit_usd=spend_limit_usd
    )
    request.status = "approved"
    request.token_enc = encrypt_secret(secret)
    request.token_id = str(token.id)
    await get_async_redis().set(device_request_key(digest), request.dump(), keepttl=True)
    return token


async def deny_device(user_code: str) -> bool:
    found = await _lookup(user_code)
    if found is None or found[1].status != "pending":
        return False
    digest, request = found
    if not await _claim(digest):
        return False
    request.status = "denied"
    await get_async_redis().set(device_request_key(digest), request.dump(), keepttl=True)
    return True


async def poll_device(device_code: str) -> tuple[DeviceStatus, str | None, str | None]:
    """(status, token, token id) for the CLI. An approved request hands out its token once and
    is deleted; a denied one is deleted after it was reported."""
    redis = get_async_redis()
    digest = _device_hash(device_code)
    key = device_request_key(digest)
    request = DeviceRequest.load(await redis.get(key))
    if request is None:
        return "expired", None, None
    if request.status == "pending":
        return "pending", None, None
    # GETDEL: when two polls race, only one of them receives the token.
    taken = DeviceRequest.load(await redis.getdel(key))
    await redis.delete(device_user_code_key(request.user_code), device_claim_key(digest))
    if taken is None:
        return "expired", None, None
    if taken.status == "denied":
        return "denied", None, None
    secret = decrypt_secret(taken.token_enc) if taken.token_enc else None
    if secret is None:  # SECRET_KEY changed in the meantime
        return "expired", None, None
    return "approved", secret, taken.token_id
