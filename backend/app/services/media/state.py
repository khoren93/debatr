"""Persist media build progress on the Debate row and notify subscribers."""

import logging
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.models import Debate, utcnow
from app.services.events import publish_event

logger = logging.getLogger(__name__)


def free_build(debate: Debate) -> bool:
    """A build an admin queued from the console: the owner pays nothing for it (voices and AI
    pictures on the system keys; the cost stays in provider_usage)."""
    return bool((debate.media_json or {}).get("free"))


def set_media_state(
    db: Session,
    debate: Debate,
    *,
    status: str | None = None,
    step: str | None = None,
    current: int | None = None,
    total: int | None = None,
    message: str | None = None,
    error: str | None = None,
    started: bool = False,
    finished: bool = False,
    extra: dict[str, Any] | None = None,
) -> None:
    state: dict[str, Any] = dict(debate.media_json or {})
    if step is not None:
        state["step"] = step
    if current is not None:
        state["current"] = current
    if total is not None:
        state["total"] = total
    if message is not None:
        state["message"] = message
    state["error"] = error
    if started:
        state["started_at"] = _iso(utcnow())
        state["finished_at"] = None
    if finished:
        state["finished_at"] = _iso(utcnow())
    if extra:
        state.update(extra)
    if status is not None:
        debate.media_status = status
    debate.media_json = state  # reassign so SQLAlchemy sees the change
    db.commit()
    publish_event(
        str(debate.id),
        "media_progress",
        {
            "debate_id": str(debate.id),
            "media_status": debate.media_status,
            "step": state.get("step"),
            "current": state.get("current"),
            "total": state.get("total"),
            "message": state.get("message"),
            "error": state.get("error"),
        },
    )


def _iso(value: datetime) -> str:
    return value.isoformat()
