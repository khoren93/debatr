"""Signing in to the admin console and managing its sessions (`/api/admin/auth/*`).

1. `POST /login`: email + password (5 attempts per 15 min per IP and per email; one answer for a
   wrong password, a disabled account and an account without a role) → a ticket cookie.
2. `POST /totp` with the authenticator code (or a recovery code) → the session cookie.
   First time instead: `POST /enroll/start` with the enrollment code from
   `python -m app.manage admin grant` (shows the new secret as a QR code), then
   `POST /enroll/confirm` with a code from the app → the session and ten recovery codes.
Wrong codes count per ticket (5 → password again) and per account (5 in 15 min → locked).
Every outcome lands in the audit log.
"""

import hashlib
import secrets
import time
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from redis.asyncio import Redis as AsyncRedis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.access import (
    ROLES,
    AdminContext,
    can,
    clear_cookie,
    current_admin,
    require_sudo,
    session_cookie_name,
    set_cookie,
    ticket_cookie_name,
)
from app.core.db import get_db
from app.core.ratelimit import (
    ADMIN_LOGIN_ATTEMPTS,
    ADMIN_LOGIN_WINDOW_SECONDS,
    enforce_admin_login_limit,
    enforce_limit,
)
from app.core.redis import get_async_redis
from app.core.security import (
    decrypt_totp_secret,
    encrypt_totp_secret,
    hash_password,
    verify_password,
)
from app.models.models import User, utcnow
from app.schemas.admin import (
    AdminCodeRequest,
    AdminLoginOut,
    AdminLoginRequest,
    AdminMeOut,
    AdminSessionInfo,
    AdminSessionOut,
    AdminSignedInOut,
    AdminUserOut,
    EnrollConfirmRequest,
    EnrollStartOut,
    EnrollStartRequest,
    RecoveryCodesOut,
    SudoOut,
)
from app.schemas.auth import OkResponse
from app.services.admin import audit, sessions
from app.services.admin.sessions import AdminSession, SignInTicket
from app.services.admin.totp import (
    matching_step,
    new_recovery_codes,
    new_secret,
    provisioning_uri,
    qr_data_uri,
    use_recovery_code,
)

router = APIRouter()

PERMISSION_NAMES = ("console", "debates.read", "moderation", "users", "money", "system", "database")
WRONG_LOGIN = "Wrong email or password"
SIGN_IN_AGAIN = "Sign in again"
_dummy_hash: str | None = None


def _time(value: float) -> datetime:
    return datetime.fromtimestamp(value, UTC)


def me_out(user: User, session: AdminSession, session_hash: str) -> AdminMeOut:
    role = user.admin_role or ""
    return AdminMeOut(
        user=AdminUserOut(
            id=str(user.id), email=user.email, display_name=user.display_name, role=role
        ),
        csrf=session.csrf,
        session=AdminSessionInfo(
            id=sessions.public_id(session_hash),
            created_at=_time(session.created_at),
            expires_at=_time(session.expires_at()),
            ends_at=_time(session.created_at + sessions.ABSOLUTE_SECONDS),
            sudo_until=_time(session.sudo_until) if session.is_sudo(time.time()) else None,
        ),
        recovery_codes_left=len(user.recovery_codes_json or []),
        permissions=[name for name in PERMISSION_NAMES if can(role, name)],
    )


def _password_matches(user: User | None, password: str) -> bool:
    """bcrypt runs for unknown emails too, so the answer time does not reveal accounts."""
    global _dummy_hash
    if user is None:
        if _dummy_hash is None:
            _dummy_hash = hash_password(secrets.token_urlsafe(16))
        verify_password(password, _dummy_hash)
        return False
    return verify_password(password, user.password_hash)


def _refusal(user: User | None, password_ok: bool) -> str | None:
    """Why a sign-in is refused (for the audit log only; the answer is always WRONG_LOGIN)."""
    if user is None:
        return "no such account"
    if not password_ok:
        return "wrong password"
    if not user.is_active:
        return "account disabled"
    if user.admin_role not in ROLES:
        return "not an admin"
    return None


