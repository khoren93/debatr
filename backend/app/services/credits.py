"""Credit ledger. Every balance change goes through `apply_transaction*` so the
`credit_transactions` table is a complete, idempotent history of the balance.

Sync functions run in the worker (charging finished runs); async ones in the API.
"""

import logging
import uuid
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.models import CreditTransaction, Debate, User

logger = logging.getLogger(__name__)

PLACES = Decimal("0.000001")
ZERO = Decimal("0")


def to_usd(value: Any) -> Decimal:
    return Decimal(str(value or 0)).quantize(PLACES, rounding=ROUND_HALF_UP)


def _row(
    user: User,
    amount: Decimal,
    kind: str,
    description: str | None,
    debate_id: uuid.UUID | None,
    provider: str | None,
    provider_ref: str | None,
    meta: dict[str, Any] | None,
) -> CreditTransaction:
    return CreditTransaction(
        user_id=user.id,
        amount_usd=amount,
        balance_after_usd=user.credits_usd,
        kind=kind,
        description=description,
        debate_id=debate_id,
        provider=provider,
        provider_ref=provider_ref,
        meta_json=meta or {},
    )


def apply_transaction_sync(
    db: Session,
    user_id: uuid.UUID,
    amount: Any,
    kind: str,
    *,
    description: str | None = None,
    debate_id: uuid.UUID | None = None,
    provider: str | None = None,
    provider_ref: str | None = None,
    meta: dict[str, Any] | None = None,
) -> CreditTransaction | None:
    """Move `amount` (signed USD) on the user's balance. Returns None when the
    `provider_ref` was already applied (idempotent) or the user is gone."""
    amount = to_usd(amount)
    if provider_ref is not None:
        existing = db.scalar(
            select(CreditTransaction.id).where(CreditTransaction.provider_ref == provider_ref)
        )
        if existing is not None:
            return None
    user = db.execute(select(User).where(User.id == user_id).with_for_update()).scalar_one_or_none()
    if user is None:
        return None
    user.credits_usd = to_usd(user.credits_usd) + amount
    tx = _row(user, amount, kind, description, debate_id, provider, provider_ref, meta)
    db.add(tx)
    db.commit()
    return tx


async def apply_transaction(
    db: AsyncSession,
    user_id: uuid.UUID,
    amount: Any,
    kind: str,
    *,
    description: str | None = None,
    debate_id: uuid.UUID | None = None,
    provider: str | None = None,
    provider_ref: str | None = None,
    meta: dict[str, Any] | None = None,
) -> CreditTransaction | None:
    amount = to_usd(amount)
    if provider_ref is not None:
        existing = await db.scalar(
            select(CreditTransaction.id).where(CreditTransaction.provider_ref == provider_ref)
        )
        if existing is not None:
            return None
    result = await db.execute(select(User).where(User.id == user_id).with_for_update())
    user = result.scalar_one_or_none()
    if user is None:
        return None
    user.credits_usd = to_usd(user.credits_usd) + amount
    tx = _row(user, amount, kind, description, debate_id, provider, provider_ref, meta)
    db.add(tx)
    await db.commit()
    return tx


# --- pricing helpers ---------------------------------------------------------


def uses_own_key(debate: Debate) -> bool:
    billing = (debate.config_json or {}).get("billing") or {}
    return bool(billing.get("own_key"))


def markup() -> Decimal:
    return Decimal(str(settings.CREDIT_MARKUP))


def debate_charge_usd(debate: Debate) -> Decimal:
    """Credits to charge for the LLM usage of a finished debate."""
    if uses_own_key(debate):
        return ZERO
    totals = debate.totals_json or {}
    cost = to_usd(totals.get("cost") or 0)
    return to_usd(cost * markup())


def tts_charge_usd(chars: int) -> Decimal:
    price = Decimal(str(settings.TTS_CREDIT_PRICE_PER_1K_CHARS))
    return to_usd(Decimal(max(0, chars)) / Decimal(1000) * price)


def charge_debate_sync(db: Session, debate: Debate) -> CreditTransaction | None:
    """Charge the owner for a finished/stopped/failed debate (idempotent per debate)."""
    if debate.user_id is None:
        return None
    amount = debate_charge_usd(debate)
    if amount <= ZERO:
        return None
    totals = debate.totals_json or {}
    return apply_transaction_sync(
        db,
        debate.user_id,
        -amount,
        "debate",
        description=(debate.title or "Debate")[:300],
        debate_id=debate.id,
        provider="system",
        provider_ref=f"debate:{debate.id}:llm",
        meta={
            "provider_cost_usd": float(totals.get("cost") or 0),
            "markup": float(markup()),
            "tokens_in": int(totals.get("tokens_in") or 0),
            "tokens_out": int(totals.get("tokens_out") or 0),
        },
    )


def charge_media_sync(
    db: Session, debate: Debate, *, chars: int, provider: str, own_key: bool, build_ref: str
) -> CreditTransaction | None:
    """Charge premium voices synthesized on the system key. Each build has its own ref."""
    if debate.user_id is None or own_key or provider != "elevenlabs":
        return None
    amount = tts_charge_usd(chars)
    if amount <= ZERO:
        return None
    return apply_transaction_sync(
        db,
        debate.user_id,
        -amount,
        "media",
        description=f"Premium voices: {(debate.title or 'Debate')[:250]}",
        debate_id=debate.id,
        provider="system",
        provider_ref=f"debate:{debate.id}:media:{build_ref}",
        meta={"chars": chars, "price_per_1k": settings.TTS_CREDIT_PRICE_PER_1K_CHARS},
    )


def has_balance(debate: Debate) -> bool:
    """Paid system-key extras (AI pictures) need money on the owner's balance; ownerless legacy
    rows are run by the admin."""
    return debate.user is None or to_usd(debate.user.credits_usd) > ZERO


def charge_images_sync(
    db: Session, debate: Debate, *, usd: float, count: int, build_ref: str
) -> CreditTransaction | None:
    """Charge the AI pictures of a media build (provider cost x markup)."""
    if debate.user_id is None:
        return None
    amount = to_usd(to_usd(usd) * markup())
    if amount <= ZERO:
        return None
    return apply_transaction_sync(
        db,
        debate.user_id,
        -amount,
        "media",
        description=f"AI pictures: {(debate.title or 'Debate')[:250]}",
        debate_id=debate.id,
        provider="system",
        provider_ref=f"debate:{debate.id}:images:{build_ref}",
        meta={"images": count, "provider_cost_usd": usd, "markup": float(markup())},
    )
