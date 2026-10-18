"""The admin audit log (`admin_audit_log`, append-only in the database).

Every console action and security event goes through `record` (API) or `record_sync` (server
commands), in the transaction of the action itself when there is one. `before` / `after` are
scrubbed of secret fields whatever the caller passes. The audit page reads it with
`audit_conditions` / `list_entries` / `facets` / `security_summary`.
"""

import json
import uuid
from datetime import UTC, datetime, time, timedelta
from typing import Any

from fastapi import Request
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.models.models import AdminAuditLog, User
from app.schemas.admin import AuditQuery

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


# --- reading (the audit page) -------------------------------------------------------------------

# The security tab: sign-ins and their failures, second factor, sessions, sudo, roles.
SECURITY_PREFIXES = ("auth.", "role.")
FAILURES = ("auth.login_failed", "auth.totp_failed", "auth.sudo_failed", "auth.passkey_failed")
FACETS_LIMIT = 200


def _like(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _day_start(day: Any) -> datetime:
    return datetime.combine(day, time.min, UTC)


def audit_conditions(query: AuditQuery) -> list[ColumnElement[bool]]:
    log = AdminAuditLog
    conditions: list[ColumnElement[bool]] = []
    if query.tab == "security":
        conditions.append(or_(*(log.action.startswith(p) for p in SECURITY_PREFIXES)))
    action = query.action.strip()
    if action.endswith("."):
        conditions.append(log.action.startswith(action, autoescape=True))
    elif action:
        conditions.append(log.action == action)
    if query.actor.strip():
        conditions.append(log.actor_email == query.actor.strip())
    if query.target_type.strip():
        conditions.append(log.target_type == query.target_type.strip())
    if query.target_id.strip():
        conditions.append(log.target_id == query.target_id.strip())
    if query.ok is not None:
        conditions.append(log.ok.is_(query.ok))
    if query.created_from:
        conditions.append(log.created_at >= _day_start(query.created_from))
    if query.created_to:
        conditions.append(log.created_at < _day_start(query.created_to) + timedelta(days=1))
    text = query.q.strip()
    if text:
        pattern = _like(text)
        conditions.append(
            or_(
                *(
                    column.ilike(pattern, escape="\\")
                    for column in (log.action, log.actor_email, log.target_id, log.ip, log.reason)
                )
            )
        )
    return conditions


def entry_out(entry: AdminAuditLog) -> dict[str, Any]:
    return {
        "id": str(entry.id),
        "created_at": entry.created_at,
        "actor_user_id": str(entry.actor_user_id) if entry.actor_user_id else None,
        "actor_email": entry.actor_email,
        "action": entry.action,
        "target_type": entry.target_type,
        "target_id": entry.target_id,
        "reason": entry.reason,
        "before": entry.before_json,
        "after": entry.after_json,
        "ip": entry.ip,
        "user_agent": entry.user_agent,
        "ok": entry.ok,
    }


async def list_entries(db: AsyncSession, query: AuditQuery) -> tuple[int, list[dict[str, Any]]]:
    conditions = audit_conditions(query)
    total = await db.scalar(select(func.count()).select_from(AdminAuditLog).where(*conditions))
    rows = await db.scalars(
        select(AdminAuditLog)
        .where(*conditions)
        .order_by(AdminAuditLog.created_at.desc(), AdminAuditLog.id)
        .limit(query.limit)
        .offset(query.offset)
    )
    return int(total or 0), [entry_out(entry) for entry in rows.all()]


async def facets(db: AsyncSession) -> dict[str, list[dict[str, Any]]]:
    """Values the filters offer, most frequent first."""

    async def counts(column: Any) -> list[dict[str, Any]]:
        rows = await db.execute(
            select(column, func.count())
            .where(column.is_not(None))
            .group_by(column)
            .order_by(func.count().desc(), column)
            .limit(FACETS_LIMIT)
        )
        return [{"value": str(value), "count": int(n)} for value, n in rows.all()]

    return {
        "actions": await counts(AdminAuditLog.action),
        "actors": await counts(AdminAuditLog.actor_email),
        "target_types": await counts(AdminAuditLog.target_type),
    }


async def security_summary(db: AsyncSession, now: datetime) -> dict[str, Any]:
    log = AdminAuditLog
    since = now - timedelta(days=7)
    row = (
        await db.execute(
            select(
                func.count().filter(log.action == "auth.signed_in"),
                func.count().filter(log.action.in_(FAILURES)),
                func.count().filter(log.action == "auth.locked"),
                func.count().filter(log.action == "auth.recovery_code_used"),
                func.count(func.distinct(log.ip)).filter(log.action.startswith("auth.")),
            ).where(log.created_at >= since)
        )
    ).one()
    last = await db.scalar(
        select(log)
        .where(log.action.in_((*FAILURES, "auth.locked")))
        .order_by(log.created_at.desc())
        .limit(1)
    )
    return {
        "sign_ins": int(row[0] or 0),
        "failures": int(row[1] or 0),
        "locks": int(row[2] or 0),
        "recovery_codes_used": int(row[3] or 0),
        "addresses": int(row[4] or 0),
        "last_failure": entry_out(last) if last else None,
    }