@router.post("/login", response_model=AdminLoginOut)
async def login(
    body: AdminLoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> AdminLoginOut:
    await enforce_admin_login_limit(request)
    await enforce_limit(
        request,
        bucket="admin_login_email",
        limit=ADMIN_LOGIN_ATTEMPTS,
        window_seconds=ADMIN_LOGIN_WINDOW_SECONDS,
        what="sign-in attempts",
        key=hashlib.sha256(body.email.encode()).hexdigest(),
    )
    user = await db.scalar(select(User).where(User.email == body.email))
    password_ok = _password_matches(user, body.password)
    refusal = _refusal(user, password_ok)
    if refusal is not None or user is None:
        await audit.record(
            db,
            "auth.login_failed",
            request=request,
            actor=user,
            actor_email=body.email,
            reason=refusal,
            ok=False,
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=WRONG_LOGIN)

    ticket = SignInTicket(
        user_id=str(user.id),
        epoch=user.session_epoch,
        ip=audit.client_ip(request) or "",
        created_at=time.time(),
    )
    token = await sessions.create_ticket(get_async_redis(), ticket)
    set_cookie(response, request, ticket_cookie_name(request), token, sessions.TICKET_SECONDS)
    enrolled = user.totp_enabled_at is not None and bool(user.totp_secret_enc)
    return AdminLoginOut(next="totp" if enrolled else "enroll")


async def _ticket(request: Request, db: AsyncSession) -> tuple[str, SignInTicket, User]:
    raw = request.cookies.get(ticket_cookie_name(request))
    if not raw:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=SIGN_IN_AGAIN)
    redis = get_async_redis()
    hashed = sessions.token_hash(raw)
    ticket = await sessions.load_ticket(redis, hashed, time.time())
    user = await db.get(User, uuid.UUID(ticket.user_id)) if ticket else None
    if (
        ticket is None
        or user is None
        or not user.is_active
        or user.admin_role not in ROLES
        or user.session_epoch != ticket.epoch
    ):
        await sessions.delete_ticket(redis, hashed)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=SIGN_IN_AGAIN)
    return hashed, ticket, user


async def _check_lock(redis: AsyncRedis, user: User) -> None:
    if await sessions.code_failures(redis, str(user.id)) >= sessions.MAX_CODE_FAILURES:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many wrong codes. Try again in 15 minutes.",
        )


async def _code_failed(
    request: Request,
    db: AsyncSession,
    redis: AsyncRedis,
    user: User,
    action: str,
    ticket: tuple[str, SignInTicket] | None = None,
) -> HTTPException:
    """Count a wrong code and build the error to raise (400: a 401 would read as signed out)."""
    count = await sessions.add_code_failure(redis, str(user.id))
    if ticket is not None:
        hashed, state = ticket
        state.failures += 1
        if state.failures >= sessions.MAX_TICKET_FAILURES:
            await sessions.delete_ticket(redis, hashed)
        else:
            await sessions.save_ticket(redis, hashed, state)
    locked = count >= sessions.MAX_CODE_FAILURES
    await audit.record(
        db, "auth.locked" if locked else action, request=request, actor=user, ok=False
    )
    if locked:
        return HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many wrong codes. Try again in 15 minutes.",
        )
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Wrong code")


def _secret_of(user: User) -> str:
    secret = decrypt_totp_secret(user.totp_secret_enc or "")
    if secret is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The authenticator secret cannot be read (SECRET_KEY changed?). "
            "Reset it on the server: python -m app.manage admin reset-2fa <email>",
        )
    return secret


async def _sign_in(
    request: Request, response: Response, db: AsyncSession, redis: AsyncRedis, user: User
) -> AdminSignedInOut:
    token, hashed, session = await sessions.create_session(
        redis,
        user_id=str(user.id),
        epoch=user.session_epoch,
        ip=audit.client_ip(request) or "",
        user_agent=audit.user_agent(request) or "",
        now=time.time(),
    )
    set_cookie(response, request, session_cookie_name(request), token, sessions.ABSOLUTE_SECONDS)
    clear_cookie(response, request, ticket_cookie_name(request))
    await audit.record(db, "auth.signed_in", request=request, actor=user)
    return AdminSignedInOut(me=me_out(user, session, hashed))


