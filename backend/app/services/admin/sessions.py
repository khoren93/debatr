"""Server-side sessions of the admin console, sign-in tickets and second-factor state (Redis).

A session is a random 256-bit token in the console's `__Host-` cookie; Redis keeps only its
SHA-256 → AdminSession (owner, CSRF token, IP, browser, times, the user's `session_epoch` at
sign-in, sudo deadline). It ends IDLE_SECONDS after the last request or ABSOLUTE_SECONDS after
sign-in, whichever comes first, when it is revoked, or when the account changes (app.admin.access
compares role, activity and epoch on every request). Unlike the signed user cookie it can be
revoked at once. A ticket carries a sign-in from the password to the TOTP code for
TICKET_SECONDS (also only by hash). The async functions serve the API, the `_sync` ones the
server commands (`app.manage`).
"""

import hashlib
import secrets

from pydantic import BaseModel
from redis import Redis
from redis.asyncio import Redis as AsyncRedis

from app.core.redis import (
    admin_enroll_key,
    admin_session_key,
    admin_ticket_key,
    admin_totp_failures_key,
    admin_totp_step_key,
    admin_user_sessions_key,
)
from app.services.admin.totp import code_hash, new_enrollment_code, normalize_code

IDLE_SECONDS = 30 * 60
ABSOLUTE_SECONDS = 12 * 60 * 60
# Room for installing an authenticator app on the first sign-in.
TICKET_SECONDS = 10 * 60
# `last_seen_at` (and so the idle deadline) is written at most this often.
TOUCH_EVERY_SECONDS = 60
SUDO_SECONDS = 5 * 60
ENROLL_SECONDS = 24 * 60 * 60
# Wrong TOTP / recovery codes per account before the second factor locks for LOCK_SECONDS.
MAX_CODE_FAILURES = 5
LOCK_SECONDS = 15 * 60
# A ticket is dropped (password again) after this many wrong codes.
MAX_TICKET_FAILURES = 5


class AdminSession(BaseModel):
    user_id: str
    csrf: str
    created_at: float
    last_seen_at: float
    ip: str
    user_agent: str
    epoch: int
    sudo_until: float = 0.0

    def expires_at(self) -> float:
        return min(self.last_seen_at + IDLE_SECONDS, self.created_at + ABSOLUTE_SECONDS)

    def ttl(self, now: float) -> int:
        return max(0, int(self.expires_at() - now))

    def is_sudo(self, now: float) -> bool:
        return self.sudo_until > now


class SignInTicket(BaseModel):
    user_id: str
    epoch: int
    ip: str
    created_at: float
    failures: int = 0
    # Enrollment in progress: the new TOTP secret (encrypted) shown to the admin once.
    pending_secret_enc: str | None = None
    # A passkey sign-in in progress: its WebAuthn challenge (base64url, used once).
    passkey_challenge: str | None = None


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def public_id(session_hash: str) -> str:
    """What the console shows (and revokes by): a prefix of the hash, never the token."""
    return session_hash[:16]


def _text(value: bytes | str | None) -> str | None:
    if value is None:
        return None
    return value.decode() if isinstance(value, bytes) else value


# --- sessions ---------------------------------------------------------------------------------


async def create_session(
    redis: AsyncRedis, *, user_id: str, epoch: int, ip: str, user_agent: str, now: float
) -> tuple[str, str, AdminSession]:
    """(token for the cookie, its hash, the session)."""
    token = new_token()
    session = AdminSession(
        user_id=user_id,
        csrf=secrets.token_urlsafe(32),
        created_at=now,
        last_seen_at=now,
        ip=ip,
        user_agent=user_agent,
        epoch=epoch,
    )
    hashed = token_hash(token)
    await save_session(redis, hashed, session, now)
    await redis.sadd(admin_user_sessions_key(user_id), hashed)  # type: ignore[misc]
    await redis.expire(admin_user_sessions_key(user_id), ABSOLUTE_SECONDS)
    return token, hashed, session


async def save_session(redis: AsyncRedis, hashed: str, session: AdminSession, now: float) -> None:
    ttl = session.ttl(now)
    if ttl <= 0:
        await delete_session(redis, session.user_id, hashed)
        return
    await redis.set(admin_session_key(hashed), session.model_dump_json(), ex=ttl)


async def load_session(redis: AsyncRedis, hashed: str, now: float) -> AdminSession | None:
    raw = _text(await redis.get(admin_session_key(hashed)))
    if raw is None:
        return None
    try:
        session = AdminSession.model_validate_json(raw)
    except ValueError:
        await redis.delete(admin_session_key(hashed))
        return None
    if session.ttl(now) <= 0:
        await delete_session(redis, session.user_id, hashed)
        return None
    return session


