"""The console's Mail page: the letters of `mail_messages` (services/mail_log) filtered and paged,
the last 7 days in numbers and how the relay is set up."""

import contextlib
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.core.config import settings
from app.models.models import MailMessage
from app.schemas.admin import MailQuery
from app.services import mail
from app.services.mail_log import PROBLEMS

NOT_SENT = ("failed", "off")


def _like(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def problem_clause() -> ColumnElement[bool]:
    return or_(MailMessage.status.in_(NOT_SENT), MailMessage.delivery.in_(PROBLEMS))


def conditions(query: MailQuery, now: datetime) -> list[ColumnElement[bool]]:
    m = MailMessage
    found: list[ColumnElement[bool]] = []
    match query.status:
        case None:
            pass
        case "problems":
            found.append(problem_clause())
        case "failed":
            found.append(or_(m.status == "failed", m.delivery == "failed"))
        case "sending" | "sent" | "off":
            found.append(m.status == query.status)
        case "waiting":
            found.extend((m.status == "sent", m.delivery.is_(None)))
        case _:
            found.append(m.delivery == query.status)
    if query.kind:
        found.append(m.kind == query.kind)
    if query.user_id:
        found.append(m.user_id == query.user_id)
    if query.days:
        found.append(m.created_at >= now - timedelta(days=query.days))
    text = query.q.strip()
    if text:
        pattern = _like(text.lower())
        options: list[ColumnElement[bool]] = [
            m.to_address.ilike(pattern, escape="\\"),
            m.subject.ilike(pattern, escape="\\"),
            m.provider_id == text,
        ]
        with contextlib.suppress(ValueError):
            options.append(m.id == uuid.UUID(text))
        found.append(or_(*options))
    return found


def letter_out(row: MailMessage) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "created_at": row.created_at,
        "user_id": str(row.user_id) if row.user_id else None,
        "kind": row.kind,
        "to_address": row.to_address,
        "subject": row.subject,
        "status": row.status,
        "reply": row.reply,
        "error": row.error,
        "duration_ms": row.duration_ms,
        "message_id": row.message_id,
        "provider_id": row.provider_id,
        "delivery": row.delivery,
        "delivery_at": row.delivery_at,
        "events": [
            {"type": e.get("type") or "?", "at": e.get("at"), "note": e.get("note")}
            for e in row.events_json or []
            if e.get("at")
        ],
    }


async def list_letters(
    db: AsyncSession, query: MailQuery, now: datetime
) -> tuple[int, list[dict[str, Any]]]:
    found = conditions(query, now)
    total = await db.scalar(select(func.count()).select_from(MailMessage).where(*found))
    rows = await db.scalars(
        select(MailMessage)
        .where(*found)
        .order_by(MailMessage.created_at.desc(), MailMessage.id)
        .limit(query.limit)
        .offset(query.offset)
    )
    return int(total or 0), [letter_out(row) for row in rows.all()]


def relay() -> dict[str, Any]:
    return {
        "configured": mail.enabled(),
        "host": settings.MAIL_SMTP_HOST,
        "port": settings.MAIL_SMTP_PORT,
        "user": settings.MAIL_SMTP_USER,
        "from_address": settings.MAIL_FROM,
        "reply_to": mail.reply_to(),
        "webhook": bool(settings.MAIL_WEBHOOK_SECRET),
        "webhook_url": f"{settings.SITE_URL.rstrip('/')}/api/mail/events",
        "log_days": settings.MAIL_LOG_DAYS,
    }


async def status(db: AsyncSession, now: datetime) -> dict[str, Any]:
    m = MailMessage
    row = (
        await db.execute(
            select(
                func.count(),
                func.count().filter(m.status == "sent"),
                func.count().filter(m.status.in_(NOT_SENT)),
                func.count().filter(m.delivery == "delivered"),
                func.count().filter(m.delivery.in_(PROBLEMS)),
            ).where(m.created_at >= now - timedelta(days=7))
        )
    ).one()
    last = await db.scalar(select(m).order_by(m.created_at.desc()).limit(1))
    failure = await db.scalar(
        select(m).where(problem_clause()).order_by(m.created_at.desc()).limit(1)
    )
    return {
        "relay": relay(),
        "last_7_days": {
            "letters": int(row[0] or 0),
            "sent": int(row[1] or 0),
            "not_sent": int(row[2] or 0),
            "delivered": int(row[3] or 0),
            "problems": int(row[4] or 0),
        },
        "last_letter": letter_out(last) if last else None,
        "last_failure": letter_out(failure) if failure else None,
    }
