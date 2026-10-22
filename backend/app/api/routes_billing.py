"""Credits and payments.

- GET  /api/billing/config        top-up amounts, payment mode, prices
- POST /api/billing/checkout      start a Stripe Checkout (or credit instantly in dev mode)
- GET  /api/billing/confirm       credit a paid Checkout session (success page fallback)
- POST /api/billing/webhook       Stripe webhook (checkout.session.completed)
- GET  /api/billing/transactions  ledger (newest first, paged with limit/offset)
- GET  /api/billing/transactions.csv  the whole ledger as a CSV download
- GET  /api/billing/usage         this month's consumption (totals + per-day buckets)
"""

import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import stripe
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.auth import require_session_user, require_user
from app.core.config import settings
from app.core.db import get_db
from app.core.security import random_token
from app.models.models import CreditTransaction, Debate, User
from app.schemas.billing import (
    BillingConfigOut,
    CheckoutOut,
    CheckoutRequest,
    ConfirmOut,
    TransactionOut,
    UsageOut,
)
from app.services import email_check, ledger, runtime_settings
from app.services.credits import apply_transaction, cover_charge_usd
from app.services.estimate import reference_debate_usd
from app.services.media.tts.elevenlabs import system_key_status

logger = logging.getLogger(__name__)
router = APIRouter()


def _site() -> str:
    return settings.SITE_URL.rstrip("/")


def _stripe() -> stripe.StripeClient:
    if not settings.STRIPE_SECRET_KEY:
        raise HTTPException(status_code=503, detail="Payments are not configured")
    return stripe.StripeClient(settings.STRIPE_SECRET_KEY)


def transaction_out(tx: CreditTransaction) -> TransactionOut:
    return TransactionOut(
        id=str(tx.id),
        amount_usd=float(tx.amount_usd),
        balance_after_usd=float(tx.balance_after_usd),
        kind=tx.kind,
        category=ledger.category(tx),
        title=ledger.title(tx),
        description=tx.description,
        debate_id=str(tx.debate_id) if tx.debate_id else None,
        provider=tx.provider,
        created_at=tx.created_at,
    )


@router.get("/config", response_model=BillingConfigOut)
async def billing_config() -> BillingConfigOut:
    elevenlabs_ok, elevenlabs_reason = await run_in_threadpool(system_key_status)
    levers = await runtime_settings.current()
    cover = cover_charge_usd(settings.COVER_PRICE_USD, levers.credit_markup)
    debate_usd, voiced_debate_usd = reference_debate_usd(
        markup=levers.credit_markup,
        min_charge=levers.min_debate_charge_usd,
        tts_price_per_1k=levers.tts_price_per_1k_chars,
        cover_usd=0.0 if levers.ai_covers == "off" else float(cover),
    )
    return BillingConfigOut(
        topup_amounts=settings.topup_amounts,
        currency=settings.STRIPE_CURRENCY,
        payments_mode=settings.payments_mode,  # type: ignore[arg-type]
        signup_bonus_usd=levers.signup_bonus_usd,
        tts_price_per_1k_chars=levers.tts_price_per_1k_chars,
        tts_price_per_min=round(levers.tts_price_per_1k_chars, 4),
        music_price_per_min=levers.music_price_per_min,
        debate_usd=debate_usd,
        voiced_debate_usd=voiced_debate_usd,
        elevenlabs_available=elevenlabs_ok,
        elevenlabs_error=elevenlabs_reason,
    )


def _create_checkout(user: User, amount: int) -> str:
    session = _stripe().v1.checkout.sessions.create(
        {
            "mode": "payment",
            "line_items": [
                {
                    "quantity": 1,
                    "price_data": {
                        "currency": settings.STRIPE_CURRENCY,
                        "unit_amount": amount * 100,
                        "product_data": {
                            "name": f"{settings.PROJECT_NAME} credits",
                            "description": f"${amount} of debate credits",
                        },
                    },
                }
            ],
            "success_url": f"{_site()}/account?topup=success&session_id={{CHECKOUT_SESSION_ID}}",
            "cancel_url": f"{_site()}/account?topup=cancel",
            "client_reference_id": str(user.id),
            "customer_email": user.email,
            "metadata": {"user_id": str(user.id), "amount_usd": str(amount)},
        }
    )
    if not session.url:
        raise HTTPException(status_code=502, detail="Stripe did not return a checkout URL")
    return session.url


@router.post("/checkout", response_model=CheckoutOut)
async def checkout(
    body: CheckoutRequest,
    user: User = Depends(require_session_user),
    db: AsyncSession = Depends(get_db),
) -> CheckoutOut:
    if body.amount_usd not in settings.topup_amounts:
        raise HTTPException(status_code=400, detail="Unsupported top-up amount")
    if email_check.pending(user):
        raise HTTPException(
            status_code=403,
            detail=f"Confirm your email before adding credits: open the link we sent to "
            f"{user.email}.",
        )
    mode = settings.payments_mode
    if mode == "dev":
        await apply_transaction(
            db,
            user.id,
            body.amount_usd,
            "topup",
            description=f"Top-up ${body.amount_usd} (development)",
            provider="dev",
            provider_ref=f"dev:{random_token(12)}",
        )
        return CheckoutOut(url=f"{_site()}/account?topup=success", instant=True)
    if mode != "stripe":
        raise HTTPException(status_code=503, detail="Payments coming soon")
    try:
        url = await run_in_threadpool(_create_checkout, user, body.amount_usd)
    except stripe.StripeError as e:
        logger.warning("Stripe checkout failed: %s", e)
        raise HTTPException(status_code=502, detail=f"Stripe error: {e.user_message or e}") from e
    return CheckoutOut(url=url)


