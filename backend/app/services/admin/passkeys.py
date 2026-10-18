"""Passkeys (WebAuthn) of the admin console: a second factor in place of the TOTP code.

An admin adds passkeys on the Security page (after sudo); the sign-in page then offers "Use a
passkey" after the password, and sudo accepts one too. TOTP stays: the first sign-in enrolls
it, and it (or a recovery code) still works when no passkey is at hand, so a lost passkey never
locks an admin out. User verification (PIN or biometrics) is required: a passkey is then a
second factor on its own. The relying party is the console's host: ADMIN_HOST over https in
production, the page's own origin in development (the gate has checked it for POSTs). A
challenge lives CHALLENGE_SECONDS (in the sign-in ticket, or in Redis for the session) and is
used once. Only public keys are stored (`admin_passkeys`).
"""

import json
from typing import Any
from urllib.parse import urlsplit

from fastapi import Request
from redis.asyncio import Redis as AsyncRedis
from webauthn import (
    base64url_to_bytes,
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import bytes_to_base64url
from webauthn.helpers.exceptions import (
    InvalidAuthenticationResponse,
    InvalidJSONStructure,
    InvalidRegistrationResponse,
)
from webauthn.helpers.structs import (
    AttestationConveyancePreference,
    AuthenticatorSelectionCriteria,
    AuthenticatorTransport,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from app.core.config import settings
from app.models.models import AdminPasskey, User

RP_NAME = "Debatr admin"
CHALLENGE_SECONDS = 300
TIMEOUT_MS = CHALLENGE_SECONDS * 1000
MAX_PASSKEYS = 10
TRANSPORTS = {t.value: t for t in AuthenticatorTransport}


class PasskeyError(ValueError):
    """A passkey answer that does not verify (the message is safe to show)."""


def relying_party(request: Request) -> tuple[str, str]:
    """(RP ID, expected origin) for this request."""
    host = settings.admin_hostname
    if settings.is_production:
        return host, f"https://{host}"
    origin = request.headers.get("origin") or (
        f"{request.url.scheme}://{request.headers.get('host', 'localhost')}"
    )
    return urlsplit(origin).hostname or "localhost", origin.rstrip("/")


def _transports(names: list[str]) -> list[AuthenticatorTransport]:
    return [TRANSPORTS[name] for name in names if name in TRANSPORTS]


def _descriptors(passkeys: list[AdminPasskey]) -> list[PublicKeyCredentialDescriptor]:
    return [
        PublicKeyCredentialDescriptor(
            id=base64url_to_bytes(p.credential_id), transports=_transports(p.transports or [])
        )
        for p in passkeys
    ]


def registration_options(
    user: User, existing: list[AdminPasskey], rp_id: str
) -> tuple[dict[str, Any], str]:
    """(options for navigator.credentials.create, the challenge as base64url)."""
    options = generate_registration_options(
        rp_id=rp_id,
        rp_name=RP_NAME,
        user_name=user.email,
        user_id=user.id.bytes,
        user_display_name=user.display_name or user.email,
        timeout=TIMEOUT_MS,
        attestation=AttestationConveyancePreference.NONE,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
        exclude_credentials=_descriptors(existing),
    )
    return json.loads(options_to_json(options)), bytes_to_base64url(options.challenge)


def authentication_options(passkeys: list[AdminPasskey], rp_id: str) -> tuple[dict[str, Any], str]:
    """(options for navigator.credentials.get, the challenge as base64url)."""
    options = generate_authentication_options(
        rp_id=rp_id,
        timeout=TIMEOUT_MS,
        allow_credentials=_descriptors(passkeys),
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    return json.loads(options_to_json(options)), bytes_to_base64url(options.challenge)


def new_passkey(
    user: User, name: str, credential: dict[str, Any], challenge: str, rp_id: str, origin: str
) -> AdminPasskey:
    """Verify a registration answer and build the row (the caller checks duplicates, saves)."""
    try:
        verified = verify_registration_response(
            credential=credential,
            expected_challenge=base64url_to_bytes(challenge),
            expected_rp_id=rp_id,
            expected_origin=origin,
            require_user_verification=True,
        )
    except (InvalidRegistrationResponse, InvalidJSONStructure, ValueError, KeyError) as exc:
        raise PasskeyError(f"The passkey could not be verified ({exc})") from None
    response = credential.get("response")
    names = response.get("transports") if isinstance(response, dict) else None
    transports = [t for t in names if t in TRANSPORTS] if isinstance(names, list) else []
    return AdminPasskey(
        user_id=user.id,
        credential_id=bytes_to_base64url(verified.credential_id),
        public_key=verified.credential_public_key,
        sign_count=verified.sign_count,
        transports=transports,
        name=name,
        aaguid=verified.aaguid,
        backed_up=verified.credential_backed_up,
    )


def matching(passkeys: list[AdminPasskey], credential: dict[str, Any]) -> AdminPasskey:
    raw = credential.get("rawId") or credential.get("id")
    found = next((p for p in passkeys if p.credential_id == raw), None)
    if found is None:
        raise PasskeyError("This passkey is not registered for your account")
    return found


def check_assertion(
    passkey: AdminPasskey, credential: dict[str, Any], challenge: str, rp_id: str, origin: str
) -> tuple[int, bool]:
    """Verify a sign-in answer: (the new sign count, backed up)."""
    try:
        verified = verify_authentication_response(
            credential=credential,
            expected_challenge=base64url_to_bytes(challenge),
            expected_rp_id=rp_id,
            expected_origin=origin,
            credential_public_key=passkey.public_key,
            credential_current_sign_count=passkey.sign_count,
            require_user_verification=True,
        )
    except (InvalidAuthenticationResponse, InvalidJSONStructure, ValueError, KeyError) as exc:
        raise PasskeyError(f"The passkey could not be verified ({exc})") from None
    return verified.new_sign_count, verified.credential_backed_up


# --- challenges of a signed-in session (sign-in challenges live in the ticket) ------------------


def _challenge_key(session_hash: str, purpose: str) -> str:
    return f"admin:webauthn:{purpose}:{session_hash}"


async def remember_challenge(
    redis: AsyncRedis, session_hash: str, purpose: str, challenge: str
) -> None:
    await redis.set(_challenge_key(session_hash, purpose), challenge, ex=CHALLENGE_SECONDS)


async def take_challenge(redis: AsyncRedis, session_hash: str, purpose: str) -> str | None:
    """The waiting challenge, removed (a challenge works once)."""
    raw = await redis.getdel(_challenge_key(session_hash, purpose))
    if raw is None:
        return None
    return raw.decode() if isinstance(raw, bytes) else str(raw)
