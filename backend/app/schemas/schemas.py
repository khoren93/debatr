from datetime import datetime
from typing import Any, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

from app.schemas.visuals import Scene, SceneCheck

# The site calls them short / medium / long; "long" (~500 words) is only in configs saved before
# it was retired (`DebateConfig` runs a new one as medium).
LengthPreset = Literal["very_short", "short", "medium", "long"]
ParticipantRole = Literal["moderator", "debater"]
# Show formats (services/formats); a new one is added to this list and to the registry.
FormatId = Literal["debate", "rap_battle"]
# A debater's side; unset = the persona text carries the stance (configs from before sides).
DebaterSide = Literal["for", "against", "own"]
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
# none: one card per debate (the CLI); motion: one card per topic, its best version on the cover.
GalleryGroup = Literal["none", "motion"]
GalleryPeriod = Literal["week", "month", "year", "all"]

# Request-only fields that must never be written to `debates.config_json`.
TRANSIENT_CONFIG_FIELDS: frozenset[str] = frozenset(
    {"user_provider_key", "user_tts_key", "draft", "remix_of"}
)


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
    side: DebaterSide | None = None  # debaters only; formats with fixed seats set it themselves


class MediaPlan(BaseModel):
    """What to produce automatically once the debate finishes (chosen in the wizard)."""

    provider: TTSProvider = "edge"
    model_id: str = Field(default="eleven_v4", max_length=100)
    voices: dict[str, str] = Field(default_factory=dict)  # speaker id -> provider voice id
    outputs: list[MediaOutput] = Field(default_factory=lambda: ["audio", "video", "short"])
    quality: VideoQuality = "1080p"
    visuals: bool = True  # charts / drawn scenes, live next to the text and in the video
    images: ImageSource = "off"  # pictures among the scenes
    # Rap battles: speaker id -> flow preset (media/music.FLOWS), in place of a rapper's voice.
    flows: dict[str, str] = Field(default_factory=dict, max_length=8)
    # Crowd / studio reactions in the video; None: the format's default (Format.crowd_sounds).
    sfx: bool | None = None


class NewsContext(BaseModel):
    """The news story behind a trending topic (wizard: "Ground in the … article"). The models
    do not know recent news, so its brief goes into every prompt."""

    brief: str = Field(min_length=1, max_length=2000)
    outlet: str = Field(default="", max_length=100)
    title: str = Field(default="", max_length=300)
    url: str = Field(default="", max_length=1000)
    # ISO timestamp as sent by the trending API (kept as text: config_json is plain JSON).
    published_at: str | None = Field(default=None, max_length=40)

    @field_validator("url")
    @classmethod
    def _http_url(cls, value: str) -> str:
        value = value.strip()
        if value and not value.lower().startswith(("http://", "https://")):
            raise ValueError("The source link must be an http(s) URL")
        return value


# The topic is drawn on the video (the intro poster, the stage between scenes, the Short), where
# up to 150 characters fit in three lines. Configs saved before this limit may hold up to 500:
# `DebateConfig.stored` still loads them (drafts, resume, the wizard's remix).
TOPIC_MAX_LENGTH = 150
STORED_TOPIC_MAX_LENGTH = 500


