import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
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
    # The site's own account (`python -m app.manage official`): the logo as its avatar, a mark
    # next to its name, the only one allowed the brand's name (services/official).
    official: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Last request as this user (cookie or API token), written at most every ACTIVITY_TOUCH
    # (app.services.activity); the days themselves are in user_activity_days.
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Admin console (app/admin): None | "admin" | "moderator". Granted only on the server
    # (`python -m app.manage admin grant`), never through the API.
    admin_role: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # TOTP second factor of the console, encrypted (app.core.security.encrypt_totp_secret).
    totp_secret_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    totp_enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # SHA-256 of the unused one-time recovery codes.
    recovery_codes_json: Mapped[list[str]] = mapped_column(JSON, default=list, server_default="[]")
    # Bumped to end every session at once (password change, 2FA reset, "sign out everywhere").
    session_epoch: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    debates: Mapped[list["Debate"]] = relationship("Debate", back_populates="user")
    transactions: Mapped[list["CreditTransaction"]] = relationship(
        "CreditTransaction",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="CreditTransaction.created_at.desc()",
    )
    api_tokens: Mapped[list["ApiToken"]] = relationship(
        "ApiToken",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ApiToken.created_at.desc()",
    )


class ApiToken(Base):
    """Personal API token for the CLI, scripts and AI agents (MCP), sent as
    `Authorization: Bearer debatr_…`. Only a SHA-256 hash of the secret is stored; the plaintext
    is shown once, when the token is created (see app.services.api_tokens)."""

    __tablename__ = "api_tokens"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    token_last4: Mapped[str] = mapped_column(String(8))
    # Credits the token may spend in total: the runs it started, with their voices and pictures.
    # None = no limit. Runs on the user's own OpenRouter key cost no credits.
    spend_limit_usd: Mapped[Decimal | None] = mapped_column(Numeric(14, 6), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship("User", back_populates="api_tokens")


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


class Motion(Base):
    """A debate topic. Every debate is a version of one (services/motions): versions share the
    normalized topic text, or a remix keeps its parent's topic in another language. What the
    gallery shows (versions, cover, title) is computed from the public debates, never stored."""

    __tablename__ = "motions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(32), unique=True)  # /t/{slug}
    # Normalized topic text (motions.normalize_topic). NULL for a topic an admin split off a
    # version into: new debates with that text keep joining the original topic.
    key: Mapped[str | None] = mapped_column(String(600), nullable=True, unique=True)
    # Set when an admin merged this topic into another one; lookups follow it (one hop: merging
    # re-points the topics merged into this one).
    merged_into_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("motions.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    # Similar topics for the wizard (pg_trgm similarity on the normalized text).
    __table_args__ = (
        Index(
            "ix_motions_key_trgm",
            "key",
            postgresql_using="gin",
            postgresql_ops={"key": "gin_trgm_ops"},
        ),
    )


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
    # API token that started the run (CLI / agents); its charges count against the token's
    # spending limit. NULL for runs started in the browser.
    api_token_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("api_tokens.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # The topic this debate is a version of (services/motions.assign_motion).
    motion_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("motions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # The debate this one was remixed from ("Remix of …"; a translation stays in its topic).
    remix_of_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("debates.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # draft | queued | running | completed | error | stopped
    status: Mapped[str] = mapped_column(String, default="queued", index=True)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Full DebateConfig JSON (never contains user API keys)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
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
    # AI cover (services/media/cover.py): none | queued | running | ready | error, the state of
    # the latest build. cover_json: {current, versions[], request, error, started_at, ...};
    # `current` is the version shown everywhere (null: the markup cover).
    cover_status: Mapped[str] = mapped_column(
        String(16), default="none", server_default="none", index=True
    )
    cover_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, server_default="{}")

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

    # An account's debates by date (library, admin user page, per-user statistics).
    __table_args__ = (Index("ix_debates_user_id_created_at", "user_id", "created_at"),)


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


class UserActivityDay(Base):
    """A UTC day on which an account used the site or the API (DAU / WAU / MAU, retention).
    One row per user and day, written by app.services.activity."""

    __tablename__ = "user_activity_days"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    day: Mapped[date] = mapped_column(Date, primary_key=True)

    __table_args__ = (Index("ix_user_activity_days_day", "day"),)


class ViewDay(Base):
    """Views of a public debate per UTC day, by where it was watched (`place`: its page or a
    player embedded on another site) and where the viewer came from (`source`: search, ai,
    social, embed, other, direct, internal; app.services.views). No IP, no address, no user:
    only counts, written by the view beacon."""

    __tablename__ = "view_days"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    debate_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("debates.id", ondelete="CASCADE"), primary_key=True
    )
    place: Mapped[str] = mapped_column(String(8), primary_key=True)
    source: Mapped[str] = mapped_column(String(16), primary_key=True)
    views: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    __table_args__ = (Index("ix_view_days_debate_id", "debate_id"),)


class Visit(Base):
    """One visit of the site (a session: ends after 30 minutes without activity), written by the
    page's presence beacon (app.services.audience). The ids come from the browser: `visitor_id`
    lives in its localStorage, `id` rotates with the visit. `ip` and `user_agent` are cleared
    after the `analytics_ip_days` lever; the rest (place, source, pages, time) stays."""

    __tablename__ = "visits"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    visitor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Signed in with a console role at some point of the visit (left out of the statistics).
    staff: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    last_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    user_agent: Mapped[str | None] = mapped_column(String(300), nullable=True)
    country: Mapped[str | None] = mapped_column(String(2), nullable=True)  # ISO 3166-1 alpha-2
    region: Mapped[str | None] = mapped_column(String(80), nullable=True)
    city: Mapped[str | None] = mapped_column(String(80), nullable=True)
    # Where it came from (app.services.views.classify), the referring host and page, the
    # campaign of the landing address (utm_*) and its `?ref=`.
    source: Mapped[str] = mapped_column(String(16), default="direct")
    referrer_host: Mapped[str | None] = mapped_column(String(253), nullable=True)
    referrer: Mapped[str | None] = mapped_column(String(300), nullable=True)
    utm_source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    utm_medium: Mapped[str | None] = mapped_column(String(100), nullable=True)
    utm_campaign: Mapped[str | None] = mapped_column(String(100), nullable=True)
    ref: Mapped[str | None] = mapped_column(String(40), nullable=True)
    landing: Mapped[str] = mapped_column(String(300), default="/")
    exit_path: Mapped[str] = mapped_column(String(300), default="/")
    pageviews: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    actions: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Time the page was in front of the visitor (visible, not idle), over all its pages.
    engaged_ms: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    device: Mapped[str] = mapped_column(String(8), default="desktop")  # desktop | mobile | tablet
    browser: Mapped[str | None] = mapped_column(String(24), nullable=True)
    os: Mapped[str | None] = mapped_column(String(24), nullable=True)
    screen: Mapped[str | None] = mapped_column(String(16), nullable=True)  # "1440x900"
    language: Mapped[str | None] = mapped_column(String(16), nullable=True)  # navigator.language
    timezone: Mapped[str | None] = mapped_column(String(48), nullable=True)
    # The visitor's first visit (no earlier visit with its id).
    new_visitor: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    # A person, a bot or an AI agent (audience/bots.py), weighed again with every beacon:
    # human | likely_human | unclear | suspect | bot | agent; the score is automation points
    # minus person points (±100) and the reasons [{code, points, detail?}] say why.
    verdict: Mapped[str] = mapped_column(
        String(12), default="unclear", server_default="unclear", index=True
    )
    bot_score: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    bot_reasons: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, server_default="[]"
    )
    # What the page counted of its input and said about the browser, and the request's facts
    # (bots.merge: {"c": counts, "env": browser, "srv": headers}).
    signals: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, server_default="{}")
    # The IP's network operator and whether it is a data centre or a relay (kept after the IP).
    network: Mapped[str | None] = mapped_column(String(120), nullable=True)
    network_kind: Mapped[str | None] = mapped_column(String(8), nullable=True)

    __table_args__ = (Index("ix_visits_visitor_started", "visitor_id", "started_at"),)


class VisitEvent(Base):
    """A page shown in a visit (`kind=page`, `engaged_ms` grows while it stays in front) or
    something the visitor did there (`kind=action`, `name` from audience.ACTIONS)."""

    __tablename__ = "visit_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    visit_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("visits.id", ondelete="CASCADE")
    )
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    kind: Mapped[str] = mapped_column(String(8))  # page | action
    name: Mapped[str] = mapped_column(String(32))  # "page", or the action
    path: Mapped[str] = mapped_column(String(300))
    debate_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("debates.id", ondelete="SET NULL"), nullable=True, index=True
    )
    engaged_ms: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    props: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, server_default="{}")

    __table_args__ = (Index("ix_visit_events_visit_at", "visit_id", "at"),)


