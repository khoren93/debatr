"""Request/response schemas for accounts."""

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")


def normalize_email(value: str) -> str:
    email = value.strip().lower()
    if not _EMAIL_RE.match(email):
        raise ValueError("Enter a valid email address")
    return email


class RegisterRequest(BaseModel):
    email: str = Field(max_length=320)
    # bcrypt only uses the first 72 bytes of a password.
    password: str = Field(min_length=8, max_length=72)
    display_name: str | None = Field(default=None, max_length=100)

    @field_validator("email")
    @classmethod
    def _email(cls, value: str) -> str:
        return normalize_email(value)


class LoginRequest(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(min_length=1, max_length=72)

    @field_validator("email")
    @classmethod
    def _email(cls, value: str) -> str:
        return value.strip().lower()


class UserOut(BaseModel):
    id: str
    email: str
    display_name: str
    avatar_seed: str
    official: bool = False  # the site's own account: the logo is its avatar
    email_verified: bool = False  # the owner opened a link we mailed
    email_required: bool = False  # publishing and top-ups wait for the email to be confirmed
    credits_usd: float
    openrouter_key_masked: str | None = None
    created_at: datetime


class UpdateProfileRequest(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    avatar_seed: str | None = Field(default=None, max_length=64)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=72)
    new_password: str = Field(min_length=8, max_length=72)


class SetOpenRouterKeyRequest(BaseModel):
    key: str = Field(min_length=10, max_length=300)

    @field_validator("key")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()


class OkResponse(BaseModel):
    ok: bool = True


class ForgotPasswordRequest(BaseModel):
    email: str = Field(max_length=320)

    @field_validator("email")
    @classmethod
    def _email(cls, value: str) -> str:
        return value.strip().lower()


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    # bcrypt only uses the first 72 bytes of a password.
    password: str = Field(min_length=8, max_length=72)


class VerifyEmailRequest(BaseModel):
    token: str = Field(min_length=10, max_length=200)


class VerifyEmailOut(BaseModel):
    ok: bool = True
    published: int = 0  # debates that went public with the confirmed address


# --- API tokens ---------------------------------------------------------------


class CreateApiTokenRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    # None = the token never expires.
    expires_in_days: int | None = Field(default=None, ge=1, le=3650)
    # Credits the token may spend in total; None = no limit, 0 = free models only.
    spend_limit_usd: float | None = Field(default=None, ge=0, le=100_000)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("Give the token a name")
        return value


class ApiTokenOut(BaseModel):
    id: str
    name: str
    token_hint: str  # "debatr_…a1b2"
    created_at: datetime
    last_used_at: datetime | None = None
    expires_at: datetime | None = None
    expired: bool = False
    spend_limit_usd: float | None = None
    # Credits charged for the runs the token started (and their voices / pictures).
    spent_usd: float = 0.0


class ApiTokenCreated(ApiTokenOut):
    token: str  # the secret, shown only in this response


# --- `debatr login` (device authorization, RFC 8628 style) ---------------------

DeviceStatus = Literal["pending", "approved", "denied", "expired"]


class DeviceStartRequest(BaseModel):
    client_name: str = Field(default="Debatr CLI", min_length=1, max_length=100)

    @field_validator("client_name")
    @classmethod
    def _client_name(cls, value: str) -> str:
        return " ".join(value.split()) or "Debatr CLI"


class DeviceStartOut(BaseModel):
    device_code: str  # secret, only the CLI knows it
    user_code: str  # "WDJB-MJHT", confirmed by the user in the browser
    verification_uri: str
    verification_uri_complete: str
    expires_in: int  # seconds
    interval: int  # seconds between polls


class DeviceInfoOut(BaseModel):
    user_code: str
    client_name: str
    status: DeviceStatus
    expires_at: datetime


class DevicePollRequest(BaseModel):
    device_code: str = Field(min_length=1, max_length=200)


class DevicePollOut(BaseModel):
    status: DeviceStatus
    # Only once, in the first poll after the approval.
    token: str | None = None
    api_token: ApiTokenOut | None = None
