"""Passkeys of the admin console (`/api/admin/auth/passkey*`, see services/admin/passkeys).

Sign-in, after the password (ticket cookie): `POST /passkey/options` → the browser asks the
authenticator → `POST /passkey` → the session. A wrong answer counts like a wrong code.
Signed in: list (`GET /passkeys`), add (`POST /passkeys/options` + `POST /passkeys`) and remove
(`DELETE /passkeys/{id}`), both after sudo; sudo itself takes a passkey too
(`POST /sudo/passkey/options` + `POST /sudo/passkey`). Everything lands in the audit log.
"""

import time
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.access import AdminContext, current_admin, require_sudo
from app.api.admin.routes_auth import check_lock, code_failed, sign_in, ticket_of
from app.core.db import get_db
from app.core.redis import get_async_redis
from app.models.models import AdminPasskey, User, utcnow
from app.schemas.admin import (
    AdminPasskeyOut,
    AdminSignedInOut,
    PasskeyAddRequest,
    PasskeyAnswer,
    PasskeyOptionsOut,
    SudoOut,
)
from app.schemas.auth import OkResponse
from app.services.admin import audit, passkeys, sessions
from app.services.admin.passkeys import PasskeyError

router = APIRouter()

NO_PASSKEYS = "No passkey is set up for this account"
START_AGAIN = "The passkey request expired: try again"
NOT_VERIFIED = "That passkey did not verify: try again, or use a code from your authenticator app"


def passkey_out(row: AdminPasskey) -> AdminPasskeyOut:
    return AdminPasskeyOut(
        id=str(row.id),
        name=row.name,
        created_at=row.created_at,
        last_used_at=row.last_used_at,
        backed_up=row.backed_up,
        transports=list(row.transports or []),
    )


async def passkeys_of(db: AsyncSession, user: User) -> list[AdminPasskey]:
    rows = await db.scalars(
        select(AdminPasskey)
        .where(AdminPasskey.user_id == user.id)
        .order_by(AdminPasskey.created_at)
    )
    return list(rows.all())


def _used(row: AdminPasskey, sign_count: int, backed_up: bool) -> None:
    row.sign_count = sign_count
    row.backed_up = backed_up
    row.last_used_at = utcnow()


# --- sign-in ----------------------------------------------------------------------------------


@router.post("/passkey/options", response_model=PasskeyOptionsOut)
async def sign_in_options(
    request: Request, db: AsyncSession = Depends(get_db)
) -> PasskeyOptionsOut:
    hashed, ticket, user = await ticket_of(request, db)
    found = await passkeys_of(db, user)
    if not found:
        raise HTTPException(status_code=409, detail=NO_PASSKEYS)
    redis = get_async_redis()
    await check_lock(redis, user)
    rp_id, _origin = passkeys.relying_party(request)
    options, challenge = passkeys.authentication_options(found, rp_id)
    ticket.passkey_challenge = challenge
    await sessions.save_ticket(redis, hashed, ticket)
    return PasskeyOptionsOut(options=options)


