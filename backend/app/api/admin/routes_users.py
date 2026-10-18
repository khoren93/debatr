"""Accounts in the admin console (`/api/admin/users*`): list, CSV, card, ledger and debates of
an account, and the changes an admin makes to it.

Reads run in a read-only transaction (`access.read_only_db`). Every change names a reason and
is written to the audit log in the same transaction as the change itself. Money moves only
through the ledger (`credits.apply_transaction`, `provider_ref = admin:<idempotency key>`, so a
repeated request never moves it twice) and needs the `money` permission; amounts above
ADMIN_SUDO_USD, the CSV, temporary passwords and deletion need a fresh TOTP code (sudo).
Admin accounts (and the admin's own) are disabled, deleted or given passwords only on the server
(`python -m app.manage`), so a stolen console session cannot take over another admin.
"""

import logging
import shutil
import time
import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.admin.access import AdminContext, read_only_db, require_admin, sudo_required
from app.core.config import settings
from app.core.db import get_db
from app.core.redis import get_async_redis, stop_flag_key
from app.core.security import hash_password
from app.models.models import ApiToken, CreditTransaction, Debate, User, utcnow
from app.schemas.admin import (
    AdminLedgerPage,
    AdminUserCard,
    AdminUserDebatePage,
    AdminUserList,
    CountOut,
    CreditChangeOut,
    CreditChangeRequest,
    DeleteUserOut,
    DeleteUserRequest,
    DisableUserOut,
    DisableUserRequest,
    ReasonRequest,
    RevokeTokensRequest,
    TemporaryPasswordOut,
    UserExportQuery,
    UserFilters,
    UserListQuery,
)
from app.services.admin import audit
from app.services.admin import users as accounts
from app.services.api_tokens import spent_by_tokens, token_out
from app.services.credits import (
    MANUAL_DESCRIPTIONS,
    apply_transaction,
    check_manual_change,
    lock_balance,
    to_usd,
)
from app.services.debate_control import ACTIVE_STATUSES, mark_stopped, signal_stopped
from app.services.ledger import slug
from app.services.media.paths import MediaPaths

logger = logging.getLogger(__name__)
router = APIRouter()

read_users = require_admin("users")


def _uuid(raw: str) -> uuid.UUID:
    try:
        return uuid.UUID(raw)
    except ValueError:
        raise HTTPException(status_code=404, detail="No such account") from None


async def _account(db: AsyncSession, user_id: str) -> User:
    user = await db.get(User, _uuid(user_id))
    if user is None:
        raise HTTPException(status_code=404, detail="No such account")
    return user


def _unprotected(ctx: AdminContext, user: User) -> None:
    """Disabling, deleting and passwords: never the admin's own account or another admin's."""
    if user.id == ctx.user.id:
        raise HTTPException(status_code=409, detail="Not on your own account")
    if user.admin_role:
        raise HTTPException(
            status_code=409,
            detail="Admin accounts are changed on the server (python -m app.manage admin …)",
        )


def _sudo(ctx: AdminContext) -> None:
    if not ctx.session.is_sudo(time.time()):
        raise sudo_required()


async def _record(
    db: AsyncSession,
    ctx: AdminContext,
    request: Request,
    action: str,
    user: User,
    reason: str,
    **changes: object,
) -> None:
    await audit.record(
        db,
        action,
        request=request,
        actor=ctx.user,
        target_type="user",
        target_id=user.id,
        reason=reason,
        before={"email": user.email},
        after=dict(changes) or None,
        commit=False,
    )


# --- reading ------------------------------------------------------------------------------------


def _filters(query: UserExportQuery) -> UserFilters:
    return UserFilters.model_validate(query.model_dump(include=set(UserFilters.model_fields)))


@router.get("/users", response_model=AdminUserList)
async def list_users(
    query: Annotated[UserListQuery, Query()],
    _ctx: AdminContext = Depends(read_users),
    db: AsyncSession = Depends(read_only_db),
) -> AdminUserList:
    total, rows = await accounts.list_users(
        db,
        _filters(query),
        sort=query.sort,
        descending=query.order == "desc",
        limit=query.limit,
        offset=query.offset,
        now=utcnow(),
    )
    return AdminUserList.model_validate(
        {"total": total, "limit": query.limit, "offset": query.offset, "rows": rows}
    )


