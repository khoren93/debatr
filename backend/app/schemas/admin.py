"""Request and response models of the admin console API (`/api/admin/*`).

Responses are explicit allowlists: no model here carries a password hash, an encrypted key, a
TOTP secret after enrollment or a token hash (tests/test_admin_console.py checks the fields).
Mirrored by frontend/src/api/admin/types.ts.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.auth import ApiTokenOut, normalize_email


class AdminLoginRequest(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(min_length=1, max_length=200)

    @field_validator("email")
    @classmethod
    def _email(cls, value: str) -> str:
        return normalize_email(value)


class AdminLoginOut(BaseModel):
    # What the sign-in page asks for next: the authenticator code, or setting one up.
    next: Literal["totp", "enroll"]


class AdminCodeRequest(BaseModel):
    """A TOTP code, or one of the recovery codes instead."""

    code: str = Field(default="", max_length=32)
    recovery_code: str = Field(default="", max_length=32)


class EnrollStartRequest(BaseModel):
    enrollment_code: str = Field(min_length=1, max_length=40)


class EnrollStartOut(BaseModel):
    secret: str  # shown once, for typing it in when the QR code cannot be scanned
    otpauth_uri: str
    qr: str  # SVG data URI


class EnrollConfirmRequest(BaseModel):
    code: str = Field(min_length=1, max_length=32)


class AdminUserOut(BaseModel):
    id: str
    email: str
    display_name: str
    role: str


class AdminSessionInfo(BaseModel):
    id: str
    created_at: datetime
    expires_at: datetime  # idle or absolute deadline, whichever comes first
    ends_at: datetime  # the absolute deadline (activity does not extend it)
    sudo_until: datetime | None = None


class AdminMeOut(BaseModel):
    user: AdminUserOut
    csrf: str
    session: AdminSessionInfo
    recovery_codes_left: int
    permissions: list[str]


class AdminSignedInOut(BaseModel):
    me: AdminMeOut
    # Only right after enrolling: shown once, never again.
    recovery_codes: list[str] | None = None


class AdminSessionOut(BaseModel):
    id: str
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    ip: str
    user_agent: str
    current: bool


class RecoveryCodesOut(BaseModel):
    recovery_codes: list[str]


class SudoOut(BaseModel):
    sudo_until: datetime


# --- overview ---------------------------------------------------------------------------------

OverviewPeriod = Literal["24h", "7d", "30d", "90d", "all"]


class Tile(BaseModel):
    value: float
    previous: float | None = None  # the period before (None for "all")


class UserTiles(BaseModel):
    new: Tile
    active: Tile
    total: int
    dau: int
    wau: int
    mau: int


class DebateTiles(BaseModel):
    started: Tile
    completed: Tile
    failed: Tile
    stopped: Tile
    error_rate: Tile
    running_now: int
    media_ready: Tile
    media_failed: Tile
    renders: int  # MP4 exports of the debates created in the period
    published: Tile
    likes: Tile
    votes: Tile


class MoneyOut(BaseModel):
    topups: float
    bonuses: float
    refunds: float
    adjustments: float
    charged: dict[str, float]  # models / voices / pictures, as positive amounts
    charged_total: float
    cost_system: float  # what providers cost us (system keys)
    cost_user_keys: float  # spent on users' own keys (not ours)
    cost_by_purpose: dict[str, float]
    margin: float
    topups_previous: float | None = None
    charged_total_previous: float | None = None
    cost_system_previous: float | None = None
    margin_previous: float | None = None
    liabilities: float  # credits users hold
    negative_balances: int
    negative_total: float
    cost_tracked_since: datetime | None  # provider_usage starts here


class SeriesPoint(BaseModel):
    t: datetime
    signups: float
    active: float | None
    completed: float
    error: float
    stopped: float
    charged: float | None = None
    topups: float | None = None
    cost: float | None = None


class AttentionItem(BaseModel):
    key: str
    severity: Literal["critical", "warning", "info"]
    title: str
    detail: str
    href: str | None = None


class TopModel(BaseModel):
    model: str
    debates: int
    turns: int
    failure_rate: float | None
    avg_ttft_ms: int | None
    cost: float


class TopSpender(BaseModel):
    user_id: str
    email: str
    display_name: str
    spent: float


class TopDebate(BaseModel):
    id: str
    title: str
    slug: str | None
    url: str | None  # the public page on the site, when published
    likes: int
    views: int
    votes: int


class OverviewOut(BaseModel):
    period: OverviewPeriod
    start: datetime
    end: datetime
    previous_start: datetime | None
    bucket: Literal["hour", "day", "week"]
    generated_at: datetime
    users: UserTiles
    debates: DebateTiles
    money: MoneyOut | None  # only with the "money" permission
    series: list[SeriesPoint]
    attention: list[AttentionItem]
    top_models: list[TopModel]
    top_spenders: list[TopSpender] | None
    top_debates: list[TopDebate]


# --- users ------------------------------------------------------------------------------------

UserSort = Literal[
    "created", "last_seen", "balance", "topped_up", "spent", "debates", "likes", "email"
]


class UserFilters(BaseModel):
    """The list's search and filters (query parameters of the list and the CSV export)."""

    q: str = Field(default="", max_length=200)  # email or name contains, or an exact id
    paid: bool | None = None  # ever topped up
    balance: Literal["positive", "negative"] | None = None
    own_key: bool | None = None  # stored OpenRouter key
    tokens: bool | None = None  # API tokens that still work
    status: Literal["active", "disabled"] | None = None
    staff: bool | None = None  # has a console role
    created_from: date | None = None  # UTC days, both inclusive
    created_to: date | None = None
    active_days: int | None = Field(default=None, ge=1, le=365)  # seen within N days