@router.post("/passkey", response_model=AdminSignedInOut)
async def sign_in_with_passkey(
    body: PasskeyAnswer,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> AdminSignedInOut:
    hashed, ticket, user = await ticket_of(request, db)
    redis = get_async_redis()
    await check_lock(redis, user)
    challenge = ticket.passkey_challenge
    if not challenge:
        raise HTTPException(status_code=409, detail=START_AGAIN)
    ticket.passkey_challenge = None  # one answer per challenge
    await sessions.save_ticket(redis, hashed, ticket)
    rp_id, origin = passkeys.relying_party(request)
    try:
        row = passkeys.matching(await passkeys_of(db, user), body.credential)
        sign_count, backed_up = passkeys.check_assertion(
            row, body.credential, challenge, rp_id, origin
        )
    except PasskeyError as exc:
        raise await code_failed(
            request,
            db,
            redis,
            user,
            "auth.passkey_failed",
            (hashed, ticket),
            reason=str(exc),
            wrong=NOT_VERIFIED,
        ) from None
    _used(row, sign_count, backed_up)
    await sessions.clear_code_failures(redis, str(user.id))
    await sessions.delete_ticket(redis, hashed)
    return await sign_in(request, response, db, redis, user, method=f"the passkey “{row.name}”")


# --- managing passkeys ------------------------------------------------------------------------


@router.get("/passkeys", response_model=list[AdminPasskeyOut])
async def list_passkeys(
    ctx: AdminContext = Depends(current_admin), db: AsyncSession = Depends(get_db)
) -> list[AdminPasskeyOut]:
    return [passkey_out(row) for row in await passkeys_of(db, ctx.user)]


@router.post("/passkeys/options", response_model=PasskeyOptionsOut)
async def add_options(
    request: Request,
    ctx: AdminContext = Depends(require_sudo),
    db: AsyncSession = Depends(get_db),
) -> PasskeyOptionsOut:
    existing = await passkeys_of(db, ctx.user)
    if len(existing) >= passkeys.MAX_PASSKEYS:
        raise HTTPException(
            status_code=409, detail=f"At most {passkeys.MAX_PASSKEYS} passkeys: remove one first"
        )
    rp_id, _origin = passkeys.relying_party(request)
    options, challenge = passkeys.registration_options(ctx.user, existing, rp_id)
    await passkeys.remember_challenge(get_async_redis(), ctx.session_hash, "add", challenge)
    return PasskeyOptionsOut(options=options)


@router.post("/passkeys", response_model=AdminPasskeyOut)
async def add_passkey(
    body: PasskeyAddRequest,
    request: Request,
    ctx: AdminContext = Depends(require_sudo),
    db: AsyncSession = Depends(get_db),
) -> AdminPasskeyOut:
    challenge = await passkeys.take_challenge(get_async_redis(), ctx.session_hash, "add")
    if challenge is None:
        raise HTTPException(status_code=409, detail=START_AGAIN)
    rp_id, origin = passkeys.relying_party(request)
    try:
        row = passkeys.new_passkey(ctx.user, body.name, body.credential, challenge, rp_id, origin)
    except PasskeyError as exc:
        await audit.record(
            db,
            "auth.passkey_add_failed",
            request=request,
            actor=ctx.user,
            reason=str(exc),
            ok=False,
        )
        raise HTTPException(status_code=400, detail=str(exc)) from None
    taken = await db.scalar(
        select(AdminPasskey.id).where(AdminPasskey.credential_id == row.credential_id)
    )
    if taken is not None:
        raise HTTPException(status_code=409, detail="This passkey is already registered")
    db.add(row)
    await db.flush()
    await audit.record(
        db,
        "auth.passkey_added",
        request=request,
        actor=ctx.user,
        target_type="passkey",
        target_id=row.id,
        after={"name": row.name, "backed_up": row.backed_up, "transports": row.transports},
    )
    return passkey_out(row)


@router.delete("/passkeys/{passkey_id}", response_model=OkResponse)
async def remove_passkey(
    passkey_id: str,
    request: Request,
    ctx: AdminContext = Depends(require_sudo),
    db: AsyncSession = Depends(get_db),
) -> OkResponse:
    try:
        row = await db.get(AdminPasskey, uuid.UUID(passkey_id))
    except ValueError:
        row = None
    if row is None or row.user_id != ctx.user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such passkey")
    name = row.name
    await db.delete(row)
    await audit.record(
        db,
        "auth.passkey_removed",
        request=request,
        actor=ctx.user,
        target_type="passkey",
        target_id=passkey_id,
        before={"name": name},
    )
    return OkResponse()


# --- sudo -------------------------------------------------------------------------------------


@router.post("/sudo/passkey/options", response_model=PasskeyOptionsOut)
async def sudo_options(
    request: Request,
    ctx: AdminContext = Depends(current_admin),
    db: AsyncSession = Depends(get_db),
) -> PasskeyOptionsOut:
    found = await passkeys_of(db, ctx.user)
    if not found:
        raise HTTPException(status_code=409, detail=NO_PASSKEYS)
    redis = get_async_redis()
    await check_lock(redis, ctx.user)
    rp_id, _origin = passkeys.relying_party(request)
    options, challenge = passkeys.authentication_options(found, rp_id)
    await passkeys.remember_challenge(redis, ctx.session_hash, "sudo", challenge)
    return PasskeyOptionsOut(options=options)


@router.post("/sudo/passkey", response_model=SudoOut)
async def sudo_with_passkey(
    body: PasskeyAnswer,
    request: Request,
    ctx: AdminContext = Depends(current_admin),
    db: AsyncSession = Depends(get_db),
) -> SudoOut:
    redis = get_async_redis()
    user = ctx.user
    await check_lock(redis, user)
    challenge = await passkeys.take_challenge(redis, ctx.session_hash, "sudo")
    if challenge is None:
        raise HTTPException(status_code=409, detail=START_AGAIN)
    rp_id, origin = passkeys.relying_party(request)
    try:
        row = passkeys.matching(await passkeys_of(db, user), body.credential)
        sign_count, backed_up = passkeys.check_assertion(
            row, body.credential, challenge, rp_id, origin
        )
    except PasskeyError as exc:
        raise await code_failed(
            request, db, redis, user, "auth.sudo_failed", reason=str(exc), wrong=NOT_VERIFIED
        ) from None
    _used(row, sign_count, backed_up)
    await sessions.clear_code_failures(redis, str(user.id))
    now = time.time()
    ctx.session.sudo_until = now + sessions.SUDO_SECONDS
    await sessions.save_session(redis, ctx.session_hash, ctx.session, now)
    await audit.record(db, "auth.sudo", request=request, actor=user, after={"passkey": row.name})
    return SudoOut(sudo_until=datetime.fromtimestamp(ctx.session.sudo_until, UTC))