class DebateConfig(BaseModel):
    format: FormatId = "debate"
    topic: str = Field(
        min_length=1,
        max_length=STORED_TOPIC_MAX_LENGTH,
        json_schema_extra={"maxLength": TOPIC_MAX_LENGTH},
    )
    description: str | None = Field(default=None, max_length=4000)
    # The news story the topic came from (trending topics), when the user grounds the debate in it.
    news: NewsContext | None = None
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
    # An AI cover once the debate completes (services/media/cover.py): unset follows the rule
    # (runs paid from the balance or an own key; API tokens only when they send it), false never.
    cover: bool | None = None
    # Save without starting (status=draft). Request-only.
    draft: bool = False
    # Optional BYOK OpenRouter key. Never persisted to the database.
    user_provider_key: str | None = Field(default=None, max_length=300)
    # Optional BYOK ElevenLabs key for the automatic audio build. Never persisted either.
    user_tts_key: str | None = Field(default=None, max_length=200)
    # Id of the debate this one is a remix of (`debates.remix_of_id`, services/motions). Request-
    # only; ignored when the user may not see that debate.
    remix_of: str | None = Field(default=None, max_length=64)

    @field_validator("topic")
    @classmethod
    def _topic_fits_the_video(cls, value: str, info: ValidationInfo) -> str:
        if len(value) > TOPIC_MAX_LENGTH and not (info.context or {}).get("stored"):
            raise ValueError(f"The topic must be at most {TOPIC_MAX_LENGTH} characters")
        return value

    @field_validator("length_preset")
    @classmethod
    def _retired_length(cls, value: LengthPreset, info: ValidationInfo) -> LengthPreset:
        """ "long" (~500 words a turn) was retired: nobody watches that long. Old clients that
        still send it get the longest preset left; saved configs keep theirs."""
        if value == "long" and not (info.context or {}).get("stored"):
            return "medium"
        return value

    @classmethod
    def stored(cls, data: dict[str, Any]) -> Self:
        """A configuration saved earlier, checked by the rules of its time (longer topics)."""
        return cls.model_validate(data, context={"stored": True})

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

    @model_validator(mode="after")
    def _fits_the_format(self) -> Self:
        from app.services.formats import format_of  # the registry imports no schemas

        fmt = format_of({"format": self.format})
        problems = fmt.problems(
            self.model_dump(include={"participants", "num_rounds", "media_plan"})
        )
        if problems:
            raise ValueError("; ".join(problems))
        # What the format decides for itself: the style its texts are written in, no scenes.
        if fmt.output_style is not None:
            self.output_style = fmt.output_style
        if not fmt.visuals:
            self.fact_check = False
            if self.media_plan is not None:
                self.media_plan = self.media_plan.model_copy(
                    update={"visuals": False, "images": "off"}
                )
        return self

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


class FreeRunsOut(BaseModel):
    per_day: int
    used: int
    left: int
    next_at: datetime | None = None  # when a run leaves the 24-hour window, once none is left


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
    music_ms: int = 0  # a rap battle's generated track
    music_cost_usd: float = 0.0  # in credits, like tts_cost_usd
    # The run gets an AI cover when it completes, and what it adds to `credits_cost_usd` (0 on
    # an own OpenRouter key, which pays OpenRouter itself).
    cover: bool = False
    cover_cost_usd: float = 0.0
    own_key: bool = False
    own_tts_key: bool = False
    paid_models: list[str] = Field(default_factory=list)
    credits_before: float | None = None
    credits_after: float | None = None
    # What the API token making the request may still spend (null: browser or no limit).
    token_budget_usd: float | None = None
    sufficient: bool = True
    # A free debate (system key, free models, no balance; services/free_limits): the day's
    # allowance, and why it would be refused (too big, or none left today), else null.
    free_runs: FreeRunsOut | None = None
    free_limit: str | None = None


class ResumeEstimateOut(EstimateOut):
    """What resuming a failed debate costs: only the turns from `from_turn` (0-based) on."""

    from_turn: int


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
    path: str | None = None  # canonical path of the public page
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
    round_label: str = ""  # the format's name for this part of the show ("Round 2", "Verdict")
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
    # Set when a router picked `model` (Free Router: the model of the first answer is kept).
    router: str | None = None
    voice_name: str | None = None
    avatar: str | None = None
    side: DebaterSide | None = None


class VerdictFeedback(BaseModel):
    speaker_id: str
    name: str
    text: str


class RoundScoreOut(BaseModel):
    round: int
    scores: dict[str, int]  # participant id -> the judge's score


class VerdictOut(BaseModel):
    winner_id: str | None = None
    winner_name: str | None = None
    is_draw: bool = True
    headline: str = ""
    feedback: list[VerdictFeedback] = Field(default_factory=list)
    # Formats whose judge scores every round (rap battle); empty otherwise.
    rounds: list[RoundScoreOut] = Field(default_factory=list)


class BillingOut(BaseModel):
    own_key: bool = False


CoverStatus = Literal["none", "queued", "running", "ready", "error"]
# Why the owner cannot ask for a cover now: turned off, the debate is not finished, one is being
# drawn, or it needs credits (the browser's own OpenRouter key still can).
CoverBlocker = Literal["off", "not_finished", "busy", "no_balance"]


class CoverImageOut(BaseModel):
    """One AI cover (a version): 16:9 at 1536 and 768 px wide, YouTube's 1280x720 JPEG and the
    1200x630 link preview."""

    id: str
    url: str
    small_url: str
    yt_url: str
    og_url: str
    hook: str = ""
    source: str = "owner"  # auto | owner | admin
    created_at: datetime | None = None


