from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.visuals import Scene, SceneCheck

LengthPreset = Literal["very_short", "short", "medium", "long"]
ParticipantRole = Literal["moderator", "debater"]
# "spoken" asks the models for plain spoken prose (no Markdown) suited for TTS and video.
OutputStyle = Literal["markdown", "spoken"]
DebateStatus = Literal["draft", "queued", "running", "completed", "error", "stopped"]
MediaOutput = Literal["audio", "video", "short"]
VideoQuality = Literal["720p", "1080p", "4k"]
TTSProvider = Literal["elevenlabs", "edge"]
# Pictures in the visual scenes: none, free photos (Wikimedia Commons) or AI images (paid).
ImageSource = Literal["off", "stock", "ai"]

GALLERY_CATEGORIES: tuple[str, ...] = ("tech", "society", "science", "culture", "money", "fun")
GallerySort = Literal["new", "trending", "top"]
GalleryPeriod = Literal["week", "month", "year", "all"]

# Request-only fields that must never be written to `debates.config_json`.
TRANSIENT_CONFIG_FIELDS: frozenset[str] = frozenset({"user_provider_key", "user_tts_key", "draft"})


# --- Preset Schemas ---
class Preset(BaseModel):
    id: str
    name: str
    description: str | None = None
    preset_json: dict[str, Any]
    model_config = ConfigDict(from_attributes=True)


# --- Model Schemas ---
class ModelPricing(BaseModel):
    prompt: str
    completion: str


class ModelInfo(BaseModel):
    id: str
    name: str
    context_length: int
    pricing: ModelPricing
    is_free: bool
    description: str = ""
    created: int = 0  # unix seconds the model was added to OpenRouter


class ModelsResponse(BaseModel):
    data: list[ModelInfo]
    timestamp: float


class CreditsResponse(BaseModel):
    credits: float | None = None
    error: str | None = None


class ValidateModelsRequest(BaseModel):
    model_ids: list[str] = Field(min_length=1, max_length=10)
    api_key: str | None = None


class ValidationResult(BaseModel):
    model_id: str
    status: Literal["ok", "error"]
    error: str | None = None


class ValidateModelsResponse(BaseModel):
    results: list[ValidationResult]


# --- Debate Creation Schemas ---
class ParticipantConfig(BaseModel):
    role: ParticipantRole
    model_id: str = Field(min_length=1, max_length=200)
    display_name: str = Field(min_length=1, max_length=100)
    avatar_url: str | None = Field(default=None, max_length=500)
    voice_name: str | None = Field(default=None, max_length=200)
    persona_preset: str | None = None
    persona_custom: str | None = Field(default=None, max_length=4000)


class MediaPlan(BaseModel):
    """What to produce automatically once the debate finishes (chosen in the wizard)."""

    provider: TTSProvider = "edge"
    model_id: str = Field(default="eleven_v3", max_length=100)
    voices: dict[str, str] = Field(default_factory=dict)  # speaker id -> provider voice id
    outputs: list[MediaOutput] = Field(default_factory=lambda: ["audio", "video", "short"])
    quality: VideoQuality = "1080p"
    visuals: bool = True  # charts / drawn scenes, live next to the text and in the video
    images: ImageSource = "off"  # pictures among the scenes


class DebateConfig(BaseModel):
    topic: str = Field(min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=4000)
    language: str = Field(default="English", max_length=50)
    participants: list[ParticipantConfig] = Field(min_length=1, max_length=8)
    debate_preset_id: str | None = "custom"
    length_preset: LengthPreset = "medium"
    num_rounds: int = Field(default=3, ge=1, le=10)
    intensity: int = Field(default=5, ge=1, le=10)
    output_style: OutputStyle = "markdown"
    media_plan: MediaPlan | None = None
    # Publish to the gallery once finished and approved by the AI check (services/moderation).
    auto_publish: bool = True
    # Web fact-check of the figures and quotes shown in the visual scenes (services/factcheck),
    # billed like the debate. Needs media_plan.visuals.
    fact_check: bool = False
    # Save without starting (status=draft). Request-only.
    draft: bool = False
    # Optional BYOK OpenRouter key. Never persisted to the database.
    user_provider_key: str | None = Field(default=None, max_length=300)
    # Optional BYOK ElevenLabs key for the automatic audio build. Never persisted either.
    user_tts_key: str | None = Field(default=None, max_length=200)

    @field_validator("participants")
    @classmethod
    def _validate_participants(cls, value: list[ParticipantConfig]) -> list[ParticipantConfig]:
        debaters = [p for p in value if p.role == "debater"]
        moderators = [p for p in value if p.role == "moderator"]
        if not debaters:
            raise ValueError("At least one debater is required")
        if len(moderators) > 1:
            raise ValueError("At most one moderator is allowed")
        return value

    def persisted(self) -> dict[str, Any]:
        """The part of the config that is stored on the debate row."""
        return self.model_dump(exclude=set(TRANSIENT_CONFIG_FIELDS))


