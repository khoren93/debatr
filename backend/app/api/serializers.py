"""Build API response models from ORM rows (shared by the debates and gallery routes)."""

from collections.abc import Sequence
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

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
    MotionOut,
    MotionRef,
    MotionVersion,
    NewsContext,
    ParticipantOut,
    RemixParentOut,
    RoundScoreOut,
    TurnOut,
    TurnUsage,
    VerdictFeedback,
    VerdictOut,
)
from app.services import motions
from app.services.formats import SIDES, Format, format_of
from app.services.free_router import is_free_router
from app.services.media.languages import language_code
from app.services.motions import MotionInfo
from app.services.scheduler import speaker_role_for
from app.services.studio import turn_visuals_out
from app.services.verdict import stored_round_scores


def is_owner(debate: Debate, viewer: User | None) -> bool:
    return viewer is not None and debate.user_id == viewer.id


def can_view(debate: Debate, viewer: User | None) -> bool:
    """Owners, and anyone for public or legacy (ownerless) debates. Admins read the others in
    the admin console, never through this API."""
    return debate.is_public or debate.user_id is None or is_owner(debate, viewer)


def can_manage(debate: Debate, viewer: User | None) -> bool:
    return is_owner(debate, viewer)


def share_url(debate: Debate) -> str | None:
    if not debate.slug or not debate.is_public:
        return None
    return f"{settings.SITE_URL.rstrip('/')}/d/{debate.slug}"


def totals_out(debate: Debate) -> DebateTotals:
    return DebateTotals.model_validate(debate.totals_json or {})


def turn_out(turn: Turn, fmt: Format) -> TurnOut:
    return TurnOut(
        seq_index=turn.seq_index,
        round_id=turn.round_id,
        round_label=fmt.round_label(turn.round_id, turn.turn_type),
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
        rounds=[RoundScoreOut.model_validate(r) for r in stored_round_scores(raw)],
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


def has_premium_voices(debate: Debate) -> bool:
    """The ready audio was voiced by ElevenLabs (system or own key). `routes_gallery.
    premium_voices_sql` is its SQL twin."""
    options = (debate.media_json or {}).get("options") or {}
    return debate.media_status == "ready" and options.get("provider") == "elevenlabs"


def outputs(debate: Debate) -> list[str]:
    """Deliverables that exist for this debate. Video and shorts are rendered in the browser
    from the timeline, so they become available as soon as the audio build is ready."""
    if debate.media_status != "ready":
        return []
    plan = media_plan_out(debate)
    wanted = set(plan.outputs) if plan else {"audio", "video", "short"}
    return [o for o in ("audio", "video", "short") if o in wanted]


def participants_out(debate: Debate) -> list[ParticipantOut]:
    configured: list[dict[str, Any]] = (debate.config_json or {}).get("participants") or []
    return [
        ParticipantOut(
            id=f"participant_{i}",  # rows are inserted in config order
            name=p.persona_name,
            role=p.role,
            model=p.model_id,
            router=router_of(configured[i] if i < len(configured) else {}, p.model_id),
            voice_name=p.voice_name,
            avatar=p.avatar_url,
            side=side_of(configured[i] if i < len(configured) else {}),
        )
        for i, p in enumerate(debate.participants)
    ]


def side_of(configured: dict[str, Any]) -> Any:
    """A debater's side as configured (None: not set, the persona carried the stance)."""
    side = configured.get("side")
    return side if configured.get("role") == "debater" and side in SIDES else None


def router_of(configured: dict[str, Any], model_id: str) -> str | None:
    """The router that picked `model_id` for a participant configured with it (Free Router)."""
    requested = str(configured.get("model_id") or "")
    return requested if is_free_router(requested) and model_id != requested else None


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
        return DebateConfig.stored(stored)
    except ValueError:
        return None


def moderation_out(debate: Debate) -> ModerationOut:
    raw: dict[str, Any] = debate.moderation_json or {}
    return ModerationOut(
        status=debate.moderation_status or "none",
        reason=raw.get("reason") or None,
        publish_requested=bool(raw.get("publish_requested")),
    )


def news_out(conf: dict[str, Any]) -> NewsContext | None:
    raw = conf.get("news")
    if not isinstance(raw, dict) or not raw.get("brief"):
        return None
    try:
        return NewsContext.model_validate(raw)
    except ValueError:
        return None


def detail_out(
    debate: Debate,
    viewer: User | None,
    engagement: EngagementOut | None = None,
    *,
    manager: bool = False,
    motion: MotionOut | None = None,
    remix_of: RemixParentOut | None = None,
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
            format=format_of(conf).id,
            topic=conf.get("topic", ""),
            description=conf.get("description"),
            language=conf.get("language", "English"),
            language_code=language_code(conf.get("language")),
            num_rounds=int(conf.get("num_rounds") or 1),
            length_preset=conf.get("length_preset", "medium"),
            intensity=int(conf.get("intensity") or 5),
            output_style=conf.get("output_style") or "markdown",
            news=news_out(conf),
        ),
        totals=totals_out(debate),
        participants=participants_out(debate),
        turns=[turn_out(t, format_of(conf)) for t in debate.turns],
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
        motion=motion,
        remix_of=remix_of,
    )


