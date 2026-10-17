"""Free Router participants (`openrouter/free`).

OpenRouter's free router picks a random free model for every request and names it in the
response's `model` field. A debater that switched models every turn would make the lineup, the
video and the leaderboard meaningless, so the free model of a participant's first answer is
pinned for the rest of the debate: it goes into `DebateParticipant.model_id` (what the lineup,
the gallery filter and the leaderboard read), while `config_json` keeps the router so remixes
and drafts ask the router again. Only `:free` variants are pinned, so a pin never costs money.

The router also picks models that cannot debate (a content-safety classifier answered a turn
with "User Safety: safe"), so only a real turn pins: enough words, no classifier in the id.
Such a turn is still saved with the model that wrote it, and the next turn asks the router again.
"""

from collections.abc import Sequence
from typing import Any

from app.models.models import DebateParticipant

FREE_ROUTER_ID = "openrouter/free"  # mirrors FREE_ROUTER_ID in frontend/src/lib/modelNames.ts
FREE_SUFFIX = ":free"
MAX_MODEL_ID_LENGTH = 200  # ParticipantConfig.model_id
MIN_PIN_WORDS = 20  # the shortest turns ask for ~50 words (prompt_builder.LENGTH_WORDS)
NON_CHAT_MARKERS = ("guard", "safety", "moderation")  # classifiers among the free models


def is_free_router(model_id: str | None) -> bool:
    return model_id == FREE_ROUTER_ID


def routed_model(model_id: str | None) -> str | None:
    """A concrete free model a router answered with, or None (missing, odd or not free)."""
    value = (model_id or "").strip()
    if (
        not value
        or is_free_router(value)
        or "/" not in value
        or not value.endswith(FREE_SUFFIX)
        or len(value) > MAX_MODEL_ID_LENGTH
        or any(c.isspace() for c in value)
    ):
        return None
    return value


def participant_row(
    rows: Sequence[DebateParticipant], index: int, role: str | None
) -> DebateParticipant | None:
    """The normalized row of the config's participant `index` (rows follow the config order)."""
    if 0 <= index < len(rows) and rows[index].role == role:
        return rows[index]
    return None


def pinned_model(requested: str, row: DebateParticipant | None) -> str | None:
    """The free model pinned for a Free Router participant, if its first answer pinned one."""
    if not is_free_router(requested) or row is None:
        return None
    return routed_model(row.model_id)


def worth_pinning(model_id: str, text: str) -> bool:
    """Whether an answer looks like a debate turn, so its model may speak for the participant."""
    lowered = model_id.lower()
    return len(text.split()) >= MIN_PIN_WORDS and not any(m in lowered for m in NON_CHAT_MARKERS)


def resolved_participants(
    participants: list[dict[str, Any]], rows: Sequence[DebateParticipant]
) -> list[dict[str, Any]]:
    """Config participants with each Free Router replaced by its pinned model (video lineup)."""
    resolved: list[dict[str, Any]] = []
    for i, p in enumerate(participants):
        pinned = pinned_model(str(p.get("model_id") or ""), participant_row(rows, i, p.get("role")))
        resolved.append({**p, "model_id": pinned} if pinned else p)
    return resolved