class StartDebateRequest(BaseModel):
    user_provider_key: str | None = Field(default=None, max_length=300)
    user_tts_key: str | None = Field(default=None, max_length=200)


class DebateResponse(BaseModel):
    debate_id: str
    status: str
    message: str


class EstimateOut(BaseModel):
    turns: int
    words: int
    tokens_in: int
    tokens_out: int
    llm_cost_usd: float
    tts_chars: int
    tts_cost_usd: float
    factcheck_cost_usd: float = 0.0
    images_cost_usd: float = 0.0
    credits_cost_usd: float
    duration_ms: int
    render_ms: int
    own_key: bool = False
    own_tts_key: bool = False
    paid_models: list[str] = Field(default_factory=list)
    credits_before: float | None = None
    credits_after: float | None = None
    sufficient: bool = True


class PublishRequest(BaseModel):
    category: str | None = None

    @field_validator("category")
    @classmethod
    def _category(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        value = value.strip().lower()
        if value not in GALLERY_CATEGORIES:
            raise ValueError(f"Category must be one of: {', '.join(GALLERY_CATEGORIES)}")
        return value


class PublishOut(BaseModel):
    is_public: bool
    slug: str | None
    share_url: str | None
    # "flagged" when the debate waits for an admin review instead of going public.
    moderation_status: str = "none"


class ModerationOut(BaseModel):
    """Gallery check, shown to the owner only."""

    # none | approved | flagged | rejected
    status: str = "none"
    reason: str | None = None
    publish_requested: bool = False


class RenderReport(BaseModel):
    kind: Literal["long", "short"]


class RendersOut(BaseModel):
    renders: dict[str, int]


# --- Debate Read Schemas ---
class TurnUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost: float = 0.0


class DebateTotals(BaseModel):
    tokens_in: int = 0
    tokens_out: int = 0
    cost: float = 0.0
    turns_count: int = 0


class TurnSceneOut(BaseModel):
    key: str
    scene: Scene
    checkable: bool = False  # sent to the fact-checker (the result may still be pending)
    check: SceneCheck | None = None


class TurnDisputeOut(BaseModel):
    key: str  # the challenged scene (of an earlier turn)
    reason: str = ""


class TurnVisualsOut(BaseModel):
    """Live scenes of a turn (services/studio)."""

    # designing | checking (sketches / fact-checks running) | ready | error | none
    status: str = "none"
    scenes: list[TurnSceneOut] = Field(default_factory=list)
    disputes: list[TurnDisputeOut] = Field(default_factory=list)  # made by this turn


class TurnOut(BaseModel):
    seq_index: int
    round_id: str
    turn_type: str
    speaker_role: ParticipantRole
    speaker_id: str = ""  # "participant_{i}" (index into config participants) or "judge"
    speaker_name: str
    text: str
    error: str | None = None
    model_used: str
    usage: TurnUsage = Field(default_factory=TurnUsage)
    created_at: datetime | None = None
    visuals: TurnVisualsOut | None = None


class ParticipantOut(BaseModel):
    id: str = ""  # "participant_{i}", matches Turn.speaker_id
    name: str | None
    role: str
    model: str
    voice_name: str | None = None
    avatar: str | None = None


class VerdictFeedback(BaseModel):
    speaker_id: str
    name: str
    text: str


class VerdictOut(BaseModel):
    winner_id: str | None = None
    winner_name: str | None = None
    is_draw: bool = True
    headline: str = ""
    feedback: list[VerdictFeedback] = Field(default_factory=list)


class BillingOut(BaseModel):
    own_key: bool = False


class DebateSummary(BaseModel):
    id: str
    title: str | None
    topic: str = ""
    status: str
    media_status: str = "none"
    created_at: datetime
    ended_at: datetime | None = None
    totals: DebateTotals = Field(default_factory=DebateTotals)
    is_public: bool = False
    slug: str | None = None
    moderation_status: str = "none"
    category: str | None = None
    views: int = 0
    likes: int = 0
    votes: int = 0
    duration_ms: int | None = None
    outputs: list[str] = Field(default_factory=list)
    verdict: VerdictOut | None = None
    participants: list[ParticipantOut] = Field(default_factory=list)


class DebateSettingsOut(BaseModel):
    topic: str
    description: str | None = None
    language: str
    language_code: str = "en"
    num_rounds: int
    length_preset: str
    intensity: int
    output_style: OutputStyle = "markdown"


class AudienceOut(BaseModel):
    """Audience vote ("who argued better?") on a public debate."""

    total: int = 0
    counts: dict[str, int] = Field(default_factory=dict)  # participant_id -> votes
    my_vote: str | None = None
    can_vote: bool = False
    # Why the viewer cannot vote: sign_in | owner | not_public | not_finished
    reason: str | None = None


class EngagementOut(BaseModel):
    likes: int = 0
    liked: bool = False
    can_like: bool = False
    audience: AudienceOut = Field(default_factory=AudienceOut)


class LikeOut(BaseModel):
    liked: bool
    likes: int


class VoteRequest(BaseModel):
    participant_id: str = Field(min_length=1, max_length=32)


class DebateDetail(BaseModel):
    id: str
    status: str
    media_status: str = "none"
    title: str | None
    error_message: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    ended_at: datetime | None = None
    settings: DebateSettingsOut
    totals: DebateTotals = Field(default_factory=DebateTotals)
    participants: list[ParticipantOut]
    turns: list[TurnOut]
    user_id: str | None = None
    author_name: str | None = None
    is_owner: bool = False
    is_public: bool = False
    slug: str | None = None
    share_url: str | None = None
    category: str | None = None
    views: int = 0
    published_at: datetime | None = None
    verdict: VerdictOut | None = None
    media_plan: MediaPlan | None = None
    duration_ms: int | None = None
    outputs: list[str] = Field(default_factory=list)
    billing: BillingOut = Field(default_factory=BillingOut)
    engagement: EngagementOut = Field(default_factory=EngagementOut)
    # Full stored configuration; only sent to the owner (drafts re-open in the wizard).
    config: DebateConfig | None = None
    # Gallery check; only sent to the owner and the admin.
    moderation: ModerationOut | None = None


class StopDebateResponse(BaseModel):
    debate_id: str
    status: str


# --- Gallery ---
class GalleryItem(BaseModel):
    id: str
    slug: str
    title: str | None
    topic: str
    language: str
    category: str | None = None
    author_name: str | None = None
    views: int = 0
    likes: int = 0
    votes: int = 0
    duration_ms: int | None = None
    has_media: bool = False
    verdict: VerdictOut | None = None
    participants: list[ParticipantOut] = Field(default_factory=list)
    published_at: datetime | None = None


class GalleryResponse(BaseModel):
    items: list[GalleryItem]
    total: int
    categories: list[str] = Field(default_factory=lambda: list(GALLERY_CATEGORIES))


# --- Model leaderboard ---
class LeaderboardEntry(BaseModel):
    model_id: str
    name: str
    is_free: bool
    rating: int
    debates: int  # public debates the model argued in
    votes: int  # audience votes received
    vote_share: float | None = None  # votes / all votes cast in its debates
    audience_wins: int = 0
    audience_contests: int = 0
    judge_wins: int = 0
    judge_contests: int = 0
    # Web fact-checks of the model's on-screen figures and quotes.
    claims_checked: int = 0
    claims_verified: int = 0
    claims_disputed: int = 0


class LeaderboardOut(BaseModel):
    entries: list[LeaderboardEntry]
    total_debates: int
    total_votes: int