def motion_ref_out(info: MotionInfo | None) -> MotionRef | None:
    if info is None:
        return None
    return MotionRef(slug=info.slug, title=info.title, versions=info.versions, models=info.models)


def motion_version_out(debate: Debate, current: Debate | None = None) -> MotionVersion:
    conf: dict[str, Any] = debate.config_json or {}
    return MotionVersion(
        id=str(debate.id),
        slug=debate.slug or "",
        topic=topic_of(debate),
        language=str(conf.get("language") or "English"),
        language_code=language_code(conf.get("language")),
        author_name=debate.user.display_name if debate.user is not None else None,
        participants=participants_out(debate),
        likes=debate.likes_count or 0,
        views=debate.views or 0,
        duration_ms=duration_ms(debate),
        premium_voices=has_premium_voices(debate),
        published_at=debate.published_at,
        current=current is not None and debate.id == current.id,
    )


def motion_out(
    info: MotionInfo | None, versions: Sequence[Debate], current: Debate
) -> MotionOut | None:
    """The version strip of a debate page: null while the topic has no public version."""
    if info is None or not versions:
        return None
    return MotionOut(
        slug=info.slug,
        title=info.title,
        versions=info.versions,
        items=[motion_version_out(v, current) for v in versions],
    )


def remix_parent_out(parent: Debate | None) -> RemixParentOut | None:
    """Only a public parent is named: a private one stays private even to its remixers."""
    if parent is None or not parent.is_public or not parent.slug:
        return None
    return RemixParentOut(slug=parent.slug, topic=topic_of(parent))


async def topic_context(
    db: AsyncSession, debate: Debate
) -> tuple[MotionOut | None, RemixParentOut | None]:
    """The debate page's topic block: its public versions and the public debate it remixes."""
    motion: MotionOut | None = None
    if debate.motion_id is not None:
        info = (await motions.motion_infos(db, [debate.motion_id])).get(debate.motion_id)
        if info is not None:
            versions = list(
                await motions.public_versions(db, debate.motion_id, limit=motions.VERSIONS_SHOWN)
            )
            # The debate being viewed is always in its own strip, even past the first dozen.
            if debate.is_public and debate.slug and all(v.id != debate.id for v in versions):
                versions = [*versions[: motions.VERSIONS_SHOWN - 1], debate]
            motion = motion_out(info, versions, debate)
    parent = await db.get(Debate, debate.remix_of_id) if debate.remix_of_id else None
    return motion, remix_parent_out(parent)


def gallery_item_out(debate: Debate, motion: MotionInfo | None = None) -> GalleryItem:
    conf: dict[str, Any] = debate.config_json or {}
    return GalleryItem(
        id=str(debate.id),
        slug=debate.slug or "",
        format=format_of(conf).id,
        title=debate.title,
        topic=topic_of(debate),
        language=str(conf.get("language") or "English"),
        language_code=language_code(conf.get("language")),
        category=debate.category,
        author_name=debate.user.display_name if debate.user is not None else None,
        views=debate.views or 0,
        likes=debate.likes_count or 0,
        votes=debate.votes_count or 0,
        duration_ms=duration_ms(debate),
        has_media=debate.media_status == "ready",
        premium_voices=has_premium_voices(debate),
        verdict=verdict_out(debate),
        participants=participants_out(debate),
        published_at=debate.published_at,
        motion=motion_ref_out(motion),
    )