async def delete_session(redis: AsyncRedis, user_id: str, hashed: str) -> None:
    await redis.delete(admin_session_key(hashed))
    await redis.srem(admin_user_sessions_key(user_id), hashed)  # type: ignore[misc]


async def list_sessions(
    redis: AsyncRedis, user_id: str, now: float
) -> list[tuple[str, AdminSession]]:
    """Live sessions of an admin, newest first (ended ones are dropped from the set)."""
    found: list[tuple[str, AdminSession]] = []
    members = await redis.smembers(admin_user_sessions_key(user_id))  # type: ignore[misc]
    for member in members:
        hashed = _text(member) or ""
        session = await load_session(redis, hashed, now)
        if session is None:
            await redis.srem(admin_user_sessions_key(user_id), hashed)  # type: ignore[misc]
        else:
            found.append((hashed, session))
    return sorted(found, key=lambda item: item[1].created_at, reverse=True)


async def revoke_all(redis: AsyncRedis, user_id: str) -> int:
    members = await redis.smembers(admin_user_sessions_key(user_id))  # type: ignore[misc]
    hashes = [_text(member) or "" for member in members]
    if hashes:
        await redis.delete(*[admin_session_key(hashed) for hashed in hashes])
    await redis.delete(admin_user_sessions_key(user_id))
    return len(hashes)


def revoke_all_sync(redis: Redis, user_id: str) -> int:
    members: set[bytes] = redis.smembers(admin_user_sessions_key(user_id))  # type: ignore[assignment]
    hashes = [_text(member) or "" for member in members]
    if hashes:
        redis.delete(*[admin_session_key(hashed) for hashed in hashes])
    redis.delete(admin_user_sessions_key(user_id))
    return len(hashes)


# --- sign-in tickets --------------------------------------------------------------------------


async def create_ticket(redis: AsyncRedis, ticket: SignInTicket) -> str:
    token = new_token()
    await save_ticket(redis, token_hash(token), ticket)
    return token


async def save_ticket(redis: AsyncRedis, hashed: str, ticket: SignInTicket) -> None:
    await redis.set(admin_ticket_key(hashed), ticket.model_dump_json(), ex=TICKET_SECONDS)


async def load_ticket(redis: AsyncRedis, hashed: str, now: float) -> SignInTicket | None:
    raw = _text(await redis.get(admin_ticket_key(hashed)))
    if raw is None:
        return None
    try:
        ticket = SignInTicket.model_validate_json(raw)
    except ValueError:
        return None
    return ticket if now - ticket.created_at <= TICKET_SECONDS else None


async def delete_ticket(redis: AsyncRedis, hashed: str) -> None:
    await redis.delete(admin_ticket_key(hashed))


# --- second-factor state ----------------------------------------------------------------------


async def last_step(redis: AsyncRedis, user_id: str) -> int | None:
    raw = _text(await redis.get(admin_totp_step_key(user_id)))
    return int(raw) if raw and raw.isdigit() else None


async def remember_step(redis: AsyncRedis, user_id: str, step: int) -> None:
    # Longer than the accepted window, so a code cannot come back within it.
    await redis.set(admin_totp_step_key(user_id), str(step), ex=10 * 60)


async def code_failures(redis: AsyncRedis, user_id: str) -> int:
    raw = _text(await redis.get(admin_totp_failures_key(user_id)))
    return int(raw) if raw and raw.isdigit() else 0


async def add_code_failure(redis: AsyncRedis, user_id: str) -> int:
    key = admin_totp_failures_key(user_id)
    count = int(await redis.incr(key))
    if count == 1:
        await redis.expire(key, LOCK_SECONDS)
    return count


async def clear_code_failures(redis: AsyncRedis, user_id: str) -> None:
    await redis.delete(admin_totp_failures_key(user_id))


# --- enrollment codes -------------------------------------------------------------------------


def issue_enrollment_code_sync(redis: Redis, user_id: str) -> str:
    """A fresh one-time code for setting up the authenticator (replaces an older one)."""
    code = new_enrollment_code()
    redis.set(admin_enroll_key(user_id), code_hash(code), ex=ENROLL_SECONDS)
    return code


def drop_enrollment_code_sync(redis: Redis, user_id: str) -> None:
    redis.delete(admin_enroll_key(user_id))


async def enrollment_code_matches(redis: AsyncRedis, user_id: str, code: str) -> bool:
    if not normalize_code(code):
        return False
    stored = _text(await redis.get(admin_enroll_key(user_id)))
    return stored is not None and secrets.compare_digest(stored, code_hash(code))


async def drop_enrollment_code(redis: AsyncRedis, user_id: str) -> None:
    await redis.delete(admin_enroll_key(user_id))
