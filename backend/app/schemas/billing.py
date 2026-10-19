"""Request/response schemas for credits and payments."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

PaymentsMode = Literal["stripe", "dev", "disabled"]


class BillingConfigOut(BaseModel):
    topup_amounts: list[int]
    currency: str
    payments_mode: PaymentsMode
    signup_bonus_usd: float
    # Prices only, never the markup (an internal lever of the admin console).
    tts_price_per_1k_chars: float
    # ~1000 characters of speech last about a minute at a natural pace.
    tts_price_per_min: float
    elevenlabs_available: bool
    elevenlabs_error: str | None = None


class CheckoutRequest(BaseModel):
    amount_usd: int


class CheckoutOut(BaseModel):
    url: str
    instant: bool = False


class ConfirmOut(BaseModel):
    credited: bool
    amount_usd: float | None = None
    credits_usd: float


class TransactionOut(BaseModel):
    id: str
    amount_usd: float
    balance_after_usd: float
    kind: str
    # What the money paid for: models | voices | pictures | topup | bonus | refund | adjustment
    category: str
    # Headline for the UI: the debate title for charges, the description otherwise.
    title: str
    description: str | None = None
    debate_id: str | None = None
    provider: str | None = None
    created_at: datetime


class UsageDay(BaseModel):
    date: date
    tokens: int = 0
    voice_ms: int = 0
    renders: int = 0
    spent_usd: float = 0.0


class UsageOut(BaseModel):
    period_start: datetime
    # One entry per UTC day from period_start through today.
    days: list[UsageDay] = []
    debates: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    voice_ms: int = 0
    renders: int = 0
    spent_usd: float = 0.0
    topped_up_usd: float = 0.0
    llm_usd: float = 0.0
    tts_usd: float = 0.0
