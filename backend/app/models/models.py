import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

# Debate statuses: draft | queued | running | completed | error | stopped
# Credit transaction kinds: bonus | topup | debate | media | adjustment | refund


def utcnow() -> datetime:
    return datetime.now(UTC)


class Session(Base):
    """Legacy anonymous session table (kept for old rows; accounts replaced it)."""

    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # session_id cookie
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    debates: Mapped[list["Debate"]] = relationship("Debate", back_populates="session")


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    display_name: Mapped[str] = mapped_column(String(100))
    # Seed for the generated avatar gradient; users can re-roll it.
    avatar_seed: Mapped[str] = mapped_column(String(64), default="")
    # Prepaid balance in USD. May go slightly negative when a run costs more than estimated.
    credits_usd: Mapped[Decimal] = mapped_column(
        Numeric(14, 6), default=Decimal("0"), server_default="0"
    )
    # Optional personal OpenRouter key, encrypted with SECRET_KEY (see app.core.security).
    openrouter_key_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    openrouter_key_last4: Mapped[str | None] = mapped_column(String(8), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    debates: Mapped[list["Debate"]] = relationship("Debate", back_populates="user")
    transactions: Mapped[list["CreditTransaction"]] = relationship(
        "CreditTransaction",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="CreditTransaction.created_at.desc()",
    )


class CreditTransaction(Base):
    """Append-only ledger of credit movements (top-ups, bonuses, charges)."""

    __tablename__ = "credit_transactions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    amount_usd: Mapped[Decimal] = mapped_column(Numeric(14, 6))  # signed
    balance_after_usd: Mapped[Decimal] = mapped_column(Numeric(14, 6))
    kind: Mapped[str] = mapped_column(String(32), index=True)
    description: Mapped[str | None] = mapped_column(String(300), nullable=True)
    debate_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("debates.id", ondelete="SET NULL"), nullable=True, index=True
    )
    provider: Mapped[str | None] = mapped_column(String(32), nullable=True)  # stripe | system
    # Idempotency key, e.g. "stripe:{checkout_session_id}" or "debate:{id}:llm".
    provider_ref: Mapped[str | None] = mapped_column(String(200), nullable=True, unique=True)
    meta_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )

    user: Mapped["User"] = relationship("User", back_populates="transactions")


class Debate(Base):
    __tablename__ = "debates"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("sessions.id"), nullable=True, index=True
    )
    # Owner. NULL for debates created before accounts existed.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # draft | queued | running | completed | error | stopped
    status: Mapped[str] = mapped_column(String, default="queued", index=True)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Full DebateConfig JSON (never contains user API keys)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Aggregated stats: {tokens_in, tokens_out, cost, turns_count, analysis_cost}
    totals_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # Structured verdict: {winner_id, winner_name, headline, feedback: [...]} (see services.verdict)
    verdict_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, server_default="{}")

    # Public gallery / share link
    is_public: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", index=True
    )
    slug: Mapped[str | None] = mapped_column(String(32), nullable=True, unique=True)
    category: Mapped[str | None] = mapped_column(String(40), nullable=True)
    views: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Denormalized counters of debate_likes / debate_votes rows (gallery sorting).
    likes_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    votes_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Gallery moderation: none (not checked) | approved | flagged (waits for an admin) | rejected.
    # moderation_json: {reason, source: llm|fallback|admin, checked_at, publish_requested}
    # (see app.services.moderation).
    moderation_status: Mapped[str] = mapped_column(
        String(16), default="none", server_default="none", index=True
    )
    moderation_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, server_default="{}")

    # Audio/video pipeline: none | queued | running | ready | error.
    # media_json holds progress, options, asset names and stats (see app.services.media.state).
    media_status: Mapped[str] = mapped_column(
        String, default="none", server_default="none", index=True
    )
    media_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, server_default="{}")

    session: Mapped["Session | None"] = relationship("Session", back_populates="debates")
    user: Mapped["User | None"] = relationship("User", back_populates="debates")
    turns: Mapped[list["Turn"]] = relationship(
        "Turn",
        back_populates="debate",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Turn.seq_index",
    )
    participants: Mapped[list["DebateParticipant"]] = relationship(
        "DebateParticipant",
        back_populates="debate",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="DebateParticipant.id",
    )


class DebateParticipant(Base):
    """Normalized table for analytics (e.g., finding all debates with GPT-4)."""

    __tablename__ = "debate_participants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    debate_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("debates.id", ondelete="CASCADE")
    )

    role: Mapped[str] = mapped_column(String)  # moderator | debater
    model_id: Mapped[str] = mapped_column(String)  # openrouter model id
    persona_name: Mapped[str | None] = mapped_column(String, nullable=True)
    voice_name: Mapped[str | None] = mapped_column(String, nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String, nullable=True)

    debate: Mapped["Debate"] = relationship("Debate", back_populates="participants")


class Turn(Base):
    __tablename__ = "turns"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    debate_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("debates.id", ondelete="CASCADE"), index=True
    )

    seq_index: Mapped[int] = mapped_column(Integer)  # Order 0, 1, 2...
    round_id: Mapped[str] = mapped_column(String)  # e.g. "round_1", "verdict"
    # moderator_intro | moderator_transition | opening | rebuttal | closing | argument | verdict
    turn_type: Mapped[str] = mapped_column(String)

    speaker_id: Mapped[str] = mapped_column(String)
    speaker_name: Mapped[str] = mapped_column(String)

    text: Mapped[str] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    word_count: Mapped[int] = mapped_column(Integer, default=0)

    model_used: Mapped[str] = mapped_column(String)
    # {prompt_tokens, completion_tokens, total_tokens, cost}
    usage_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # Visual scenes of the turn (app.services.studio): the director's plan, the speaker's
    # [visual: …] hints, disputes made in this turn, fact-checks of its scenes.
    visuals_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, server_default="{}")

    retake_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    debate: Mapped["Debate"] = relationship("Debate", back_populates="turns")


class DebateLike(Base):
    """One like per user and public debate."""

    __tablename__ = "debate_likes"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    debate_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("debates.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (Index("ix_debate_likes_debate_id", "debate_id"),)


class DebateVote(Base):
    """Audience vote: which debater argued better, one per user and debate (changeable)."""

    __tablename__ = "debate_votes"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    debate_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("debates.id", ondelete="CASCADE"), primary_key=True
    )
    # "participant_{i}" (see serializers.participants_out); always a debater.
    participant_id: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (Index("ix_debate_votes_debate_id", "debate_id"),)


class Preset(Base):
    __tablename__ = "presets"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # e.g. "classic_v1"
    name: Mapped[str] = mapped_column(String)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    preset_json: Mapped[dict[str, Any]] = mapped_column(JSON)
