from functools import cached_property
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

TERMINAL_DEBATE_STATUSES = frozenset({"completed", "error", "stopped"})


class Settings(BaseSettings):
    PROJECT_NAME: str = "AI Debates"
    ENVIRONMENT: Literal["development", "production"] = "development"
    LOG_LEVEL: str = "INFO"

    # Infrastructure. Defaults target a local `docker compose -f docker-compose.dev.yml up`.
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/ai_debates"
    REDIS_URL: str = "redis://localhost:6379/0"

    # OpenRouter
    OPENROUTER_API_KEY: str | None = None
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    # Used only when a participant has no model configured.
    DEFAULT_MODEL_ID: str = "openai/gpt-4o-mini"
    MODELS_CACHE_TTL: int = 3600
    LLM_CONNECT_TIMEOUT: float = 15.0
    LLM_READ_TIMEOUT: float = 120.0

    # Worker
    TURN_JOB_TIMEOUT: int = 600  # seconds per LLM turn job
    # Run jobs in-process instead of forking (useful on macOS during development).
    RQ_SIMPLE_WORKER: bool = False
    # User-supplied OpenRouter keys are kept in Redis only for the lifetime of a debate.
    PROVIDER_KEY_TTL: int = 86400

    # Abuse protection: debates per hour per client IP. 0 disables the limit.
    DEBATE_CREATE_RATE_LIMIT: int = 20

    # Media pipeline (neural TTS + timeline for browser-side video rendering)
    # Generated files live under MEDIA_ROOT (a shared volume in Docker) and are served
    # at /api/media/files. Relative paths resolve against the backend working directory.
    MEDIA_ROOT: str = "./media"
    MEDIA_JOB_TIMEOUT: int = 3600  # seconds for one audio build job
    # Comma-separated RQ queues a worker listens to ("default" = debate turns, "media" = TTS).
    RQ_QUEUES: str = "default,media"
    # Optional shared secret (header X-Media-Token) that bypasses the media rate limit.
    MEDIA_API_TOKEN: str | None = None
    ELEVENLABS_API_KEY: str | None = None
    ELEVENLABS_BASE_URL: str = "https://api.elevenlabs.io"
    TTS_DEFAULT_MODEL_ID: str = "eleven_v3"
    TTS_MAX_CHARS_PER_REQUEST: int = 2500
    TTS_CONCURRENCY: int = 2
    # Cheap model used to pick short-video highlights and the winner from the transcript.
    MEDIA_HIGHLIGHTS_MODEL: str = "openai/gpt-4o-mini"
    # Model that designs the visual scenes (charts, drawn schemes) per turn; empty = the
    # highlights model. Runs on the system key and is not billed to the user (~$0.01/debate).
    MEDIA_VISUALS_MODEL: str = "google/gemini-2.5-flash"
    MEDIA_VISUALS_CONCURRENCY: int = 4
    # Illustrator of "sketch" scenes (SVG line art, sanitized), system key, not billed; empty =
    # the visuals model. anthropic/claude-haiku-5.5 draws cleaner but takes ~13 s.
    MEDIA_SKETCH_MODEL: str = "google/gemini-3.5-flash-lite"
    # "image" scenes: free photos from Wikimedia Commons or AI pictures (MediaOptions.images).
    # AI pictures are paid from the owner's balance (cost x CREDIT_MARKUP); the visuals model
    # checks every picture before it is used.
    MEDIA_IMAGE_MODEL: str = "black-forest-labs/flux-3-image-klein"
    MEDIA_IMAGE_PRICE_USD: float = 0.009  # per AI picture, for estimates
    MEDIA_MAX_IMAGES: int = 6  # pictures per debate
    # Web fact-check of on-screen figures and quotes (DebateConfig.fact_check). Runs during the
    # debate on the debate's OpenRouter key and is billed like the debate.
    FACT_CHECK_MODEL: str = "perplexity/sonar"
    FACT_CHECK_MAX_PER_TURN: int = 2
    FACT_CHECK_PRICE_USD: float = 0.006  # per check, for estimates
    MEDIA_GAP_MS: int = 600
    MEDIA_LOUDNESS_LUFS: float = -16.0
    FFMPEG_BIN: str = "ffmpeg"
    FFPROBE_BIN: str = "ffprobe"

    # Site / admin
    SITE_URL: str = "http://localhost"
    ADMIN_USER: str = "admin"
    ADMIN_PASSWORD: str = "changeme"
    SECRET_KEY: str = "secret-key-for-sessions-change-me"
    ALLOWED_ORIGINS: str = "http://localhost,http://localhost:5173,http://localhost:3000"

    # Accounts, credits and billing
    SESSION_MAX_AGE: int = 60 * 60 * 24 * 30  # seconds the login cookie stays valid
    LOGIN_RATE_LIMIT: int = 30  # login/register attempts per IP per hour (0 disables)
    SIGNUP_BONUS_USD: float = 0.0  # welcome credits for every new account (0 disables)
    # Multiplier applied to the provider cost (OpenRouter usage) when charging credits.
    CREDIT_MARKUP: float = 1.2
    # Premium (ElevenLabs) voices on the system key, charged to credits per 1000 characters.
    TTS_CREDIT_PRICE_PER_1K_CHARS: float = 0.15
    TOPUP_AMOUNTS_USD: str = "5,10,25"
    STRIPE_SECRET_KEY: str | None = None
    STRIPE_WEBHOOK_SECRET: str | None = None
    STRIPE_CURRENCY: str = "usd"
    # Development only: top-ups are credited instantly without Stripe.
    DEV_FAKE_PAYMENTS: bool = False

    model_config = SettingsConfigDict(
        env_file=[".env", "../.env"],
        env_ignore_empty=True,
        case_sensitive=True,
        extra="ignore",
    )

    @cached_property
    def sync_database_url(self) -> str:
        """Blocking driver URL for the RQ worker (psycopg 3)."""
        return self.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql+psycopg://")

    @cached_property
    def media_root_path(self) -> Path:
        return Path(self.MEDIA_ROOT).expanduser().resolve()

    @cached_property
    def rq_queue_names(self) -> list[str]:
        return [q.strip() for q in self.RQ_QUEUES.split(",") if q.strip()] or ["default"]

    @cached_property
    def allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",") if o.strip()]

    @cached_property
    def topup_amounts(self) -> list[int]:
        amounts: list[int] = []
        for raw in self.TOPUP_AMOUNTS_USD.split(","):
            raw = raw.strip()
            if raw.isdigit() and int(raw) > 0:
                amounts.append(int(raw))
        return amounts or [5, 10, 25]

    @property
    def payments_mode(self) -> str:
        """stripe | dev (instant fake top-ups) | disabled."""
        if self.STRIPE_SECRET_KEY:
            return "stripe"
        if self.DEV_FAKE_PAYMENTS and not self.is_production:
            return "dev"
        return "disabled"

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    def insecure_defaults(self) -> list[str]:
        """Names of secrets still set to their placeholder values."""
        found: list[str] = []
        if self.SECRET_KEY == "secret-key-for-sessions-change-me":
            found.append("SECRET_KEY")
        if self.ADMIN_PASSWORD == "changeme":
            found.append("ADMIN_PASSWORD")
        return found


settings = Settings()
