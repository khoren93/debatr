"""Email confirmation and password reset: the links we mail, and what waits for a confirmed
address.

- A link carries a random token; Redis keeps only its hash (`email_token_key`) with the account,
  its email and, for a reset, its session epoch, so a reset link dies once the password changes.
  A reset link works once (GETDEL); a confirmation link may be opened again until it expires
  (confirming twice changes nothing, and the page may post it twice).
- `pending`: accounts made since confirmations exist (`email_check_required`) publish to the
  gallery and top up only with a confirmed address; older accounts are only asked to confirm.
  A debate finished or published before that stays private with its wish noted, and goes public
  when the address is confirmed (`publish_waiting`).
"""

import hashlib
import json
import logging
import secrets
import uuid
from email.message import EmailMessage
from typing import Any, Literal

from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.redis import email_token_key, get_async_redis
from app.models.models import Debate, User, utcnow
from app.services import indexnow, mail
from app.services.moderation import publish_async, should_auto_publish

logger = logging.getLogger(__name__)

LinkKind = Literal["verify", "reset"]
LINK_SECONDS: dict[LinkKind, int] = {"verify": 3 * 24 * 3600, "reset": 3600}
PATHS: dict[LinkKind, str] = {"verify": "/verify-email", "reset": "/reset-password"}
MAILS_PER_HOUR = 3  # confirmation or reset mails to one account / address


def pending(user: User) -> bool:
    """Publishing and top-ups wait for this account to confirm its email."""
    return bool(user.email_check_required) and user.email_verified_at is None


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def link(kind: LinkKind, token: str) -> str:
    return f"{settings.SITE_URL.rstrip('/')}{PATHS[kind]}?token={token}"


async def issue(kind: LinkKind, user: User) -> str:
    """A new link's token (raises RedisError when Redis is down)."""
    token = secrets.token_urlsafe(32)
    data = {"uid": str(user.id), "email": user.email, "epoch": user.session_epoch}
    await get_async_redis().set(
        email_token_key(kind, _digest(token)), json.dumps(data), ex=LINK_SECONDS[kind]
    )
    return token


async def read(kind: LinkKind, token: str) -> dict[str, Any] | None:
    """What a link stands for, or None (unknown, expired, used). A reset link is used up here."""
    if not token or len(token) > 200:
        return None
    key = email_token_key(kind, _digest(token))
    redis = get_async_redis()
    raw = await (redis.getdel(key) if kind == "reset" else redis.get(key))
    if raw is None:
        return None
    try:
        data = json.loads(raw)
        uuid.UUID(str(data["uid"]))
    except (ValueError, KeyError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def matches(data: dict[str, Any] | None, user: User | None, *, epoch: bool = False) -> bool:
    """The link still belongs to this account: same address (and, for a reset, no password
    change since it was mailed)."""
    if data is None or user is None or not user.is_active or data.get("email") != user.email:
        return False
    return not epoch or data.get("epoch") == user.session_epoch


def confirm(user: User) -> bool:
    """Mark the address confirmed; True when it was not yet (the caller commits)."""
    if user.email_verified_at is not None:
        return False
    user.email_verified_at = utcnow()
    return True


async def publish_waiting(db: AsyncSession, user: User) -> int:
    """Publish the owner's finished debates that waited for the confirmed address (approved,
    clean, the owner asked for the gallery); commits. Returns how many went public."""
    rows = await db.scalars(
        select(Debate)
        .where(
            Debate.user_id == user.id,
            Debate.status == "completed",
            Debate.is_public.is_(False),
            Debate.moderation_status == "approved",
        )
        .options(selectinload(Debate.turns))
    )
    published: list[Debate] = []
    for debate in rows:
        if should_auto_publish(debate) and await publish_async(db, debate):
            published.append(debate)
    if published:
        await db.commit()
        refs = [ref for d in published for ref in indexnow.debate_refs(d)]
        await indexnow.announce(refs)
        logger.info("Published %d debates of %s after the email check", len(published), user.id)
    return len(published)


def confirmation_mail(name: str, email: str, token: str) -> EmailMessage:
    text, html = mail.letter(
        title="Confirm your email",
        lines=[
            f"Hi {name},",
            f"Confirm that {email} is yours: then your debates can go to the public gallery and "
            "you can add credits.",
        ],
        button="Confirm my email",
        url=link("verify", token),
        footer="The link works for 3 days. If you did not sign up for Debatr, ignore this email.",
    )
    return mail.build_message(email, "Confirm your email for Debatr", text, html)


def reset_mail(name: str, email: str, token: str) -> EmailMessage:
    text, html = mail.letter(
        title="Reset your password",
        lines=[
            f"Hi {name},",
            f"Someone, hopefully you, asked to reset the password of the Debatr account {email}.",
        ],
        button="Set a new password",
        url=link("reset", token),
        footer="The link works for an hour, once. If it was not you, ignore this email: your "
        "password stays as it is.",
    )
    return mail.build_message(email, "Reset your Debatr password", text, html)


async def mail_link(kind: LinkKind, user: User) -> EmailMessage | None:
    """The letter with a fresh link for this account, or None when Redis is down (logged): the
    caller sends it after its response."""
    try:
        token = await issue(kind, user)
    except RedisError:
        logger.warning("Could not store a %s link for %s", kind, user.id)
        return None
    build = confirmation_mail if kind == "verify" else reset_mail
    return build(user.display_name, user.email, token)
