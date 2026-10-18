"""Request and response models of the admin console API (`/api/admin/*`).

Responses are explicit allowlists: no model here carries a password hash, an encrypted key, a
TOTP secret after enrollment or a token hash (tests/test_admin_console.py checks the fields).
Mirrored by frontend/src/api/admin/types.ts.
"""

import json
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
    version: str  # the commit the server runs (APP_VERSION)
    # False when ADMIN_SKIP_2FA (development) lets the console in with the password alone.
    two_factor: bool = True
    passkeys: int = 0  # registered passkeys (sudo can take one instead of a code)


class AdminLoginOut(BaseModel):
    # What the sign-in page asks for next: the authenticator code, setting one up, or nothing
    # ("done" with ADMIN_SKIP_2FA: signed in, `me` is set).
    next: Literal["totp", "enroll", "done"]
    me: AdminMeOut | None = None
    passkey: bool = False  # with "totp": a passkey may answer instead of the code


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


# --- passkeys ---------------------------------------------------------------------------------

MAX_CREDENTIAL_JSON = 20_000


def _small_credential(value: dict[str, Any]) -> dict[str, Any]:
    if len(json.dumps(value, default=str)) > MAX_CREDENTIAL_JSON:
        raise ValueError("credential too large")
    return value


class PasskeyAnswer(BaseModel):
    """The browser's PublicKeyCredential as JSON (base64url fields)."""

    credential: dict[str, Any]

    _credential = field_validator("credential")(_small_credential)


class PasskeyAddRequest(PasskeyAnswer):
    name: str = Field(min_length=1, max_length=64)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        name = " ".join(value.split())
        if not name:
            raise ValueError("Name the passkey")
        return name


class PasskeyOptionsOut(BaseModel):
    options: dict[str, Any]  # for navigator.credentials.create / get (parse*FromJSON)


class AdminPasskeyOut(BaseModel):
    id: str
    name: str
    created_at: datetime
    last_used_at: datetime | None
    backed_up: bool  # synced passkey (iCloud Keychain, Google Password Manager…)
    transports: list[str]


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
    actor_user_id: str | None = None
    actor_email: str | None
    action: str
    target_type: str | None
    target_id: str | None
    reason: str | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    ip: str | None
    user_agent: str | None = None
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


# --- debates and moderation -------------------------------------------------------------------

DebateSort = Literal["created", "likes", "views", "cost", "charged", "turns"]
DebateStatusName = Literal["draft", "queued", "running", "completed", "error", "stopped"]


class DebateFilters(BaseModel):
    q: str = Field(default="", max_length=200)  # title contains, an exact id or slug
    status: DebateStatusName | None = None
    active: bool | None = None  # queued or running
    failed: bool | None = None  # ended with an error
    moderation: Literal["none", "approved", "flagged", "rejected"] | None = None
    media: Literal["none", "queued", "running", "ready", "error"] | None = None
    public: bool | None = None
    own_key: bool | None = None  # ran on the owner's OpenRouter key
    via_token: bool | None = None  # started with an API token
    model: str | None = Field(default=None, max_length=160)  # a debater's model id
    user_id: uuid.UUID | None = None
    created_from: date | None = None  # UTC days, both inclusive
    created_to: date | None = None


class DebateListQuery(DebateFilters):
    sort: DebateSort = "created"
    order: Literal["asc", "desc"] = "desc"
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)


class DebateOwner(BaseModel):
    id: str
    email: str
    display_name: str


class AdminDebateRow(BaseModel):
    id: str
    title: str
    owner: DebateOwner | None  # None: a debate from before accounts
    status: str
    models: list[str]  # debaters
    created_at: datetime
    started_at: datetime | None
    ended_at: datetime | None
    duration_ms: int | None  # start to end of the run
    turns: int
    cost: float | None  # provider cost on the system keys (`money` permission)
    charged: float | None  # net credits of its ledger rows (`money` permission)
    own_key: bool
    via_token: bool
    is_public: bool
    url: str | None
    moderation_status: str
    media_status: str
    views: int
    likes: int
    votes: int
    error: str | None


class AdminDebateList(BaseModel):
    total: int
    limit: int
    offset: int
    rows: list[AdminDebateRow]


class AdminTurn(BaseModel):
    seq_index: int
    round_id: str
    turn_type: str
    speaker_name: str
    model_used: str
    text: str
    error: str | None
    created_at: datetime | None
    tokens_in: int
    tokens_out: int
    cost: float
    duration_ms: int | None
    ttft_ms: int | None
    error_kind: str | None
    visuals_status: str
    scenes: int
    checks: dict[str, int]  # fact-check verdict -> scenes
    disputes: int