@router.post("/users/export")
async def export_users(
    request: Request,
    query: Annotated[UserExportQuery, Query()],
    ctx: AdminContext = Depends(read_users),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """The filtered list as CSV (sudo; written to the audit log)."""
    _sudo(ctx)
    filters = _filters(query)
    total, rows = await accounts.list_users(
        db,
        filters,
        sort=query.sort,
        descending=query.order == "desc",
        limit=accounts.EXPORT_LIMIT,
        offset=0,
        now=utcnow(),
    )
    await audit.record(
        db,
        "users.exported",
        request=request,
        actor=ctx.user,
        target_type="users",
        after={
            "filters": filters.model_dump(exclude_defaults=True, mode="json"),
            "rows": len(rows),
        },
    )
    name = f"{slug(settings.PROJECT_NAME)}-users-{utcnow():%Y%m%d-%H%M}.csv"
    headers = {"Content-Disposition": f'attachment; filename="{name}"', "X-Total-Count": str(total)}
    return Response(accounts.users_csv(rows), media_type="text/csv", headers=headers)


@router.get("/users/{user_id}", response_model=AdminUserCard)
async def user_card(
    user_id: str,
    _ctx: AdminContext = Depends(read_users),
    db: AsyncSession = Depends(read_only_db),
) -> AdminUserCard:
    user = await _account(db, user_id)
    now = utcnow()
    month = now - timedelta(days=accounts.CARD_DAYS)
    debates = await accounts.debate_facts(db, user.id)
    txs = await accounts.tx_facts(db, user.id)
    tokens = list(
        (
            await db.scalars(
                select(ApiToken)
                .where(ApiToken.user_id == user.id)
                .order_by(ApiToken.created_at.desc())
            )
        ).all()
    )
    spent = await spent_by_tokens(db, [t.id for t in tokens])
    return AdminUserCard.model_validate(
        {
            "profile": accounts.profile_out(user),
            "all_time": accounts.period_stats(
                debates, txs, since=None, cost_system=await accounts.system_cost(db, user.id, None)
            ),
            "last_30_days": accounts.period_stats(
                debates,
                txs,
                since=month,
                cost_system=await accounts.system_cost(db, user.id, month),
            ),
            "favorite_models": accounts.favorite_models(debates),
            "spend_days": accounts.spend_days(txs, now),
            "tokens": [token_out(t, spent.get(t.id, Decimal(0))) for t in tokens],
            "reactions": await accounts.reactions(db, user.id),
            "audit": await accounts.audit_entries(db, user.id),
            "active_debates": await accounts.count_debates(
                db, user.id, Debate.status.in_(ACTIVE_STATUSES)
            ),
            "public_debates": await accounts.count_debates(db, user.id, Debate.is_public.is_(True)),
            "protected": user.admin_role is not None,
        }
    )


@router.get("/users/{user_id}/ledger", response_model=AdminLedgerPage)
async def user_ledger(
    user_id: str,
    limit: int = Query(default=50, ge=1, le=accounts.LIST_LIMIT),
    offset: int = Query(default=0, ge=0),
    _ctx: AdminContext = Depends(require_admin("money")),
    db: AsyncSession = Depends(read_only_db),
) -> AdminLedgerPage:
    user = await _account(db, user_id)
    total, rows = await accounts.ledger_page(db, user.id, limit=limit, offset=offset)
    return AdminLedgerPage.model_validate({"total": total, "rows": rows})


@router.get("/users/{user_id}/debates", response_model=AdminUserDebatePage)
async def user_debates(
    user_id: str,
    limit: int = Query(default=20, ge=1, le=accounts.LIST_LIMIT),
    offset: int = Query(default=0, ge=0),
    _ctx: AdminContext = Depends(read_users),
    db: AsyncSession = Depends(read_only_db),
) -> AdminUserDebatePage:
    user = await _account(db, user_id)
    total, rows = await accounts.debates_page(db, user.id, limit=limit, offset=offset)
    return AdminUserDebatePage.model_validate({"total": total, "rows": rows})


# --- changes ------------------------------------------------------------------------------------


async def _applied(db: AsyncSession, ref: str, user: User) -> CreditChangeOut | None:
    """The answer of a change already made with this idempotency key."""
    tx = await db.scalar(select(CreditTransaction).where(CreditTransaction.provider_ref == ref))
    if tx is None:
        return None
    if tx.user_id != user.id:
        raise HTTPException(status_code=409, detail="This request was used for another account")
    after = to_usd(tx.balance_after_usd)
    return CreditChangeOut(
        transaction_id=str(tx.id),
        balance_before=float(after - to_usd(tx.amount_usd)),
        balance_after=float(after),
        duplicate=True,
    )


@router.post("/users/{user_id}/credits", response_model=CreditChangeOut)
async def change_credits(
    user_id: str,
    body: CreditChangeRequest,
    request: Request,
    ctx: AdminContext = Depends(require_admin("money")),
    db: AsyncSession = Depends(get_db),
) -> CreditChangeOut:
    """Add or take credits: a ledger row (adjustment / bonus / refund) the user sees with its
    description; the reason stays internal."""
    user = await _account(db, user_id)
    ref = f"admin:{body.idempotency_key}"
    done = await _applied(db, ref, user)
    if done is not None:
        return done
    amount = body.amount
    try:
        check_manual_change(amount, body.kind)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    amount = to_usd(amount)
    if abs(amount) > to_usd(settings.ADMIN_SUDO_USD):
        _sudo(ctx)
    text = (body.description or "").strip()[:300] or MANUAL_DESCRIPTIONS[body.kind]
    before = await lock_balance(db, user.id)
    if before is None:
        raise HTTPException(status_code=404, detail="No such account")
    await _record(
        db,
        ctx,
        request,
        "credits.changed",
        user,
        body.reason,
        amount_usd=str(amount),
        kind=body.kind,
        description=text,
        balance_before=str(before),
        balance_after=str(before + amount),
        provider_ref=ref,
    )
    try:
        tx = await apply_transaction(
            db,
            user.id,
            amount,
            body.kind,
            description=text,
            provider="admin",
            provider_ref=ref,
            meta={"reason": body.reason, "source": "console", "admin": ctx.user.email},
        )
    except IntegrityError:
        # The same key raced in from a second request: report that one.
        await db.rollback()
        done = await _applied(db, ref, user)
        if done is None:
            raise
        return done
    if tx is None:
        await db.rollback()
        done = await _applied(db, ref, user)
        if done is None:
            raise HTTPException(status_code=404, detail="No such account")
        return done
    logger.info("Admin %s: %s USD (%s) for %s", ctx.user.email, amount, body.kind, user.email)
    return CreditChangeOut(
        transaction_id=str(tx.id),
        balance_before=float(before),
        balance_after=float(tx.balance_after_usd),
        duplicate=False,
    )


@router.post("/users/{user_id}/disable", response_model=DisableUserOut)
async def disable_user(
    user_id: str,
    body: DisableUserRequest,
    request: Request,
    ctx: AdminContext = Depends(read_users),
    db: AsyncSession = Depends(get_db),
) -> DisableUserOut:
    """Sign-ins, cookies and tokens stop working at once (`is_active`); the epoch bump keeps
    old cookies dead if the account is enabled again."""
    user = await _account(db, user_id)
    _unprotected(ctx, user)
    if not user.is_active:
        raise HTTPException(status_code=409, detail="The account is already disabled")
    stopped = await accounts.active_debates(db, user.id) if body.stop_debates else []
    for debate in stopped:
        mark_stopped(debate)
    revoked = await accounts.revoke_tokens(db, user.id) if body.revoke_tokens else 0
    unpublished = await accounts.unpublish_all(db, user.id) if body.unpublish else 0
    user.is_active = False
    user.session_epoch += 1
    await _record(
        db,
        ctx,
        request,
        "user.disabled",
        user,
        body.reason,
        stopped=len(stopped),
        tokens_revoked=revoked,
        unpublished=unpublished,
    )
    await db.commit()
    for debate in stopped:
        await signal_stopped(str(debate.id))
    return DisableUserOut(stopped=len(stopped), tokens_revoked=revoked, unpublished=unpublished)


@router.post("/users/{user_id}/enable", response_model=CountOut)
async def enable_user(
    user_id: str,
    body: ReasonRequest,
    request: Request,
    ctx: AdminContext = Depends(read_users),
    db: AsyncSession = Depends(get_db),
) -> CountOut:
    user = await _account(db, user_id)
    _unprotected(ctx, user)
    if user.is_active:
        raise HTTPException(status_code=409, detail="The account is already active")
    user.is_active = True
    await _record(db, ctx, request, "user.enabled", user, body.reason)
    await db.commit()
    return CountOut(count=1)


@router.post("/users/{user_id}/tokens/revoke", response_model=CountOut)
async def revoke_user_tokens(
    user_id: str,
    body: RevokeTokensRequest,
    request: Request,
    ctx: AdminContext = Depends(read_users),
    db: AsyncSession = Depends(get_db),
) -> CountOut:
    """Revoke one API token, or all of them (`token_id` left out)."""
    user = await _account(db, user_id)
    revoked = await accounts.revoke_tokens(db, user.id, body.token_id)
    if not revoked:
        raise HTTPException(status_code=404, detail="No such token")
    await _record(
        db,
        ctx,
        request,
        "user.tokens_revoked",
        user,
        body.reason,
        token_id=str(body.token_id) if body.token_id else "all",
        revoked=revoked,
    )
    await db.commit()
    return CountOut(count=revoked)


@router.post("/users/{user_id}/openrouter-key/remove", response_model=CountOut)
async def remove_openrouter_key(
    user_id: str,
    body: ReasonRequest,
    request: Request,
    ctx: AdminContext = Depends(read_users),
    db: AsyncSession = Depends(get_db),
) -> CountOut:
    user = await _account(db, user_id)
    if user.openrouter_key_enc is None:
        raise HTTPException(status_code=409, detail="No stored OpenRouter key")
    last4 = user.openrouter_key_last4
    user.openrouter_key_enc = None
    user.openrouter_key_last4 = None
    await _record(db, ctx, request, "user.openrouter_key_removed", user, body.reason, last4=last4)
    await db.commit()
    return CountOut(count=1)


@router.post("/users/{user_id}/sign-out", response_model=CountOut)
async def sign_out_everywhere(
    user_id: str,
    body: ReasonRequest,
    request: Request,
    ctx: AdminContext = Depends(read_users),
    db: AsyncSession = Depends(get_db),
) -> CountOut:
    """End every session of the account: site cookies and console sessions (API tokens are
    revoked on their own)."""
    user = await _account(db, user_id)
    if user.id == ctx.user.id:
        raise HTTPException(status_code=409, detail="Use the Security page for your own sessions")
    user.session_epoch += 1
    await _record(db, ctx, request, "user.signed_out", user, body.reason)
    await db.commit()
    return CountOut(count=1)


@router.post("/users/{user_id}/temporary-password", response_model=TemporaryPasswordOut)
async def set_temporary_password(
    user_id: str,
    body: ReasonRequest,
    request: Request,
    ctx: AdminContext = Depends(read_users),
    db: AsyncSession = Depends(get_db),
) -> TemporaryPasswordOut:
    """A new random password, shown once (there is no reset by email yet). Every session of
    the account ends."""
    _sudo(ctx)
    user = await _account(db, user_id)
    _unprotected(ctx, user)
    password = accounts.temporary_password()
    user.password_hash = await run_in_threadpool(hash_password, password)
    user.session_epoch += 1
    await _record(db, ctx, request, "user.temporary_password", user, body.reason)
    await db.commit()
    return TemporaryPasswordOut(temporary_password=password)


@router.post("/users/{user_id}/delete", response_model=DeleteUserOut)
async def delete_user(
    user_id: str,
    body: DeleteUserRequest,
    request: Request,
    ctx: AdminContext = Depends(read_users),
    db: AsyncSession = Depends(get_db),
) -> DeleteUserOut:
    """Delete the account and its debates with their files (not left ownerless: anyone with
    the link could read those). The audit log keeps what was deleted."""
    _sudo(ctx)
    user = await _account(db, user_id)
    _unprotected(ctx, user)
    if body.confirm_email != user.email:
        raise HTTPException(status_code=422, detail="Type the account's email to confirm")
    snapshot = {
        "email": user.email,
        "display_name": user.display_name,
        "created_at": user.created_at,
        "credits_usd": str(to_usd(user.credits_usd)),
    }
    target = user.id
    deleted = await accounts.delete_account(db, user)
    await audit.record(
        db,
        "user.deleted",
        request=request,
        actor=ctx.user,
        target_type="user",
        target_id=target,
        reason=body.reason,
        before=snapshot,
        after={"debates": len(deleted.debate_ids)},
        commit=False,
    )
    await db.commit()
    redis = get_async_redis()
    for debate_id in deleted.active_ids:
        try:
            await redis.set(stop_flag_key(debate_id), "1", ex=3600)
        except RedisError:  # the worker finds the debate gone anyway
            logger.warning("Could not set the stop flag of %s", debate_id)
    for debate_id in deleted.debate_ids:
        await run_in_threadpool(shutil.rmtree, MediaPaths(debate_id).dir, True)
    logger.info("Admin %s deleted the account %s", ctx.user.email, snapshot["email"])
    return DeleteUserOut(debates=len(deleted.debate_ids))
