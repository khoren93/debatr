"""Build API response models from ORM rows (shared by the debates and gallery routes)."""

from typing import Any

from fastapi import Request

from app.core.auth import is_admin_session
from app.core.config import settings
from app.models.models import Debate, Turn, User
from app.schemas.schemas import (
    BillingOut,
    DebateConfig,
    DebateDetail,
    DebateSettingsOut,
    DebateSummary,
    DebateTotals,
    EngagementOut,
    GalleryItem,
    MediaPlan,
    ModerationOut,
    ParticipantOut,
    TurnOut,
    TurnUsage,
    VerdictFeedback,
    VerdictOut,
)
from app.services.media.languages import language_code
from app.services.scheduler import speaker_role_for
from app.services.studio import turn_visuals_out


def is_owner(debate: Debate, viewer: User | None) -> bool:
    return viewer is not None and debate.user_id == viewer.id


def can_view(debate: Debate, viewer: User | None, request: Request | None = None) -> bool:
    """Owners, admins and anyone for public or legacy (ownerless) debates."""
    if debate.is_public or debate.user_id is None or is_owner(debate, viewer):
        return True
    return request is not None and is_admin_session(request)


def can_manage(debate: Debate, viewer: User | None, request: Request | None = None) -> bool:
    if is_owner(debate, viewer):
        return True
    return request is not None and is_admin_session(request)


def share_url(debate: Debate) -> str | None:
    if not debate.slug or not debate.is_public:
        return None
    return f"{settings.SITE_URL.rstrip('/')}/d/{debate.slug}"


def totals_out(debate: Debate) -> DebateTotals:
    return DebateTotals.model_validate(debate.totals_json or {})


def turn_out(turn: Turn) -> TurnOut:
    return TurnOut(
        seq_index=turn.seq_index,
        round_id=turn.round_id,
        turn_type=turn.turn_type,
        speaker_role=speaker_role_for(turn.turn_type),  # type: ignore[arg-type]
        speaker_id=turn.speaker_id,
        speaker_name=turn.speaker_name,
        text=turn.text,
        error=turn.error,
        model_used=turn.model_used,
        usage=TurnUsage.model_validate(turn.usage_json or {}),
        created_at=turn.created_at,
        visuals=turn_visuals_out(turn),
    )


def verdict_out(debate: Debate) -> VerdictOut | None:
    raw: dict[str, Any] = debate.verdict_json or {}
    if not raw:
        return None
    feedback = [
        VerdictFeedback(
            speaker_id=str(f.get("speaker_id") or ""),
            name=str(f.get("name") or ""),
            text=str(f.get("text") or ""),
        )
        for f in raw.get("feedback") or []
        if isinstance(f, dict) and f.get("text")
    ]
    winner_id = raw.get("winner_id")
    return VerdictOut(
        winner_id=winner_id,
        winner_name=raw.get("winner_name"),
        is_draw=bool(raw.get("is_draw", winner_id is None)),
        headline=str(raw.get("headline") or ""),
        feedback=feedback,
    )


def media_plan_out(debate: Debate) -> MediaPlan | None:
    raw = (debate.config_json or {}).get("media_plan")
    if not raw:
        return None
    try:
        return MediaPlan.model_validate(raw)
    except ValueError:
        return None


def duration_ms(debate: Debate) -> int | None:
    if debate.media_status != "ready":
        return None
    stats = (debate.media_json or {}).get("stats") or {}
    value = stats.get("total_ms")
    return int(value) if value else None


def outputs(debate: Debate) -> list[str]:
    """Deliverables that exist for this debate. Video and shorts are rendered in the browser
    from the timeline, so they become available as soon as the audio build is ready."""
    if debate.media_status != "ready":
        return []
    plan = media_plan_out(debate)
    wanted = set(plan.outputs) if plan else {"audio", "video", "short"}
    return [o for o in ("audio", "video", "short") if o in wanted]


def participants_out(debate: Debate) -> list[ParticipantOut]:
    return [
        ParticipantOut(
            id=f"participant_{i}",  # rows are inserted in config order
            name=p.persona_name,
            role=p.role,
            model=p.model_id,
            voice_name=p.voice_name,
            avatar=p.avatar_url,
        )
        for i, p in enumerate(debate.participants)
    ]


