"""Request/response schemas for accounts."""

import re
from datetime import datetime

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
