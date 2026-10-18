"""Request and response models of the admin console API (`/api/admin/*`).

Responses are explicit allowlists: no model here carries a password hash, an encrypted key, a
TOTP secret after enrollment or a token hash (tests/test_admin_console.py checks the fields).
Mirrored by frontend/src/api/admin/types.ts.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.auth import normalize_email


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