class UserExportQuery(UserFilters):
    sort: UserSort = "created"
    order: Literal["asc", "desc"] = "desc"


class UserListQuery(UserExportQuery):
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)


class SpendByCategory(BaseModel):
    models: float = 0.0
    voices: float = 0.0
    pictures: float = 0.0


class AdminUserRow(BaseModel):
    id: str
    email: str
    display_name: str
    created_at: datetime
    last_login_at: datetime | None
    last_seen_at: datetime | None
    is_active: bool
    role: str | None
    credits_usd: float
    own_key: bool
    tokens: int
    topped_up: float
    spent: float
    spent_by: SpendByCategory
    debates: int  # runs, drafts left out
    failed: int
    public: int
    likes: int  # received on their debates
    votes: int


class AdminUserList(BaseModel):
    total: int
    limit: int
    offset: int
    rows: list[AdminUserRow]


class AdminUserProfile(BaseModel):
    id: str
    email: str
    display_name: str
    avatar_seed: str
    created_at: datetime
    last_login_at: datetime | None
    last_seen_at: datetime | None
    is_active: bool
    role: str | None
    two_factor: bool  # console second factor set up
    credits_usd: float
    openrouter_key_masked: str | None


class UserPeriodStats(BaseModel):
    debates: int = 0
    completed: int = 0
    failed: int = 0
    stopped: int = 0
    error_rate: float | None = None
    free_debates: int = 0  # every debater on a free model
    paid_debates: int = 0
    own_key_debates: int = 0
    token_debates: int = 0  # started with an API token
    tokens_in: int = 0
    tokens_out: int = 0
    topped_up: float = 0.0
    credited: float = 0.0  # bonuses, refunds and positive adjustments
    spent: float = 0.0
    spent_by: SpendByCategory = Field(default_factory=SpendByCategory)
    avg_debate_cost: float | None = None  # model tokens charged per finished debate
    cost_system: float = 0.0  # what their runs cost us on the system keys


class ModelCount(BaseModel):
    model: str
    debates: int


class SpendDay(BaseModel):
    day: date
    models: float = 0.0
    voices: float = 0.0
    pictures: float = 0.0


class ReactionOwner(BaseModel):
    """Whose debates an account liked or voted on (many to one owner looks like boosting)."""

    user_id: str | None
    email: str | None
    display_name: str | None
    likes: int
    votes: int


class UserReactions(BaseModel):
    likes_given: int
    votes_given: int
    owners: list[ReactionOwner]


class AuditEntryOut(BaseModel):
    id: str
    created_at: datetime
    actor_email: str | None
    action: str
    target_type: str | None
    target_id: str | None
    reason: str | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    ip: str | None
    ok: bool


class AdminUserCard(BaseModel):
    profile: AdminUserProfile
    all_time: UserPeriodStats
    last_30_days: UserPeriodStats
    favorite_models: list[ModelCount]
    spend_days: list[SpendDay]  # the last 30 UTC days
    tokens: list[ApiTokenOut]
    reactions: UserReactions
    audit: list[AuditEntryOut]  # about the account, and by it when it is an admin
    active_debates: int
    public_debates: int
    # Admin accounts are disabled, deleted or given passwords only on the server.
    protected: bool


class AdminLedgerRow(BaseModel):
    id: str
    created_at: datetime
    kind: str
    category: str
    title: str
    description: str | None
    amount_usd: float
    balance_after_usd: float
    debate_id: str | None
    provider: str | None
    provider_ref: str | None
    reason: str | None  # internal, for manual changes


class AdminLedgerPage(BaseModel):
    total: int
    rows: list[AdminLedgerRow]


class AdminUserDebate(BaseModel):
    id: str
    title: str
    status: str
    created_at: datetime
    ended_at: datetime | None
    models: list[str]  # debaters
    is_public: bool
    url: str | None  # the public page on the site
    moderation_status: str
    media_status: str
    likes: int
    votes: int
    views: int
    charged: float  # net credits of the debate's ledger rows
    own_key: bool
    via_token: bool
    error: str | None


class AdminUserDebatePage(BaseModel):
    total: int
    rows: list[AdminUserDebate]


class ReasonRequest(BaseModel):
    """Every change to an account names its reason (kept in the audit log)."""

    reason: str = Field(min_length=3, max_length=500)

    @field_validator("reason")
    @classmethod
    def _reason(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 3:
            raise ValueError("Give a reason (at least 3 characters)")
        return value


class CreditChangeRequest(ReasonRequest):
    amount: Decimal  # signed USD
    kind: Literal["adjustment", "bonus", "refund"] = "adjustment"
    description: str | None = Field(default=None, max_length=300)  # what the user sees
    # One per dialog: a repeated request (retry, double click) never moves money twice.
    idempotency_key: uuid.UUID


class CreditChangeOut(BaseModel):
    transaction_id: str
    balance_before: float
    balance_after: float
    duplicate: bool  # this key was applied before; nothing changed now


class DisableUserRequest(ReasonRequest):
    stop_debates: bool = True
    revoke_tokens: bool = False
    unpublish: bool = False


class DisableUserOut(BaseModel):
    stopped: int
    tokens_revoked: int
    unpublished: int


class RevokeTokensRequest(ReasonRequest):
    token_id: uuid.UUID | None = None  # None: every token


class CountOut(BaseModel):
    count: int


class TemporaryPasswordOut(BaseModel):
    temporary_password: str  # shown once


class DeleteUserRequest(ReasonRequest):
    confirm_email: str = Field(max_length=320)

    @field_validator("confirm_email")
    @classmethod
    def _email(cls, value: str) -> str:
        return normalize_email(value)


class DeleteUserOut(BaseModel):
    debates: int