class ProviderUsage(Base):
    """One paid provider call (or try): what it was for, on whose key, what it cost.

    Append-only, written by app.services.usage from the single places that call providers
    (media/llm.py, the orchestrator's turn stream, the TTS step). Unlike `totals_json` it keeps
    retries and refused answers too, and tells the system key from the user's own."""

    __tablename__ = "provider_usage"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    debate_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("debates.id", ondelete="SET NULL"), nullable=True, index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # turn | verdict | verdict_structure | moderation | factcheck | director | sketch |
    # image | image_check | highlights | trending | trending_review | topic_ideas | tts | …
    purpose: Mapped[str] = mapped_column(String(32), index=True)
    provider: Mapped[str] = mapped_column(String(16))  # openrouter | elevenlabs | edge
    model: Mapped[str] = mapped_column(String(160))  # the model that answered when known
    key_owner: Mapped[str] = mapped_column(String(8))  # system | user
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    chars: Mapped[int] = mapped_column(Integer, default=0)  # TTS characters billed
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(14, 6), default=Decimal(0))
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    error_kind: Mapped[str | None] = mapped_column(String(24), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # ttft_ms, seq_index, estimated (TTS price from a rate table) …
    meta_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, server_default="{}")


class AdminAuditLog(Base):
    """What admins did, and the console's security events (sign-ins, failures, 2FA changes).

    Append-only: a database trigger refuses UPDATE, DELETE and TRUNCATE (migration 0011). No
    foreign keys, so the record of what was done to or by an account outlives the account;
    `actor_email` is a snapshot for the same reason."""

    __tablename__ = "admin_audit_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    actor_email: Mapped[str | None] = mapped_column(String(320), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(64), index=True)  # e.g. "auth.signed_in"
    target_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    before_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    after_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(300), nullable=True)
    ok: Mapped[bool] = mapped_column(Boolean, default=True)

    __table_args__ = (Index("ix_admin_audit_log_target", "target_type", "target_id"),)


