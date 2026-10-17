"""Credits and payments.

- GET  /api/billing/config        top-up amounts, payment mode, prices
- POST /api/billing/checkout      start a Stripe Checkout (or credit instantly in dev mode)
- GET  /api/billing/confirm       credit a paid Checkout session (success page fallback)
- POST /api/billing/webhook       Stripe webhook (checkout.session.completed)
- GET  /api/billing/transactions  ledger
- GET  /api/billing/usage         this month's consumption
"""

import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import stripe
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
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
from app.services.credits import apply_transaction
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
        description=tx.description,
        debate_id=str(tx.debate_id) if tx.debate_id else None,
        provider=tx.provider,
        created_at=tx.created_at,
    )


@router.get("/config", response_model=BillingConfigOut)
async def billing_config() -> BillingConfigOut:
    elevenlabs_ok, elevenlabs_reason = await run_in_threadpool(system_key_status)
    return BillingConfigOut(
        topup_amounts=settings.topup_amounts,
        currency=settings.STRIPE_CURRENCY,
        payments_mode=settings.payments_mode,  # type: ignore[arg-type]
        signup_bonus_usd=settings.SIGNUP_BONUS_USD,
        credit_markup=settings.CREDIT_MARKUP,
        tts_price_per_1k_chars=settings.TTS_CREDIT_PRICE_PER_1K_CHARS,
        tts_price_per_min=round(settings.TTS_CREDIT_PRICE_PER_1K_CHARS, 4),
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
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> list[TransactionOut]:
    stmt = (
        select(CreditTransaction)
        .where(CreditTransaction.user_id == user.id)
        .order_by(CreditTransaction.created_at.desc())
        .limit(limit)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [transaction_out(tx) for tx in rows]


@router.get("/usage", response_model=UsageOut)
async def usage(user: User = Depends(require_user), db: AsyncSession = Depends(get_db)) -> UsageOut:
    now = datetime.now(UTC)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    debates = (
        (
            await db.execute(
                select(Debate).where(Debate.user_id == user.id, Debate.created_at >= start)
            )
        )
        .scalars()
        .all()
    )
    out = UsageOut(period_start=start, debates=len(debates))
    for d in debates:
        totals = d.totals_json or {}
        out.tokens_in += int(totals.get("tokens_in") or 0)
        out.tokens_out += int(totals.get("tokens_out") or 0)
        media = d.media_json or {}
        if d.media_status == "ready":
            out.voice_ms += int((media.get("stats") or {}).get("total_ms") or 0)
        out.renders += sum(int(v or 0) for v in (media.get("renders") or {}).values())
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
    for tx in txs:
        amount = float(tx.amount_usd)
        if amount < 0:
            out.spent_usd += -amount
            if tx.kind == "debate":
                out.llm_usd += -amount
            elif tx.kind == "media":
                out.tts_usd += -amount
        elif tx.kind in ("topup", "bonus", "refund"):
            out.topped_up_usd += amount
    out.spent_usd = round(out.spent_usd, 6)
    out.topped_up_usd = round(out.topped_up_usd, 6)
    out.llm_usd = round(out.llm_usd, 6)
    out.tts_usd = round(out.tts_usd, 6)
    return out