class UsageByPurpose(BaseModel):
    purpose: str
    key_owner: str
    calls: int
    failures: int
    cost: float


class RecoveryState(BaseModel):
    """What Redis knows about the debate's runs right now."""

    debate_beat: bool  # a worker is on a debate step
    media_beat: bool  # a worker is building the audio
    debate_attempts: int  # recovery re-queued the run this many times
    media_attempts: int
    stop_flag: bool
    provider_key: bool  # an own OpenRouter key waits for the run
    tts_key: bool  # an own ElevenLabs key waits for the build


class AdminDebateCard(BaseModel):
    debate: AdminDebateRow
    topic: str
    config: dict[str, Any]  # as stored (keys never are), `billing` included
    totals: dict[str, Any]
    turns: list[AdminTurn]
    verdict: dict[str, Any]
    moderation: dict[str, Any]
    wants_public: bool  # the owner asked for the gallery
    media: dict[str, Any]  # media_json: options, progress, stats, error, renders, free
    recovery: RecoveryState
    usage: list[UsageByPurpose] | None  # provider calls by purpose (`money`)
    ledger: list[AdminLedgerRow] | None  # `money`
    refundable: float | None  # net charged, what a refund may still give back (`money`)
    resume_from: int | None  # the turn a resume starts from, when it can be resumed
    audit: list[AuditEntryOut]


class ModerationItem(BaseModel):
    id: str
    title: str
    owner: DebateOwner | None
    models: list[str]
    created_at: datetime
    ended_at: datetime | None
    reason: str | None
    source: str | None  # llm | fallback (the check gave no answer)
    checked_at: str | None
    publish_requested: bool  # the owner wants it public


class ModerationDecision(BaseModel):
    debate_id: str | None
    title: str | None  # None when the debate is gone
    action: str  # moderation.approved | moderation.rejected
    actor_email: str | None
    reason: str | None
    created_at: datetime


class ModerationQueue(BaseModel):
    flagged: list[ModerationItem]
    recent: list[ModerationDecision]


class RefundRequest(ReasonRequest):
    amount: Decimal | None = None  # None: everything still refundable
    idempotency_key: uuid.UUID


class RefundOut(BaseModel):
    transaction_id: str
    amount: float
    balance_after: float
    duplicate: bool


class MediaRebuildRequest(ReasonRequest):
    force: bool = False  # voice every turn again instead of reusing cached ones


class ActionOut(BaseModel):
    status: str
    message: str


# --- trending topics --------------------------------------------------------------------------


class TrendingBatchRow(BaseModel):
    id: str
    created_at: datetime
    model: str
    topic_count: int
    hidden: int
    cost_usd: float
    current: bool  # the newest batch: what the wizard shows
    feeds_ok: int | None
    feeds_total: int | None
    headlines_fresh: int | None
    headlines_blocked: int | None
    headlines_sent: int | None
    topics_asked: int | None
    dropped: int


class TrendingBatchPage(BaseModel):
    total: int
    rows: list[TrendingBatchRow]


class TrendingTopicOut(BaseModel):
    id: str
    rank: int
    label: str
    question: str
    brief: str
    category: str
    heat: int
    outlets: int
    sources: list[dict[str, Any]]
    is_hidden: bool


class TrendingBatchCard(BaseModel):
    batch: TrendingBatchRow
    topics: list[TrendingTopicOut]
    dropped: list[dict[str, Any]]  # topics the model or the review dropped, with the reason
    blocked: list[dict[str, Any]]  # headlines the blocklist removed


# --- system -----------------------------------------------------------------------------------


class JobSummary(BaseModel):
    id: str
    queue: str
    func: str  # the job function's short name
    debate_id: str | None
    status: str | None
    enqueued_at: datetime | None
    started_at: datetime | None
    ended_at: datetime | None
    error: str | None  # the end of the traceback


class QueueStats(BaseModel):
    name: str
    waiting: int
    started: int
    failed: int
    scheduled: int
    deferred: int
    finished: int


class WorkerInfo(BaseModel):
    name: str
    hostname: str | None
    pid: int | None
    queues: list[str]
    state: str
    current_job: JobSummary | None
    last_heartbeat: datetime | None
    birth: datetime | None
    successful: int
    failed: int
    working_seconds: float


class SchedulerInfo(BaseModel):
    name: str
    hostname: str | None
    pid: int | None
    started_at: datetime | None
    last_heartbeat: datetime | None


class CronJobInfo(BaseModel):
    name: str
    interval_seconds: int | None
    last_enqueued_at: datetime | None
    recent: list[JobSummary]  # the last runs RQ still remembers, newest first


