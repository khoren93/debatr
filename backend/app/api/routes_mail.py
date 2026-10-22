"""The sending service's webhook: `POST /api/mail/events` (Resend → Webhooks, events
`email.sent`, `delivered`, `delivery_delayed`, `bounced`, `complained`, `suppressed`, `failed`;
signing secret in MAIL_WEBHOOK_SECRET). What it reports lands on the letter in the console's Mail
page (services/mail_log)."""

import json
import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_db
from app.services import mail_log

router = APIRouter()

MAX_BODY_BYTES = 256 * 1024


@router.post("/events", status_code=status.HTTP_204_NO_CONTENT)
async def mail_events(request: Request, db: AsyncSession = Depends(get_db)) -> Response:
    secret = settings.MAIL_WEBHOOK_SECRET
    if not secret:
        raise HTTPException(status_code=404, detail="Not found")
    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Too large")
    if not mail_log.signature_ok(secret, request.headers, body, time.time()):
        raise HTTPException(status_code=401, detail="Bad signature")
    try:
        event = json.loads(body)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="Not JSON") from e
    if isinstance(event, dict):
        event_id = request.headers.get("svix-id") or request.headers.get("webhook-id")
        await mail_log.apply_event(db, event, event_id=event_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
