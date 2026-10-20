"""Credit ledger. Every balance change goes through `apply_transaction*` so the
`credit_transactions` table is a complete, idempotent history of the balance.

Sync functions run in the worker (charging finished runs); async ones in the API.
"""

import logging
import uuid
from dataclasses import asdict, dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.models import CreditTransaction, Debate, User

if TYPE_CHECKING:
    from app.services.runtime_settings import Levers

logger = logging.getLogger(__name__)

PLACES = Decimal("0.000001")
ZERO = Decimal("0")

# Manual changes by an operator (`python -m app.manage credits`, the admin console).
MANUAL_KINDS = ("adjustment", "bonus", "refund")
MANUAL_DESCRIPTIONS = {
    "adjustment": "Balance adjustment",
    "bonus": "Bonus credits",
    "refund": "Refund",
}
# One manual change never moves more than this, so a slip ("500" for "5.00") stays small.
MAX_MANUAL_USD = Decimal("1000")


def to_usd(value: Any) -> Decimal:
    return Decimal(str(value or 0)).quantize(PLACES, rounding=ROUND_HALF_UP)


def _locked_user(user_id: uuid.UUID) -> Select[User]:
    """The user row, locked until commit, with the balance read again from that row:
    without `populate_existing` a User already loaded in the session keeps its old balance, and
    a charge or top-up committed meanwhile would be overwritten."""
    return (
        select(User)
        .where(User.id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


async def lock_balance(db: AsyncSession, user_id: uuid.UUID) -> Decimal | None:
    """The user's balance with the row locked until commit (None when the account is gone), for
    callers that record the balance before a change in the same transaction."""
    user = (await db.execute(_locked_user(user_id))).scalar_one_or_none()
    return to_usd(user.credits_usd) if user is not None else None


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
    user = db.execute(_locked_user(user_id)).scalar_one_or_none()
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
    result = await db.execute(_locked_user(user_id))
    user = result.scalar_one_or_none()
    if user is None:
        return None
    user.credits_usd = to_usd(user.credits_usd) + amount
    tx = _row(user, amount, kind, description, debate_id, provider, provider_ref, meta)
    db.add(tx)
    await db.commit()
    return tx


def check_manual_change(amount: Decimal, kind: str) -> None:
    """A manual change is one of MANUAL_KINDS, not zero and at most MAX_MANUAL_USD; bonuses and
    refunds only add (taking credits is an adjustment)."""
    if kind not in MANUAL_KINDS:
        raise ValueError(f"Unknown kind {kind!r}")
    if not amount.is_finite() or to_usd(amount) == 0:
        raise ValueError("The amount must not be zero")
    if abs(to_usd(amount)) > MAX_MANUAL_USD:
        raise ValueError(f"At most {MAX_MANUAL_USD} USD at a time")
    if kind != "adjustment" and amount < 0:
        raise ValueError(f"A {kind} adds credits: use a positive amount, or an adjustment")


# --- pricing helpers ---------------------------------------------------------


def uses_own_key(debate: Debate) -> bool:
    billing = (debate.config_json or {}).get("billing") or {}
    return bool(billing.get("own_key"))


@dataclass(frozen=True)
class Prices:
    """What a run charges: provider cost x `markup` (models, fact-checks, AI pictures), at least
    `min_charge` for a completed paid debate, `voices_per_1k` per 1000 premium-voice characters.
    A run keeps the prices it was quoted (`config_json.billing.prices`, `media_json.prices`);
    rows from before that take the env settings, which they were quoted with."""

    markup: float
    min_charge: float
    voices_per_1k: float
    music_per_min: float

    def as_dict(self) -> dict[str, float]:
        return asdict(self)


def env_prices() -> Prices:
    return Prices(
        markup=settings.CREDIT_MARKUP,
        min_charge=settings.MIN_DEBATE_CHARGE_USD,
        voices_per_1k=settings.TTS_CREDIT_PRICE_PER_1K_CHARS,
        music_per_min=settings.MUSIC_CREDIT_PRICE_PER_MIN,
    )


def lever_prices(levers: "Levers") -> Prices:
    """Today's prices: the admin console's levers (services/runtime_settings.Levers)."""
    return Prices(
        markup=levers.credit_markup,
        min_charge=levers.min_debate_charge_usd,
        voices_per_1k=levers.tts_price_per_1k_chars,
        music_per_min=levers.music_price_per_min,
    )


def prices_of(state: dict[str, Any] | None) -> Prices:
    """The prices stored with a run (`billing` / `media_json`), the env settings for rows
    without them."""
    stored = (state or {}).get("prices") or {}
    base = env_prices().as_dict()
    for key in base:
        try:
            base[key] = float(stored[key])
        except (KeyError, TypeError, ValueError):
            continue
    return Prices(**base)


def debate_prices(debate: Debate) -> Prices:
    return prices_of((debate.config_json or {}).get("billing"))


def debate_charge_usd(debate: Debate) -> Decimal:
    """Credits to charge for the LLM usage (models, fact-checks) of a debate: cost x markup, and
    at least the minimum once it completed (a stopped or failed run pays its usage only; a
    resumed run that completes pays up to the minimum, `charge_due`)."""
    if uses_own_key(debate):
        return ZERO
    totals = debate.totals_json or {}
    cost = to_usd(totals.get("cost") or 0)
    if cost <= ZERO:
        return ZERO
    prices = debate_prices(debate)
    amount = to_usd(cost * Decimal(str(prices.markup)))
    if debate.status == "completed":
        amount = max(amount, to_usd(prices.min_charge))
    return amount


def charge_due(total: Decimal, charged: Decimal) -> Decimal:
    """What is left to charge of `total` after earlier charges: a resumed run is charged again
    at its end, for what it added."""
    return max(ZERO, to_usd(total - charged))


def run_ref(prefix: str, earlier: int) -> str:
    """`provider_ref` of the next charge under `prefix` (the first one keeps the bare prefix)."""
    return prefix if earlier == 0 else f"{prefix}:{earlier + 1}"


def _charged_sync(db: Session, debate_id: uuid.UUID, prefix: str) -> tuple[int, Decimal]:
    """Charges already booked under `prefix`: (count, amount as a positive number)."""
    count, total = db.execute(
        select(
            func.count(CreditTransaction.id),
            func.coalesce(func.sum(CreditTransaction.amount_usd), 0),
        ).where(
            CreditTransaction.debate_id == debate_id,
            or_(
                CreditTransaction.provider_ref == prefix,
                CreditTransaction.provider_ref.like(f"{prefix}:%"),
            ),
        )
    ).one()
    return int(count), -to_usd(total)


def tts_charge_usd(chars: int, price_per_1k: float) -> Decimal:
    return to_usd(Decimal(max(0, chars)) / Decimal(1000) * Decimal(str(price_per_1k)))


def music_charge_usd(ms: int, price_per_min: float) -> Decimal:
    return to_usd(Decimal(max(0, ms)) / Decimal(60_000) * Decimal(str(price_per_min)))


def charge_debate_sync(db: Session, debate: Debate) -> CreditTransaction | None:
    """Charge the owner for a finished/stopped/failed debate: what its usage costs minus what
    earlier runs of it were charged (so repeating a charge, or a resumed run, is safe)."""
    if debate.user_id is None:
        return None
    amount = debate_charge_usd(debate)
    if amount <= ZERO:
        return None
    prefix = f"debate:{debate.id}:llm"
    earlier, charged = _charged_sync(db, debate.id, prefix)
    due = charge_due(amount, charged)
    if due <= ZERO:
        return None
    totals = debate.totals_json or {}
    return apply_transaction_sync(
        db,
        debate.user_id,
        -due,
        "debate",
        description=(debate.title or "Debate")[:300],
        debate_id=debate.id,
        provider="system",
        provider_ref=run_ref(prefix, earlier),
        meta={
            "provider_cost_usd": float(totals.get("cost") or 0),
            **debate_prices(debate).as_dict(),
            "tokens_in": int(totals.get("tokens_in") or 0),
            "tokens_out": int(totals.get("tokens_out") or 0),
        },
    )


def charge_media_sync(
    db: Session,
    debate: Debate,
    *,
    chars: int,
    provider: str,
    own_key: bool,
    build_ref: str,
    price_per_1k: float,
) -> CreditTransaction | None:
    """Charge premium voices synthesized on the system key. Each build has its own ref."""
    if debate.user_id is None or own_key or provider != "elevenlabs":
        return None
    amount = tts_charge_usd(chars, price_per_1k)
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
        meta={"chars": chars, "price_per_1k": price_per_1k},
    )


def charge_music_sync(
    db: Session,
    debate: Debate,
    *,
    ms: int,
    own_key: bool,
    build_ref: str,
    price_per_min: float,
) -> CreditTransaction | None:
    """Charge a rap battle's music generated on the system key (a cached track: nothing)."""
    if debate.user_id is None or own_key:
        return None
    amount = music_charge_usd(ms, price_per_min)
    if amount <= ZERO:
        return None
    return apply_transaction_sync(
        db,
        debate.user_id,
        -amount,
        "media",
        description=f"Music: {(debate.title or 'Rap battle')[:250]}",
        debate_id=debate.id,
        provider="system",
        provider_ref=f"debate:{debate.id}:music:{build_ref}",
        meta={"music_ms": ms, "price_per_min": price_per_min},
    )


def has_balance(debate: Debate) -> bool:
    """Paid system-key extras (AI pictures) need money on the owner's balance; ownerless legacy
    rows are run by the admin."""
    return debate.user is None or to_usd(debate.user.credits_usd) > ZERO


def charge_images_sync(
    db: Session, debate: Debate, *, usd: float, count: int, build_ref: str, markup: float
) -> CreditTransaction | None:
    """Charge the AI pictures of a media build or of the live scenes (`build_ref="live"`, again
    for the new pictures when a resumed run ends): provider cost x markup."""
    if debate.user_id is None:
        return None
    amount = to_usd(to_usd(usd) * Decimal(str(markup)))
    if amount <= ZERO:
        return None
    prefix = f"debate:{debate.id}:images:{build_ref}"
    earlier, charged = _charged_sync(db, debate.id, prefix)
    due = charge_due(amount, charged)
    if due <= ZERO:
        return None
    return apply_transaction_sync(
        db,
        debate.user_id,
        -due,
        "media",
        description=f"AI pictures: {(debate.title or 'Debate')[:250]}",
        debate_id=debate.id,
        provider="system",
        provider_ref=run_ref(prefix, earlier),
        meta={"images": count, "provider_cost_usd": usd, "markup": markup},
    )


def charge_cover_sync(
    db: Session, debate: Debate, *, usd: float, version_id: str, markup: float
) -> CreditTransaction | None:
    """Charge an AI cover drawn on the system key: its provider cost (art director and
    pictures) x markup, once per version."""
    if debate.user_id is None:
        return None
    amount = to_usd(to_usd(usd) * Decimal(str(markup)))
    if amount <= ZERO:
        return None
    return apply_transaction_sync(
        db,
        debate.user_id,
        -amount,
        "media",
        description=f"AI cover: {(debate.title or 'Debate')[:250]}",
        debate_id=debate.id,
        provider="system",
        provider_ref=f"debate:{debate.id}:cover:{version_id}",
        meta={"provider_cost_usd": usd, "markup": markup},
    )


def cover_charge_usd(price: float, markup: float) -> Decimal:
    """What a cover is quoted at: its estimated provider cost x markup."""
    return to_usd(Decimal(str(price)) * Decimal(str(markup)))