class QueuesOut(BaseModel):
    queues: list[QueueStats]
    workers: list[WorkerInfo]
    schedulers: list[SchedulerInfo]
    cron_jobs: list[CronJobInfo]
    failed_jobs: list[JobSummary]


class RunInfo(BaseModel):
    debate_id: str
    title: str
    owner_email: str | None
    kind: Literal["debate", "media"]
    status: str
    step: str
    age_seconds: float  # since it started (or was queued)
    heartbeat: bool  # a worker is on it
    waiting: bool  # its next job waits in the queue
    attempts: int  # recovery re-queued it this many times
    stuck: bool  # no worker, no job, for minutes: the watchdog takes it on its next checks


class RunsOut(BaseModel):
    runs: list[RunInfo]


class FairShareUser(BaseModel):
    user_id: str
    email: str | None
    kind: Literal["debate", "media"]
    active: int | None  # runs going now
    refusals: int  # 429s in the last day
    last_refused_at: datetime | None


class LimitsOut(BaseModel):
    free_per_minute: int  # FREE_MODELS_PER_MINUTE (0 = no waiting)
    free_used_this_minute: int
    free_requests_24h: int  # `:free` calls on the system key (provider_usage)
    free_rate_limited_24h: int
    free_daily_cap: int  # OpenRouter: 1000 a day after $10 of credits were bought, else 50
    max_debates_per_user: int
    max_media_per_user: int
    debate_create_rate_limit: int
    login_rate_limit: int
    at_limit_now: list[FairShareUser]
    refused_24h: list[FairShareUser]


class ProvidersOut(BaseModel):
    checked_at: datetime
    openrouter: dict[str, Any]  # balance, total credits / usage, key limit and tier, error
    elevenlabs: dict[str, Any]  # configured, ok, reason, tier, used, limit, resets_at
    payments: dict[str, Any]  # mode, currency, top-up amounts, bonus, markup, TTS price


class TableSize(BaseModel):
    name: str
    bytes: int
    rows: int


class DatabaseHealth(BaseModel):
    ok: bool
    latency_ms: float | None
    bytes: int | None
    connections: int | None
    tables: list[TableSize]
    error: str | None = None


class RedisHealth(BaseModel):
    ok: bool
    latency_ms: float | None
    version: str | None
    uptime_seconds: int | None
    used_memory: int | None
    peak_memory: int | None
    max_memory: int | None
    keys: int | None
    error: str | None = None


class MediaDir(BaseModel):
    name: str
    bytes: int
    files: int
    title: str | None  # the debate's, when it exists


class MediaHealth(BaseModel):
    root: str
    disk_total: int | None
    disk_used: int | None
    disk_free: int | None
    bytes: int
    dirs: int
    heaviest: list[MediaDir]
    orphans: list[MediaDir]  # folders of debates that no longer exist (older than an hour)
    orphan_bytes: int
    scanned_at: datetime


class ConfigFlag(BaseModel):
    name: str
    value: str


class HealthOut(BaseModel):
    version: str
    environment: str
    alembic_current: str | None
    alembic_head: str | None
    database: DatabaseHealth
    redis: RedisHealth
    media: MediaHealth
    backup: dict[str, Any] | None  # what scripts/backup-db.sh recorded last
    config: list[ConfigFlag]


class RecoverRequest(ReasonRequest):
    kind: Literal["debate", "media"] = "debate"


class OrphansDeleteRequest(ReasonRequest):
    names: list[str] = Field(min_length=1, max_length=500)


class OrphansDeleteOut(BaseModel):
    deleted: int
    bytes: int
    skipped: list[str]  # no longer orphans (or gone)


# --- finance and models -----------------------------------------------------------------------

FinancePeriod = Literal["30d", "90d", "12m", "all"]
ModelsPeriod = Literal["30d", "90d", "all"]


class MoneyRow(BaseModel):
    topups: float
    bonuses: float
    refunds: float
    adjustments_in: float
    adjustments_out: float
    charged_models: float
    charged_voices: float
    charged_pictures: float
    charged: float
    cost_billed: float  # system-key cost of what users pay for
    cost_unbilled: float  # system-key cost nobody pays us for
    cost_openrouter: float
    cost_elevenlabs: float
    cost: float
    margin: float  # charged - refunds - cost
    markup: float | None  # charged / cost_billed


class FinancePoint(MoneyRow):
    t: datetime


class TopAccount(BaseModel):
    user_id: str
    email: str
    amount: float


class StripeMissing(BaseModel):
    id: str
    email: str | None
    amount: float
    created: datetime


