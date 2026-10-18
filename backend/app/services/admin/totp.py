"""Second factor of the admin console (pure functions).

TOTP (RFC 6238: 30-second steps, 6 digits, any authenticator app), one-time recovery codes and
the enrollment code that `python -m app.manage admin grant` prints: setting up the authenticator
needs that code besides the password, so a leaked password alone cannot enroll a stranger's
phone before the admin enrolls theirs. Only hashes of recovery and enrollment codes are kept.
"""

import hashlib
import hmac
import secrets

import pyotp
import segno

ISSUER = "Debatr admin"
STEP_SECONDS = 30
DIGITS = 6
# Steps accepted either side of now: a phone clock up to 30 s off still works.
WINDOW = 1
RECOVERY_CODE_COUNT = 10
# No 0/O or 1/I/L: the codes are read off paper.
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def new_secret() -> str:
    """160 random bits, base32 (what authenticator apps expect)."""
    return pyotp.random_base32(length=32)


def provisioning_uri(secret: str, email: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=ISSUER)


def qr_data_uri(uri: str) -> str:
    """The provisioning URI as a QR code (an SVG data URI for an <img>)."""
    return segno.make(uri, error="m").svg_data_uri(scale=6, border=2, dark="#0b0c10")


def totp_digits(code: str) -> str:
    return "".join(ch for ch in code if ch.isdigit())


def matching_step(secret: str, code: str, *, now: float, after_step: int | None) -> int | None:
    """The time step `code` belongs to (within WINDOW of `now`), or None. Steps up to
    `after_step` (the last one accepted) are refused, so every code works only once."""
    digits = totp_digits(code)
    if len(digits) != DIGITS:
        return None
    totp = pyotp.TOTP(secret)
    current = int(now // STEP_SECONDS)
    found: int | None = None
    for step in range(current - WINDOW, current + WINDOW + 1):
        fresh = after_step is None or step > after_step
        if hmac.compare_digest(totp.generate_otp(step), digits) and fresh and found is None:
            found = step
    return found


def code_now(secret: str, now: float) -> str:
    """The code an authenticator shows at `now` (tests and the server-side enrollment check)."""
    return pyotp.TOTP(secret).generate_otp(int(now // STEP_SECONDS))


# --- recovery and enrollment codes ------------------------------------------------------------


def _random_code(groups: int, size: int) -> str:
    return "-".join(
        "".join(secrets.choice(CODE_ALPHABET) for _ in range(size)) for _ in range(groups)
    )


def normalize_code(code: str) -> str:
    return "".join(ch for ch in code.upper() if ch.isalnum())


def code_hash(code: str) -> str:
    return hashlib.sha256(normalize_code(code).encode()).hexdigest()


def new_recovery_codes() -> tuple[list[str], list[str]]:
    """Ten codes like "K7PQM-2XD9H" (about 49 bits each): (plain, hashes)."""
    plain = [_random_code(2, 5) for _ in range(RECOVERY_CODE_COUNT)]
    return plain, [code_hash(code) for code in plain]


def use_recovery_code(hashes: list[str], code: str) -> list[str] | None:
    """The hashes left after spending `code`, or None when it is not one of them."""
    wanted = code_hash(code)
    match: str | None = None
    for stored in hashes:
        if hmac.compare_digest(stored, wanted):
            match = stored
    if match is None or not normalize_code(code):
        return None
    return [stored for stored in hashes if stored != match]


def new_enrollment_code() -> str:
    """Like "K7PQ-M2XD-9HTA-WC4R" (about 79 bits)."""
    return _random_code(4, 4)
