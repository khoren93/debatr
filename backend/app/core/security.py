"""Password hashing and encryption of user-supplied provider keys."""

import base64
import hashlib
import secrets

import bcrypt
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings

# bcrypt ignores everything after 72 bytes; refuse longer passwords at the schema level.
MAX_PASSWORD_BYTES = 72


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False  # an account without a password (Google only)
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
    except (ValueError, TypeError):
        return False


def _fernet(secret: str | None = None) -> Fernet:
    raw = (secret or settings.SECRET_KEY).encode("utf-8")
    key = base64.urlsafe_b64encode(hashlib.sha256(raw).digest())
    return Fernet(key)


def encrypt_secret(value: str, secret: str | None = None) -> str:
    return _fernet(secret).encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(token: str, secret: str | None = None) -> str | None:
    """Return the plaintext, or None when the token is invalid (e.g. SECRET_KEY changed)."""
    try:
        return _fernet(secret).decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, TypeError):
        return None


def key_last4(value: str) -> str:
    return value.strip()[-4:]


def mask_key(last4: str | None, prefix: str = "sk-or-") -> str | None:
    if not last4:
        return None
    return f"{prefix}••••••••{last4}"


def random_token(nbytes: int = 16) -> str:
    return secrets.token_urlsafe(nbytes)


# --- API tokens (CLI, scripts, MCP agents) ------------------------------------

# A fixed prefix makes leaked tokens easy to recognise (and to register with secret scanners).
API_TOKEN_PREFIX = "debatr_"
_API_TOKEN_BYTES = 32  # 256 bits of randomness -> 43 url-safe characters
_API_TOKEN_MIN_LENGTH = len(API_TOKEN_PREFIX) + 40
_API_TOKEN_MAX_LENGTH = len(API_TOKEN_PREFIX) + 64


def new_api_token() -> str:
    return API_TOKEN_PREFIX + secrets.token_urlsafe(_API_TOKEN_BYTES)


def hash_api_token(token: str) -> str:
    """Lookup hash of an API token. Tokens are 256-bit random values, so a fast unsalted hash is
    enough (unlike passwords) and keeps the lookup a single indexed query."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def looks_like_api_token(value: str) -> bool:
    return (
        value.startswith(API_TOKEN_PREFIX)
        and _API_TOKEN_MIN_LENGTH <= len(value) <= _API_TOKEN_MAX_LENGTH
        and value.isascii()
    )


def mask_api_token(last4: str) -> str:
    return f"{API_TOKEN_PREFIX}…{last4}"


# --- Admin console TOTP secrets -------------------------------------------------

# A key of their own (derived from SECRET_KEY with another context), so an OpenRouter key and a
# TOTP secret never share an encryption key.
_TOTP_CONTEXT = ":admin-totp"


def encrypt_totp_secret(value: str) -> str:
    return encrypt_secret(value, settings.SECRET_KEY + _TOTP_CONTEXT)


def decrypt_totp_secret(token: str) -> str | None:
    """None when unreadable (SECRET_KEY changed): reset with `app.manage admin reset-2fa`."""
    return decrypt_secret(token, settings.SECRET_KEY + _TOTP_CONTEXT)