class CoverOut(BaseModel):
    """A debate's AI cover: the one shown (null: the markup cover) and the latest build's
    state. Versions, the error, the price and whether a new one can be asked for are for the
    owner only."""

    status: CoverStatus = "none"
    current: CoverImageOut | None = None
    versions: list[CoverImageOut] = Field(default_factory=list)
    error: str | None = None
    can_generate: bool = False
    reason: CoverBlocker | None = None
    price_usd: float = 0.0


class CoverRequest(BaseModel):
    """`POST /api/debates/{id}/cover`: a new version, optionally with the owner's own hook in
    place of the art director's (at most 4 words / 22 characters, ALL CAPS on the cover)."""

    hook: str | None = Field(default=None, max_length=22)
    user_provider_key: str | None = Field(default=None, max_length=300)


class CoverSelect(BaseModel):
    """`PUT /api/debates/{id}/cover`: the version to show (null: the markup cover)."""

    version: str | None = Field(default=None, max_length=32)


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
    cover: CoverImageOut | None = None  # the AI cover shown (null: the markup cover)
    cover_status: CoverStatus = "none"


class DebateSettingsOut(BaseModel):
    format: str = "debate"
    topic: str
    description: str | None = None
    language: str
    language_code: str = "en"
    num_rounds: int
    length_preset: str
    intensity: int
    output_style: OutputStyle = "markdown"
    # The news story behind a trending topic: public, so a remix by someone else keeps it.
    news: NewsContext | None = None


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


# --- Topics (services/motions) ---
class MotionRef(BaseModel):
    """A topic as the gallery sees it: counted over its public versions only."""

    slug: str
    title: str  # the first public version's topic
    versions: int
    models: list[str] = Field(default_factory=list)  # debater models across the versions
    path: str = ""  # the topic page's canonical path (services/seo)


class MotionVersion(BaseModel):
    """One public version of a topic (no verdict: the audience votes blind)."""

    id: str
    slug: str
    topic: str
    language: str
    language_code: str = "en"
    author_name: str | None = None
    participants: list[ParticipantOut] = Field(default_factory=list)
    likes: int = 0
    views: int = 0
    duration_ms: int | None = None
    premium_voices: bool = False
    published_at: datetime | None = None
    current: bool = False  # the debate being viewed
    path: str = ""


class MotionOut(BaseModel):
    """The topic of a debate and its public versions (the debate page's version strip)."""

    slug: str
    title: str
    versions: int
    items: list[MotionVersion] = Field(default_factory=list)
    path: str = ""


class RemixParentOut(BaseModel):
    slug: str
    topic: str
    path: str = ""


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
    # The public page's canonical path (`/d/{slug}/{kebab}`, services/seo) and its absolute URL;
    # null while the debate is not public.
    path: str | None = None
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
    # The topic's public versions (null when it has none) and the public debate it remixes.
    motion: MotionOut | None = None
    remix_of: RemixParentOut | None = None
    cover: CoverOut = Field(default_factory=CoverOut)


class StopDebateResponse(BaseModel):
    debate_id: str
    status: str


# --- Gallery ---
class GalleryItem(BaseModel):
    id: str
    slug: str
    format: str = "debate"
    title: str | None
    topic: str
    language: str
    language_code: str = "en"
    category: str | None = None
    author_name: str | None = None
    views: int = 0
    likes: int = 0
    votes: int = 0
    duration_ms: int | None = None
    has_media: bool = False
    premium_voices: bool = False  # the audio was voiced by ElevenLabs
    verdict: VerdictOut | None = None
    participants: list[ParticipantOut] = Field(default_factory=list)
    published_at: datetime | None = None
    motion: MotionRef | None = None  # the topic this debate is a version of
    path: str = ""  # canonical path of the debate's page
    cover: CoverImageOut | None = None  # the AI cover (null: the markup cover)


class GalleryLanguage(BaseModel):
    code: str  # ISO 639-1, as `GalleryItem.language_code`
    count: int  # cards in this language under the other filters


class GalleryResponse(BaseModel):
    items: list[GalleryItem]
    total: int  # debates, or topics with group=motion
    categories: list[str] = Field(default_factory=lambda: list(GALLERY_CATEGORIES))
    # Every language with cards under the request's other filters, most cards first.
    languages: list[GalleryLanguage] = Field(default_factory=list)


