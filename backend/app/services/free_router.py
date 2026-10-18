"""Free Router participants (`openrouter/free`).

OpenRouter's free router picks a random free model for every request and names it in the
response's `model` field. A debater that switched models every turn would make the lineup, the
video and the leaderboard meaningless, so the free model of a participant's first answer is
pinned for the rest of the debate: it goes into `DebateParticipant.model_id` (what the lineup,
the gallery filter and the leaderboard read), while `config_json` keeps the router so remixes
and drafts ask the router again. Only `:free` variants are pinned, so a pin never costs money.

The router also picks models that cannot debate (a content-safety classifier answered a turn
with "User Safety: safe"). The worker drops such a pick as soon as the stream's first chunk names
it, before any text reaches the viewers, and asks the router again; an answer too short for a
turn is asked again too (`orchestrator._ask_router`). Only a real turn pins its model.

The router sometimes picks a classifier for every try of a turn (seen with a content-safety
model, several debates in a row), which used to stop the debate. Then the turn goes to a free
model that argued well lately instead (`fallback_models`, from `provider_usage`), and that model
is pinned like any router pick.
"""

from collections.abc import Iterable, Sequence
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select

from app.models.models import DebateParticipant, ProviderUsage, utcnow

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


def is_classifier(model_id: str) -> bool:
    """A free model that labels text instead of answering it (guard / safety / moderation)."""
    lowered = model_id.lower()
    return any(m in lowered for m in NON_CHAT_MARKERS)


def worth_pinning(model_id: str, text: str) -> bool:
    """Whether an answer looks like a debate turn, so its model may speak for the participant."""
    return len(text.split()) >= MIN_PIN_WORDS and not is_classifier(model_id)


def resolved_participants(
    participants: list[dict[str, Any]], rows: Sequence[DebateParticipant]
) -> list[dict[str, Any]]:
    """Config participants with each Free Router replaced by its pinned model (video lineup)."""
    resolved: list[dict[str, Any]] = []
    for i, p in enumerate(participants):
        pinned = pinned_model(str(p.get("model_id") or ""), participant_row(rows, i, p.get("role")))
        resolved.append({**p, "model_id": pinned} if pinned else p)
    return resolved


# --- fallback models (when the router keeps picking classifiers) -------------------------------

FALLBACK_DAYS = 7
FALLBACK_LIMIT = 3
FALLBACK_MIN_ANSWERS = 2
FALLBACK_MIN_SUCCESS = 0.8


def pick_fallbacks(
    rows: Iterable[tuple[str, int, int]], exclude: Iterable[str] = (), limit: int = FALLBACK_LIMIT
) -> list[str]:
    """(model, answered, tries) of recent `:free` turns -> the steadiest debaters, best first:
    concrete chat models that answered at least FALLBACK_MIN_ANSWERS turns and
    FALLBACK_MIN_SUCCESS of their tries."""
    skip = set(exclude)
    good = [
        (answered / tries, answered, model)
        for model, answered, tries in rows
        if routed_model(model)
        and not is_classifier(model)
        and model not in skip
        and tries > 0
        and answered >= FALLBACK_MIN_ANSWERS
        and answered / tries >= FALLBACK_MIN_SUCCESS
    ]
    good.sort(key=lambda g: (-g[0], -g[1], g[2]))
    return [model for _, _, model in good[:limit]]


def fallback_models(exclude: Iterable[str] = ()) -> list[str]:
    """Free models that answered debate turns well in the last FALLBACK_DAYS (never raises)."""
    from app.core.sync_db import get_sync_session  # worker side only

    try:
        with get_sync_session() as db:
            rows = db.execute(
                select(
                    ProviderUsage.model,
                    func.count().filter(ProviderUsage.ok.is_(True)),
                    func.count(),
                )
                .where(
                    ProviderUsage.purpose == "turn",
                    ProviderUsage.model.like(f"%{FREE_SUFFIX}"),
                    ProviderUsage.created_at >= utcnow() - timedelta(days=FALLBACK_DAYS),
                )
                .group_by(ProviderUsage.model)
            ).all()
    except Exception:  # a broken lookup must not stop the turn any more than it already is
        return []
    return pick_fallbacks(((str(m), int(a), int(t)) for m, a, t in rows), exclude)