async def _credit_checkout_session(
    db: AsyncSession, session: Any, *, expected_user: User | None = None
) -> CreditTransaction | None:
    """Credit a paid Checkout session exactly once (keyed by the session id)."""
    if session.get("payment_status") != "paid":
        return None
    metadata = session.get("metadata") or {}
    raw_user = session.get("client_reference_id") or metadata.get("user_id")
    try:
        user_id = uuid.UUID(str(raw_user))
    except ValueError:
        logger.error("Checkout session %s has no user reference", session.get("id"))
        return None
    if expected_user is not None and expected_user.id != user_id:
        raise HTTPException(status_code=403, detail="This payment belongs to another account")
    amount = Decimal(int(session.get("amount_total") or 0)) / Decimal(100)
    if amount <= 0:
        return None
    payment_intent = session.get("payment_intent")
    return await apply_transaction(
        db,
        user_id,
        amount,
        "topup",
        description=f"Top-up ${amount:.2f}",
        provider="stripe",
        provider_ref=f"stripe:{session.get('id')}",
        meta={
            "payment_intent": payment_intent
            if isinstance(payment_intent, str)
            else getattr(payment_intent, "id", None),
            "currency": session.get("currency"),
        },
    )


@router.post("/webhook", status_code=status.HTTP_200_OK)
async def stripe_webhook(request: Request, db: AsyncSession = Depends(get_db)) -> dict[str, bool]:
    if not settings.STRIPE_WEBHOOK_SECRET:
        raise HTTPException(status_code=503, detail="Webhook secret is not configured")
    payload = await request.body()
    signature = request.headers.get("stripe-signature")
    try:
        event = _stripe().construct_event(payload, signature, settings.STRIPE_WEBHOOK_SECRET)
    except (ValueError, stripe.SignatureVerificationError) as e:
        raise HTTPException(status_code=400, detail="Invalid webhook signature") from e
    # Delayed payment methods are still unpaid at "completed" and settle with the async event.
    if event.type in ("checkout.session.completed", "checkout.session.async_payment_succeeded"):
        tx = await _credit_checkout_session(db, event.data.object)
        if tx is not None:
            logger.info("Credited %s via Stripe webhook", tx.user_id)
    return {"received": True}


@router.get("/confirm", response_model=ConfirmOut)
async def confirm_checkout(
    session_id: str = Query(min_length=8, max_length=200),
    user: User = Depends(require_session_user),
    db: AsyncSession = Depends(get_db),
) -> ConfirmOut:
    """Called by the success page: credits the session if the webhook has not done it yet."""
    try:
        session = await run_in_threadpool(_stripe().v1.checkout.sessions.retrieve, session_id)
    except stripe.StripeError as e:
        raise HTTPException(status_code=400, detail=f"Stripe error: {e.user_message or e}") from e
    tx = await _credit_checkout_session(db, session, expected_user=user)
    await db.refresh(user)
    return ConfirmOut(
        credited=tx is not None,
        amount_usd=float(tx.amount_usd) if tx else None,
        credits_usd=float(user.credits_usd or 0),
    )


@router.get("/transactions", response_model=list[TransactionOut])
async def list_transactions(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> list[TransactionOut]:
    stmt = (
        select(CreditTransaction)
        .where(CreditTransaction.user_id == user.id)
        .order_by(CreditTransaction.created_at.desc(), CreditTransaction.id.desc())
        .offset(offset)
        .limit(limit)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [transaction_out(tx) for tx in rows]


@router.get("/transactions.csv")
async def export_transactions(
    user: User = Depends(require_user), db: AsyncSession = Depends(get_db)
) -> Response:
    stmt = (
        select(CreditTransaction)
        .where(CreditTransaction.user_id == user.id)
        .order_by(CreditTransaction.created_at.desc(), CreditTransaction.id.desc())
    )
    rows = (await db.execute(stmt)).scalars().all()
    filename = f"{ledger.slug(settings.PROJECT_NAME)}-ledger-{datetime.now(UTC):%Y-%m-%d}.csv"
    return Response(
        content=ledger.ledger_csv(rows),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/usage", response_model=UsageOut)
async def usage(user: User = Depends(require_user), db: AsyncSession = Depends(get_db)) -> UsageOut:
    now = datetime.now(UTC)
    start = ledger.month_start(now)
    debates = (
        (
            await db.execute(
                select(Debate).where(Debate.user_id == user.id, Debate.created_at >= start)
            )
        )
        .scalars()
        .all()
    )
    txs = (
        (
            await db.execute(
                select(CreditTransaction).where(
                    CreditTransaction.user_id == user.id, CreditTransaction.created_at >= start
                )
            )
        )
        .scalars()
        .all()
    )
    return ledger.build_usage(now, debates, txs)
