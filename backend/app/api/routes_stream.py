import json
import logging
import uuid
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.api.serializers import can_view
from app.core.auth import get_current_user
from app.core.config import TERMINAL_DEBATE_STATUSES
from app.core.db import AsyncSessionLocal, get_db
from app.core.redis import debate_channel, get_async_redis
from app.models.models import Debate, User
from app.services.events import TERMINAL_EVENTS

logger = logging.getLogger(__name__)
router = APIRouter()

_STATUS_EVENTS = {
    "completed": "debate_completed",
    "error": "debate_error",
    "stopped": "debate_stopped",
}


def _terminal_event(debate: Debate) -> dict[str, str]:
    event = _STATUS_EVENTS.get(debate.status, "debate_completed")
    data: dict[str, Any] = {"debate_id": str(debate.id), "status": debate.status}
    if debate.error_message:
        data["message"] = debate.error_message
    if debate.totals_json:
        data["totals"] = debate.totals_json
    return {"event": event, "data": json.dumps(data)}


@router.get("/{debate_id}/stream")
async def stream_debate(
    debate_id: str,
    request: Request,
    viewer: User | None = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EventSourceResponse:
    """Server-Sent Events for a debate. Closes when the debate reaches a terminal state."""
    try:
        uuid_id = uuid.UUID(debate_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="Invalid debate id") from e

    debate = await db.get(Debate, uuid_id)
    if not debate:
        raise HTTPException(status_code=404, detail="Debate not found")
    if not can_view(debate, viewer):
        raise HTTPException(status_code=403, detail="This debate is private")
    initial_status = debate.status

    async def event_generator() -> AsyncGenerator[dict[str, str], None]:
        channel = debate_channel(debate_id)
        pubsub = get_async_redis().pubsub()
        await pubsub.subscribe(channel)
        try:
            yield {
                "event": "connected",
                "data": json.dumps({"debate_id": debate_id, "status": initial_status}),
            }

            # Re-check after subscribing so a debate finishing in between isn't missed.
            async with AsyncSessionLocal() as session:
                current = await session.get(Debate, uuid_id)
            if current is None:
                return
            if current.status in TERMINAL_DEBATE_STATUSES:
                yield _terminal_event(current)
                return

            while not await request.is_disconnected():
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if not message or message.get("type") != "message":
                    continue
                try:
                    payload = json.loads(message["data"])
                except (json.JSONDecodeError, TypeError):
                    logger.warning("Malformed pub/sub message on %s", channel)
                    continue
                event_type = str(payload.get("event", "update"))
                yield {"event": event_type, "data": json.dumps(payload.get("data", {}))}
                if event_type in TERMINAL_EVENTS:
                    break
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()

    return EventSourceResponse(event_generator())
