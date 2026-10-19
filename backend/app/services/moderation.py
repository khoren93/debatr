"""Gallery moderation and auto-publishing.

Finished debates are public by default (`DebateConfig.auto_publish`), but only after an AI check:
the cheap model that structures the verdict (`services/verdict.py`) also answers whether the
topic, description and verdict are fine for a public gallery. The answer is never shown to
viewers. A flagged debate stays private until an admin approves it; when the check could not run
at all, the debate is flagged too (fail closed). Controversial topics are fine: debates are about
them.
"""

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.ids import new_slug
from app.models.models import Debate, utcnow

logger = logging.getLogger(__name__)

# none: never checked (older debates, stopped/failed runs) | approved | flagged | rejected
MODERATION_STATUSES = ("none", "approved", "flagged", "rejected")

MODERATION_RULES = (
    "Decide whether this debate may appear in a public gallery without a human check. "
    "Controversial, political, religious or uncomfortable questions are fine: that is what "
    "debates are for. Flag it only if the topic, description or verdict: promotes hatred or "
    "harassment of people for who they are; contains sexual content (any involving minors), "
    "or encourages violence, terrorism or self-harm; gives instructions for weapons, drugs or "
    "other serious harm; targets a real, identifiable private person, or accuses a real public "
    "figure of crimes as fact; is spam, advertising, gibberish or an obvious test."
)

MODERATION_JSON_SPEC = (
    '{"flag": <true if a human should review it before it goes public, else false>, '
    '"reason": <short English reason when flagged, else "">}'
)

FALLBACK_REASON = "The automatic check could not run."
MODERATION_MAX_TOKENS = 2000  # room for reasoning models before the short JSON answer


def _now() -> str:
    return utcnow().isoformat()


def parse_moderation(payload: Any) -> dict[str, Any] | None:
    """{"flag": bool, "reason": str} from the model -> {"flagged", "reason"}; None if unusable."""
    if not isinstance(payload, dict):
        return None
    flag = payload.get("flag")
    if isinstance(flag, str):
        flag = flag.strip().lower() in ("true", "yes", "1")
    if not isinstance(flag, bool):
        return None
    reason = str(payload.get("reason") or "").strip()[:300]
    return {"flagged": flag, "reason": reason if flag else ""}


def fallback_result() -> dict[str, Any]:
    return {"flagged": True, "reason": FALLBACK_REASON, "source": "fallback"}


def build_moderation_messages(
    *, topic: str, description: str | None, verdict_text: str = ""
) -> list[dict[str, str]]:
    system = "You are a content moderator. Reply with a single JSON object and nothing else."
    parts = [f"Topic: {topic}"]
    if description:
        parts.append(f"Description: {description}")
    if verdict_text:
        parts.append(f"Judge's verdict:\n{verdict_text[:4000]}")
    user = "\n".join(parts) + f"\n\n{MODERATION_RULES}\n\nReturn JSON: {MODERATION_JSON_SPEC}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def check_debate(
    conf: dict[str, Any], *, model: str, api_key: str | None = None, verdict_text: str = ""
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Stand-alone check for runs whose verdict step did not moderate. Never raises."""
    from app.services.media.llm import complete, extract_json  # worker-side import

    try:
        messages = build_moderation_messages(
            topic=str(conf.get("topic") or ""),
            description=conf.get("description"),
            verdict_text=verdict_text,
        )
        text, usage = complete(
            model,
            messages,
            purpose="moderation",
            api_key=api_key,
            max_tokens=MODERATION_MAX_TOKENS,
        )
        parsed = parse_moderation(extract_json(text))
        if parsed is None:
            return fallback_result(), usage or {}
        return {**parsed, "source": "llm"}, usage or {}
    except Exception as e:
        logger.warning("Moderation check failed, sending to review: %s", e)
        return fallback_result(), {}


def apply_check(debate: Debate, result: dict[str, Any]) -> None:
    """Store an automatic result. Admin decisions are never overwritten."""
    current = debate.moderation_json or {}
    if current.get("source") == "admin":
        return
    debate.moderation_status = "flagged" if result.get("flagged") else "approved"
    debate.moderation_json = {
        **current,
        "reason": str(result.get("reason") or ""),
        "source": str(result.get("source") or "llm"),
        "checked_at": _now(),
    }


def mark_admin_decision(debate: Debate, *, approved: bool) -> None:
    debate.moderation_status = "approved" if approved else "rejected"
    debate.moderation_json = {
        **(debate.moderation_json or {}),
        "source": "admin",
        "checked_at": _now(),
    }
    if not approved:
        debate.is_public = False


def wants_public(debate: Debate) -> bool:
    """The owner asked for the gallery: in the wizard (auto_publish) or by clicking Publish
    while the debate waited for review. Configs from before auto-publishing count as no."""
    conf = debate.config_json or {}
    return bool(conf.get("auto_publish", False)) or bool(
        (debate.moderation_json or {}).get("publish_requested")
    )


def publish_sync(db: Session, debate: Debate) -> bool:
    """Give the debate a slug and make it public (worker side). False if no slug was free."""
    if not debate.slug:
        for _ in range(5):
            candidate = new_slug()
            if db.scalar(select(Debate.id).where(Debate.slug == candidate)) is None:
                debate.slug = candidate
                break
        if not debate.slug:
            return False
    debate.is_public = True
    debate.published_at = debate.published_at or utcnow()
    return True


async def publish_async(db: AsyncSession, debate: Debate) -> bool:
    """API-side twin of publish_sync (does not commit)."""
    if not debate.slug:
        for _ in range(5):
            candidate = new_slug()
            if await db.scalar(select(Debate.id).where(Debate.slug == candidate)) is None:
                debate.slug = candidate
                break
        if not debate.slug:
            return False
    debate.is_public = True
    debate.published_at = debate.published_at or utcnow()
    return True


def clean_run(debate: Debate) -> bool:
    """Every turn produced text and the judge gave a verdict (rate limits and provider errors
    leave failed turns behind; such debates are not worth showing in the gallery)."""
    turns = list(debate.turns)
    has_verdict = any(t.turn_type == "verdict" and (t.text or "").strip() for t in turns)
    return has_verdict and not any(t.error for t in turns)


def should_auto_publish(debate: Debate) -> bool:
    """A completed, approved, clean debate whose owner wants it public."""
    return (
        debate.status == "completed"
        and not debate.is_public
        and debate.moderation_status == "approved"
        and wants_public(debate)
        and clean_run(debate)
    )