@router.post("/totp", response_model=AdminSignedInOut)
async def verify_code(
    body: AdminCodeRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> AdminSignedInOut:
    hashed, ticket, user = await _ticket(request, db)
    if user.totp_enabled_at is None or not user.totp_secret_enc:
        raise HTTPException(status_code=409, detail="Set up the authenticator first")
    redis = get_async_redis()
    await _check_lock(redis, user)
    uid = str(user.id)
    if body.recovery_code.strip():
        remaining = use_recovery_code(list(user.recovery_codes_json or []), body.recovery_code)
        if remaining is None:
            raise await _code_failed(
                request, db, redis, user, "auth.recovery_code_failed", (hashed, ticket)
            )
        user.recovery_codes_json = remaining
        await audit.record(
            db,
            "auth.recovery_code_used",
            request=request,
            actor=user,
            after={"left": len(remaining)},
        )
    else:
        secret = _secret_of(user)
        step = matching_step(
            secret, body.code, now=time.time(), after_step=await sessions.last_step(redis, uid)
        )
        if step is None:
            raise await _code_failed(request, db, redis, user, "auth.totp_failed", (hashed, ticket))
        await sessions.remember_step(redis, uid, step)
    await sessions.clear_code_failures(redis, uid)
    await sessions.delete_ticket(redis, hashed)
    return await _sign_in(request, response, db, redis, user)


@router.post("/enroll/start", response_model=EnrollStartOut)
async def enroll_start(
    body: EnrollStartRequest, request: Request, db: AsyncSession = Depends(get_db)
) -> EnrollStartOut:
    hashed, ticket, user = await _ticket(request, db)
    if user.totp_enabled_at is not None:
        raise HTTPException(status_code=409, detail="The authenticator is already set up")
    redis = get_async_redis()
    await _check_lock(redis, user)
    if not await sessions.enrollment_code_matches(redis, str(user.id), body.enrollment_code):
        raise await _code_failed(
            request, db, redis, user, "auth.enroll_code_failed", (hashed, ticket)
        )
    secret = new_secret()
    ticket.pending_secret_enc = encrypt_totp_secret(secret)
    await sessions.save_ticket(redis, hashed, ticket)
    uri = provisioning_uri(secret, user.email)
    return EnrollStartOut(secret=secret, otpauth_uri=uri, qr=qr_data_uri(uri))


@router.post("/enroll/confirm", response_model=AdminSignedInOut)
async def enroll_confirm(
    body: EnrollConfirmRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> AdminSignedInOut:
    hashed, ticket, user = await _ticket(request, db)
    if user.totp_enabled_at is not None:
        raise HTTPException(status_code=409, detail="The authenticator is already set up")
    if not ticket.pending_secret_enc:
        raise HTTPException(status_code=409, detail="Start the setup again")
    redis = get_async_redis()
    await _check_lock(redis, user)
    secret = decrypt_totp_secret(ticket.pending_secret_enc)
    step = matching_step(secret, body.code, now=time.time(), after_step=None) if secret else None
    if secret is None or step is None:
        raise await _code_failed(request, db, redis, user, "auth.enroll_failed", (hashed, ticket))

    plain, hashes = new_recovery_codes()
    user.totp_secret_enc = encrypt_totp_secret(secret)
    user.totp_enabled_at = utcnow()
    user.recovery_codes_json = hashes
    await audit.record(db, "auth.enrolled", request=request, actor=user)
    uid = str(user.id)
    await sessions.drop_enrollment_code(redis, uid)
    await sessions.remember_step(redis, uid, step)
    await sessions.clear_code_failures(redis, uid)
    await sessions.delete_ticket(redis, hashed)
    out = await _sign_in(request, response, db, redis, user)
    out.recovery_codes = plain
    return out


@router.get("/me", response_model=AdminMeOut)
async def me(ctx: AdminContext = Depends(current_admin)) -> AdminMeOut:
    return me_out(ctx.user, ctx.session, ctx.session_hash)


@router.post("/logout", response_model=OkResponse)
async def logout(
    request: Request,
    response: Response,
    ctx: AdminContext = Depends(current_admin),
    db: AsyncSession = Depends(get_db),
) -> OkResponse:
    await sessions.delete_session(get_async_redis(), ctx.session.user_id, ctx.session_hash)
    clear_cookie(response, request, session_cookie_name(request))
    await audit.record(db, "auth.signed_out", request=request, actor=ctx.user)
    return OkResponse()


@router.post("/logout-all", response_model=OkResponse)
async def logout_everywhere(
    request: Request,
    response: Response,
    ctx: AdminContext = Depends(current_admin),
    db: AsyncSession = Depends(get_db),
) -> OkResponse:
    """End every console session of this admin, this one included."""
    count = await sessions.revoke_all(get_async_redis(), ctx.session.user_id)
    ctx.user.session_epoch += 1
    clear_cookie(response, request, session_cookie_name(request))
    await audit.record(
        db, "auth.signed_out_everywhere", request=request, actor=ctx.user, after={"ended": count}
    )
    return OkResponse()


@router.get("/sessions", response_model=list[AdminSessionOut])
async def list_sessions(ctx: AdminContext = Depends(current_admin)) -> list[AdminSessionOut]:
    found = await sessions.list_sessions(get_async_redis(), ctx.session.user_id, time.time())
    return [
        AdminSessionOut(
            id=sessions.public_id(hashed),
            created_at=_time(session.created_at),
            last_seen_at=_time(session.last_seen_at),
            expires_at=_time(session.expires_at()),
            ip=session.ip,
            user_agent=session.user_agent,
            current=hashed == ctx.session_hash,
        )
        for hashed, session in found
    ]


@router.delete("/sessions/{session_id}", response_model=OkResponse)
async def revoke_session(
    session_id: str,
    request: Request,
    response: Response,
    ctx: AdminContext = Depends(current_admin),
    db: AsyncSession = Depends(get_db),
) -> OkResponse:
    redis = get_async_redis()
    found = await sessions.list_sessions(redis, ctx.session.user_id, time.time())
    match = next((hashed for hashed, _ in found if sessions.public_id(hashed) == session_id), None)
    if match is None:
        raise HTTPException(status_code=404, detail="No such session")
    await sessions.delete_session(redis, ctx.session.user_id, match)
    if match == ctx.session_hash:
        clear_cookie(response, request, session_cookie_name(request))
    await audit.record(
        db,
        "auth.session_revoked",
        request=request,
        actor=ctx.user,
        target_type="admin_session",
        target_id=session_id,
    )
    return OkResponse()


@router.post("/sudo", response_model=SudoOut)
async def confirm_sudo(
    body: AdminCodeRequest,
    request: Request,
    ctx: AdminContext = Depends(current_admin),
    db: AsyncSession = Depends(get_db),
) -> SudoOut:
    """A fresh authenticator code unlocks the dangerous actions for a few minutes."""
    redis = get_async_redis()
    user = ctx.user
    await _check_lock(redis, user)
    uid = str(user.id)
    step = matching_step(
        _secret_of(user),
        body.code,
        now=time.time(),
        after_step=await sessions.last_step(redis, uid),
    )
    if step is None:
        raise await _code_failed(request, db, redis, user, "auth.sudo_failed")
    await sessions.remember_step(redis, uid, step)
    await sessions.clear_code_failures(redis, uid)
    now = time.time()
    ctx.session.sudo_until = now + sessions.SUDO_SECONDS
    await sessions.save_session(redis, ctx.session_hash, ctx.session, now)
    await audit.record(db, "auth.sudo", request=request, actor=user)
    return SudoOut(sudo_until=_time(ctx.session.sudo_until))


@router.post("/recovery-codes", response_model=RecoveryCodesOut)
async def regenerate_recovery_codes(
    request: Request,
    ctx: AdminContext = Depends(require_sudo),
    db: AsyncSession = Depends(get_db),
) -> RecoveryCodesOut:
    """Ten new recovery codes; the old ones stop working."""
    plain, hashes = new_recovery_codes()
    ctx.user.recovery_codes_json = hashes
    await audit.record(db, "auth.recovery_codes_regenerated", request=request, actor=ctx.user)
    return RecoveryCodesOut(recovery_codes=plain)