def debater_models(debate: Debate) -> dict[str, str]:
    """participant_id -> model id for the debaters (the ids audience votes refer to)."""
    return {
        f"participant_{i}": p.model_id
        for i, p in enumerate(debate.participants)
        if p.role != "moderator"
    }


def topic_of(debate: Debate) -> str:
    return str((debate.config_json or {}).get("topic") or debate.title or "")


def summary_out(debate: Debate) -> DebateSummary:
    return DebateSummary(
        id=str(debate.id),
        title=debate.title,
        topic=topic_of(debate),
        status=debate.status,
        media_status=debate.media_status or "none",
        created_at=debate.created_at,
        ended_at=debate.ended_at,
        totals=totals_out(debate),
        is_public=debate.is_public,
        slug=debate.slug,
        moderation_status=debate.moderation_status or "none",
        category=debate.category,
        views=debate.views or 0,
        likes=debate.likes_count or 0,
        votes=debate.votes_count or 0,
        duration_ms=duration_ms(debate),
        outputs=outputs(debate),
        verdict=verdict_out(debate),
        participants=participants_out(debate),
    )


def owner_config(debate: Debate) -> DebateConfig | None:
    """The stored configuration, so owners can re-open a draft in the wizard."""
    stored = dict(debate.config_json or {})
    stored.pop("billing", None)
    try:
        return DebateConfig.model_validate(stored)
    except ValueError:
        return None


def moderation_out(debate: Debate) -> ModerationOut:
    raw: dict[str, Any] = debate.moderation_json or {}
    return ModerationOut(
        status=debate.moderation_status or "none",
        reason=raw.get("reason") or None,
        publish_requested=bool(raw.get("publish_requested")),
    )


def detail_out(
    debate: Debate,
    viewer: User | None,
    engagement: EngagementOut | None = None,
    *,
    manager: bool = False,
) -> DebateDetail:
    conf: dict[str, Any] = debate.config_json or {}
    billing = conf.get("billing") or {}
    author = debate.user.display_name if debate.user is not None else None
    owner = is_owner(debate, viewer)
    return DebateDetail(
        id=str(debate.id),
        status=debate.status,
        media_status=debate.media_status or "none",
        title=debate.title,
        error_message=debate.error_message,
        created_at=debate.created_at,
        started_at=debate.started_at,
        ended_at=debate.ended_at,
        settings=DebateSettingsOut(
            topic=conf.get("topic", ""),
            description=conf.get("description"),
            language=conf.get("language", "English"),
            language_code=language_code(conf.get("language")),
            num_rounds=int(conf.get("num_rounds") or 1),
            length_preset=conf.get("length_preset", "medium"),
            intensity=int(conf.get("intensity") or 5),
            output_style=conf.get("output_style") or "markdown",
        ),
        totals=totals_out(debate),
        participants=participants_out(debate),
        turns=[turn_out(t) for t in debate.turns],
        user_id=str(debate.user_id) if debate.user_id else None,
        author_name=author,
        is_owner=owner,
        config=owner_config(debate) if owner else None,
        moderation=moderation_out(debate) if owner or manager else None,
        is_public=debate.is_public,
        slug=debate.slug,
        share_url=share_url(debate),
        category=debate.category,
        views=debate.views or 0,
        published_at=debate.published_at,
        verdict=verdict_out(debate),
        media_plan=media_plan_out(debate),
        duration_ms=duration_ms(debate),
        outputs=outputs(debate),
        billing=BillingOut(own_key=bool(billing.get("own_key"))),
        engagement=engagement or EngagementOut(likes=debate.likes_count or 0),
    )


def gallery_item_out(debate: Debate) -> GalleryItem:
    conf: dict[str, Any] = debate.config_json or {}
    return GalleryItem(
        id=str(debate.id),
        slug=debate.slug or "",
        title=debate.title,
        topic=topic_of(debate),
        language=str(conf.get("language") or "English"),
        category=debate.category,
        author_name=debate.user.display_name if debate.user is not None else None,
        views=debate.views or 0,
        likes=debate.likes_count or 0,
        votes=debate.votes_count or 0,
        duration_ms=duration_ms(debate),
        has_media=debate.media_status == "ready",
        verdict=verdict_out(debate),
        participants=participants_out(debate),
        published_at=debate.published_at,
    )
