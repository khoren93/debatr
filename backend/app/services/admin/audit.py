"""The admin audit log (`admin_audit_log`, append-only in the database).

Every console action and security event goes through `record` (API) or `record_sync` (server
commands), in the transaction of the action itself when there is one. `before` / `after` are
scrubbed of secret fields whatever the caller passes.
"""

import json
import uuid
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models.models import AdminAuditLog, User

# Never written to the log, at any depth.
SECRET_FIELDS = frozenset(
    {
        "password",
        "password_hash",
        "openrouter_key_enc",
        "totp_secret_enc",
        "recovery_codes_json",
        "token_hash",
        "secret",
        "code",
    }
)
SERVER_ACTOR = "server (app.manage)"


def scrub(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: scrub(v) for k, v in value.items() if str(k) not in SECRET_FIELDS}
    if isinstance(value, list | tuple):
        return [scrub(v) for v in value]
    return value


def client_ip(request: Request | None) -> str | None:
    if request is None or request.client is None:
        return None
    return request.client.host[:64]


def user_agent(request: Request | None) -> str | None:
    if request is None:
        return None
    return (request.headers.get("user-agent") or "")[:300] or None


def json_safe(value: Any) -> Any:
    """Values a JSON column can hold (dates, decimals and ids become strings)."""
    return json.loads(json.dumps(value, default=str))


def _entry(
    *,
    action: str,
    actor: User | None,
    actor_user_id: uuid.UUID | None,
    actor_email: str | None,
    target_type: str | None,
    target_id: str | uuid.UUID | None,
    reason: str | None,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    ip: str | None,
    agent: str | None,
    ok: bool,
) -> AdminAuditLog:
    return AdminAuditLog(
        actor_user_id=actor.id if actor else actor_user_id,
        actor_email=((actor.email if actor else actor_email) or None),
        action=action[:64],
        target_type=target_type,
        target_id=str(target_id)[:64] if target_id is not None else None,
        reason=reason,
        before_json=json_safe(scrub(before)) if before is not None else None,
        after_json=json_safe(scrub(after)) if after is not None else None,
        ip=ip,
        user_agent=agent,
        ok=ok,
    )


async def record(
    db: AsyncSession,
    action: str,
    *,
    request: Request | None,
    actor: User | None = None,
    actor_user_id: uuid.UUID | None = None,
    actor_email: str | None = None,
    target_type: str | None = None,
    target_id: str | uuid.UUID | None = None,
    reason: str | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    ok: bool = True,
    commit: bool = True,
) -> AdminAuditLog:
    entry = _entry(
        action=action,
        actor=actor,
        actor_user_id=actor_user_id,
        actor_email=actor_email,
        target_type=target_type,
        target_id=target_id,
        reason=reason,
        before=before,
        after=after,
        ip=client_ip(request),
        agent=user_agent(request),
        ok=ok,
    )
    db.add(entry)
    if commit:
        await db.commit()
    return entry


def record_sync(
    db: Session,
    action: str,
    *,
    target: User | None = None,
    reason: str | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> AdminAuditLog:
    """A server command's change (committed by the caller with the change itself)."""
    entry = _entry(
        action=action,
        actor=None,
        actor_user_id=None,
        actor_email=SERVER_ACTOR,
        target_type="user" if target else None,
        target_id=target.id if target else None,
        reason=reason,
        before=before,
        after=after,
        ip=None,
        agent=None,
        ok=True,
    )
    db.add(entry)
    return entry