class MotionPage(BaseModel):
    """`/t/{slug}`: a topic and every public version of it."""

    slug: str
    title: str
    versions: int
    items: list[GalleryItem]
    path: str = ""


class MotionSuggestions(BaseModel):
    """For the wizard: the topic this text would join and similar topics to take the wording of
    (topics with public versions only)."""

    match: MotionRef | None = None
    similar: list[MotionRef] = Field(default_factory=list)


# --- Formats (services/formats) ---
class FormatSeat(BaseModel):
    label: str
    side: DebaterSide | None = None  # fixed by the format; null: the debater picks


class FormatFlow(BaseModel):
    """How a rapper sounds in a generated track (media/music.FLOWS), in place of a voice."""

    id: str
    label: str
    hint: str
    voice: Literal["male", "female"]


class FormatOut(BaseModel):
    """A show format as the wizard, the CLI and agents see it (`GET /api/formats`)."""

    id: str
    name: str
    show: str = "debate"  # the show in a sentence ("the battle")
    tagline: str
    host_label: str
    host_required: bool
    seats: list[FormatSeat]  # debater seats in speaking order; the last one repeats
    min_debaters: int
    max_debaters: int
    min_rounds: int
    max_rounds: int
    sides: bool  # debaters pick their own side
    visuals: bool  # charts and sketches may accompany the speeches
    # "elevenlabs": audio only with premium voices (no Edge); audio itself stays optional.
    voices: Literal["any", "elevenlabs"] = "any"
    # "music": one generated track carries the debaters (`media_plan.flows` instead of voices).
    soundtrack: Literal["speech", "music"] = "speech"
    verdict_scores: bool = False  # the judge scores every round
    # `soundtrack="music"`: the flows a debater may take, and each seat's default.
    flows: list[FormatFlow] = Field(default_factory=list)
    default_flows: list[str] = Field(default_factory=list)


# --- Model leaderboard ---
class LeaderboardEntry(BaseModel):
    model_id: str
    name: str
    is_free: bool
    rating: int
    # False until the model met another one in a debate that got audience votes: its rating is
    # then just the 1000 baseline.
    rated: bool = False
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


# --- Trending topics (services/trending.py) ---
class TrendingSource(BaseModel):
    title: str
    url: str
    outlet: str
    published_at: datetime | None = None


class TrendingTopicOut(BaseModel):
    id: str
    format: str = "debate"  # whose list it is on (formats.topic_list_of)
    rank: int  # 1 = hottest within that list
    label: str  # short chip title
    question: str  # the motion, ready for DebateConfig.topic
    brief: str  # what happened, for DebateConfig.description
    category: str
    heat: int  # 1-10
    outlets: int  # distinct outlets that carry the story
    sources: list[TrendingSource]


class TrendingCategory(BaseModel):
    id: str
    count: int


class TrendingTopicsOut(BaseModel):
    # The list shown: the format asked for when it writes topics its own way, else "debate".
    format: str = "debate"
    updated_at: datetime | None  # when the batch was built; None before the first one
    topics: list[TrendingTopicOut]
    categories: list[TrendingCategory]  # every category in display order, with its topic count


class TrendingArchiveOut(BaseModel):
    """`GET /api/topics/trending/search`: earlier batches' topics that match, newest first."""

    format: str
    topics: list[TrendingTopicOut]


class TopicIdeasIn(BaseModel):
    """The wizard's AI button: the user's own words for a topic (services/topic_ideas.py)."""

    text: str = Field(min_length=3, max_length=300)
    format: FormatId = "debate"
    language: str = Field(default="English", max_length=50)  # used when the text's is unclear


class TopicIdeasOut(BaseModel):
    format: FormatId
    ideas: list[str]  # best first; empty when the model would not write topics on the text


class FreeDebatesOut(BaseModel):
    """Limits of debates on free models for accounts without credits or an own key (0 or an
    empty list: none)."""

    per_day: int
    max_rounds: int
    max_debaters: int
    lengths: list[LengthPreset]


class SiteStatusOut(BaseModel):
    """`GET /api/status`: levers of the admin console the site reacts to."""

    registration_open: bool
    maintenance: bool  # new debates and audio builds are paused
    maintenance_message: str | None = None
    free_debates: FreeDebatesOut
    # AI covers (lever): off | paid | all_public, and what one costs from the balance.
    ai_covers: str = "paid"
    cover_price_usd: float = 0.0
    # The presence beacon (services/audience); off: the site sends none.
    analytics: bool = True