class AdminPasskey(Base):
    """A passkey (WebAuthn credential) an admin may use instead of the TOTP code: at sign-in and
    for sudo (app.services.admin.passkeys). Only the public key is stored."""

    __tablename__ = "admin_passkeys"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    credential_id: Mapped[str] = mapped_column(String(1400), unique=True)  # base64url
    public_key: Mapped[bytes] = mapped_column(LargeBinary)  # COSE key
    sign_count: Mapped[int] = mapped_column(Integer, default=0)
    transports: Mapped[list[str]] = mapped_column(JSON, default=list)
    name: Mapped[str] = mapped_column(String(64))
    aaguid: Mapped[str | None] = mapped_column(String(36), nullable=True)
    backed_up: Mapped[bool] = mapped_column(Boolean, default=False)  # synced (iCloud, Google…)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RuntimeSetting(Base):
    """A lever changed in the admin console without a deploy (app.services.runtime_settings:
    only keys of its allowlist; without a row the env setting applies). Every change is in the
    audit log."""

    __tablename__ = "runtime_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value_json: Mapped[Any] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_by: Mapped[str | None] = mapped_column(String(320), nullable=True)  # admin's email


class Preset(Base):
    __tablename__ = "presets"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # e.g. "classic_v1"
    name: Mapped[str] = mapped_column(String)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    preset_json: Mapped[dict[str, Any]] = mapped_column(JSON)


class TrendingBatch(Base):
    """One run of the trending-topics builder (services/trending.py). The newest batch is what
    the wizard shows; older ones stay as an archive for statistics."""

    __tablename__ = "trending_batches"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    model: Mapped[str] = mapped_column(String(100))
    topic_count: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(14, 6), default=Decimal(0))
    # feeds (ok/total), headlines (fresh/blocked/sent), dropped topics with reasons.
    stats_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, server_default="{}")

    topics: Mapped[list["TrendingTopic"]] = relationship(
        "TrendingTopic", back_populates="batch", cascade="all, delete-orphan"
    )


class TrendingTopic(Base):
    """A debate (or battle) topic made from today's news, with the articles it came from."""

    __tablename__ = "trending_topics"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("trending_batches.id", ondelete="CASCADE"), index=True
    )
    # The show format whose list it is on (formats.topic_list_of: the rap battle has its own).
    format: Mapped[str] = mapped_column(String(20), default="debate", server_default="debate")
    rank: Mapped[int] = mapped_column(Integer)  # 1 = hottest within its format's list
    label: Mapped[str] = mapped_column(String(80))
    question: Mapped[str] = mapped_column(String(300))
    brief: Mapped[str] = mapped_column(Text, default="")  # what happened; goes to `description`
    category: Mapped[str] = mapped_column(String(20))  # trending.TOPIC_CATEGORIES
    heat: Mapped[int] = mapped_column(Integer, default=5)  # the model's 1-10 estimate
    outlets: Mapped[int] = mapped_column(Integer, default=1)  # distinct outlets that cover it
    # [{"title", "url", "outlet", "published_at"}]
    sources_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    is_hidden: Mapped[bool] = mapped_column(Boolean, default=False)  # hidden by an admin
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    batch: Mapped["TrendingBatch"] = relationship("TrendingBatch", back_populates="topics")