class StripeReconciliation(BaseModel):
    configured: bool
    error: str | None = None
    sessions: int = 0  # paid checkout sessions in the period
    paid_total: float = 0.0
    credited: int = 0  # top-up rows from Stripe in the period
    credited_total: float = 0.0
    missing: list[StripeMissing] = Field(default_factory=list)  # paid, never credited
    unmatched: list[str] = Field(default_factory=list)  # credited, no paid session listed


class FinanceOut(BaseModel):
    period: FinancePeriod
    bucket: Literal["day", "week", "month"]
    start: datetime
    end: datetime
    totals: MoneyRow
    series: list[FinancePoint]
    cost_by_purpose: dict[str, float]  # system keys
    cost_tracked_since: datetime | None
    liabilities: float
    negative_balances: int
    negative_total: float
    top_payers: list[TopAccount]  # by top-ups
    top_spenders: list[TopAccount]  # by charges
    stripe: StripeReconciliation


class ModelRow(BaseModel):
    model: str
    name: str
    is_free: bool
    in_catalogue: bool  # still offered by OpenRouter
    disabled: bool = False  # turned off on the Settings page
    debates: int  # finished debates it argued in
    tries: int  # turn and verdict calls, retries included
    failure_rate: float | None
    errors: dict[str, int]  # error kind -> failed tries
    own_key_tries: int
    duration_p50_ms: int | None
    duration_p90_ms: int | None
    ttft_p50_ms: int | None
    ttft_p90_ms: int | None
    cost_per_turn: float | None  # `money` permission
    avg_tokens_out: int | None
    judge_wins: int
    judge_contests: int
    audience_wins: int
    audience_contests: int
    claims_checked: int
    claims_verified: int
    claims_disputed: int
    router_pins: int  # debates where the Free Router settled on it


class ModelsOut(BaseModel):
    period: ModelsPeriod
    rows: list[ModelRow]


# --- audit log ----------------------------------------------------------------------------------

AuditTab = Literal["all", "security"]


class AuditQuery(BaseModel):
    """Filters of the audit page (query parameters)."""

    tab: AuditTab = "all"  # security: sign-ins, second factor, sessions, roles
    q: str = Field(default="", max_length=200)  # action, actor, target id, IP or reason contains
    actor: str = Field(default="", max_length=320)  # exact actor email
    action: str = Field(default="", max_length=64)  # exact, or a prefix ending in "." ("auth.")
    target_type: str = Field(default="", max_length=32)
    target_id: str = Field(default="", max_length=64)
    ok: bool | None = None
    created_from: date | None = None  # UTC days, both inclusive
    created_to: date | None = None
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)


class AuditPage(BaseModel):
    total: int
    limit: int
    offset: int
    rows: list[AuditEntryOut]


class FacetCount(BaseModel):
    value: str
    count: int


class AuditFacets(BaseModel):
    actions: list[FacetCount]
    actors: list[FacetCount]
    target_types: list[FacetCount]


class SecuritySummary(BaseModel):
    """The last 7 days of console security events."""

    sign_ins: int
    failures: int  # wrong passwords and codes
    locks: int
    recovery_codes_used: int
    addresses: int  # distinct IPs that tried
    last_failure: AuditEntryOut | None


# --- levers and alerts --------------------------------------------------------------------------

LeverKind = Literal["bool", "int", "float", "text", "models"]


class LeverOut(BaseModel):
    key: str
    kind: LeverKind
    value: Any
    default: Any  # the env setting (what a reset goes back to)
    overridden: bool
    minimum: float | None = None
    maximum: float | None = None
    updated_at: datetime | None = None
    updated_by: str | None = None


class CatalogueModel(BaseModel):
    id: str
    name: str


class SettingsOut(BaseModel):
    levers: list[LeverOut]
    models: list[CatalogueModel]  # OpenRouter's catalogue, for turning models off
    cache_seconds: float  # how soon every process sees a change


class LeverChangeRequest(BaseModel):
    value: Any
    reason: str = Field(min_length=3, max_length=500)


class AlertEntryOut(BaseModel):
    at: datetime
    kind: str
    severity: Literal["critical", "warning", "info"]
    title: str
    detail: str = ""
    path: str | None = None
    sent: bool
    error: str | None = None


class AlertsOut(BaseModel):
    configured: bool  # ALERT_TELEGRAM_BOT_TOKEN and ALERT_TELEGRAM_CHAT_ID set
    check_every_seconds: int
    recent: list[AlertEntryOut]


class AlertTestOut(BaseModel):
    sent: bool
    error: str | None = None
