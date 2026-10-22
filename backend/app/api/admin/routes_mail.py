"""The Mail page (`/api/admin/mail*`): every letter the site sent or tried to, what the relay
said and what the sending service reported later (services/mail_log), how the relay is set up,
and a test letter.

Reading needs `users` (the letters name accounts' addresses); the test letter `system`.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.access import AdminContext, read_only_db, require_admin
from app.core.db import get_db
from app.models.models import User, utcnow
from app.schemas.admin import MailOut, MailPage, MailQuery, MailStatusOut, MailTestRequest
from app.services import mail_log
from app.services.admin import audit
from app.services.admin import mail as mail_admin

router = APIRouter()
read_mail = require_admin("users")
manage_system = require_admin("system")


@router.get("/mail", response_model=MailPage)
async def list_mail(
    query: Annotated[MailQuery, Query()],
    _ctx: AdminContext = Depends(read_mail),
    db: AsyncSession = Depends(read_only_db),
) -> MailPage:
    total, rows = await mail_admin.list_letters(db, query, utcnow())
    return MailPage.model_validate(
        {"total": total, "limit": query.limit, "offset": query.offset, "rows": rows}
    )


@router.get("/mail/status", response_model=MailStatusOut)
async def mail_status(
    _ctx: AdminContext = Depends(read_mail),
    db: AsyncSession = Depends(read_only_db),
) -> MailStatusOut:
    return MailStatusOut.model_validate(await mail_admin.status(db, utcnow()))


@router.post("/mail/test", response_model=MailOut)
async def test_mail(
    body: MailTestRequest,
    request: Request,
    ctx: AdminContext = Depends(manage_system),
    db: AsyncSession = Depends(get_db),
) -> MailOut:
    """Send a test letter now and wait for the relay's answer (recorded like any letter; on the
    account's card when the address has one)."""
    owner = await db.scalar(select(User.id).where(User.email == body.to))
    row = await mail_log.deliver(
        mail_log.test_letter(body.to, ctx.user.email), kind="test", user_id=owner
    )
    await audit.record(
        db,
        "mail.tested",
        request=request,
        actor=ctx.user,
        target_type="user" if owner else None,
        target_id=owner,
        after={"to": body.to, "status": row.status, "reply": row.reply, "error": row.error},
        ok=row.status == "sent",
    )
    return MailOut.model_validate(mail_admin.letter_out(row))
