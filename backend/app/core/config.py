from functools import cached_property
from ipaddress import IPv4Network, IPv6Network, ip_network
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
    LLM_READ_TIMEOUT: float = 120.0  # silence between stream lines
    # Wall-clock limit of one turn's answer. Keep-alive comments and reasoning chunks reset the
    # read timeout, so a stuck provider or a model that keeps thinking would otherwise hold the
    # turn until TURN_JOB_TIMEOUT kills the job (and the debate). Keep it well below that one:
    # the job also designs the turn's scenes.
    LLM_TURN_TIMEOUT: float = 300.0

    # Worker
    TURN_JOB_TIMEOUT: int = 600  # seconds per LLM turn job
    # Run jobs in-process instead of forking (useful on macOS during development). Docker forks:
    # a job that hangs is killed without taking its worker down.
    RQ_SIMPLE_WORKER: bool = False
    # Fair share: debates (queued + running) and audio builds one user may have at a time, so
    # nobody holds every worker. 0 = no limit.
    MAX_ACTIVE_DEBATES_PER_USER: int = 2
    MAX_ACTIVE_MEDIA_PER_USER: int = 2
    # `:free` model requests a minute on the system key, for all users together: OpenRouter
    # allows 20 per account (keys do not add up). Turns wait for a slot. 0 = no limit.
    FREE_MODELS_PER_MINUTE: int = 18
    # Times a run whose worker died (no heartbeat, no queued job) is queued again before it
    # fails and waits for Resume (services/recovery, checked every minute by the scheduler).
    RECOVERY_ATTEMPTS: int = 2
    # User-supplied OpenRouter keys are kept in Redis only for the lifetime of a debate.
    PROVIDER_KEY_TTL: int = 86400

    # Abuse protection: debates per hour per client IP. 0 disables the limit.
    DEBATE_CREATE_RATE_LIMIT: int = 20

    # Media pipeline (neural TTS + timeline for browser-side video rendering)
    # Generated files live under MEDIA_ROOT (a shared volume in Docker) and are served
    # at /api/media/files. Relative paths resolve against the backend working directory.
    MEDIA_ROOT: str = "./media"
    MEDIA_JOB_TIMEOUT: int = 3600  # seconds for one audio build job
    # Comma-separated RQ queues a worker listens to, in priority order ("default" = debate
    # turns, "background" = trending topics and recovery checks, "media" = TTS).
    RQ_QUEUES: str = "default,background,media"
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
    # Trending topics (services/trending.py): RSS headlines -> debate topics, one batch per run.
    # Hours between batches; 0 turns automatic refreshes off (the admin can still build one).
    TRENDING_REFRESH_HOURS: int = 24
    TRENDING_MODEL: str = "google/gemini-2.5-flash"  # system key, ~$0.02 per batch
    TRENDING_TOPIC_COUNT: int = 50
    MEDIA_GAP_MS: int = 600
    MEDIA_LOUDNESS_LUFS: float = -16.0
    FFMPEG_BIN: str = "ffmpeg"
    FFPROBE_BIN: str = "ffprobe"

    # Site
    SITE_URL: str = "http://localhost"
    SECRET_KEY: str = "secret-key-for-sessions-change-me"

    # Admin console (/admin + /api/admin, app/admin): admins are accounts with `users.admin_role`
    # (granted with `python -m app.manage admin grant`), signing in with password + TOTP.
    # Host the console answers on, e.g. "admin.example.com": its own origin, so a script on the
    # site (or on a sibling subdomain) cannot reach it. Empty: the site's origin in development,
    # no console at all in production.
    ADMIN_HOST: str = ""
    # Optional comma-separated CIDRs allowed to reach the console ("" = any address).
    ADMIN_ALLOWED_IPS: str = ""
    # Credit adjustments above this need a fresh TOTP code (sudo).
    ADMIN_SUDO_USD: float = 20.0
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

    @property
    def admin_hostname(self) -> str:
        """ADMIN_HOST without scheme, port or path, lowercase ("" when unset)."""
        raw = self.ADMIN_HOST.strip().lower()
        raw = raw.split("://", 1)[-1].split("/", 1)[0]
        return raw.rsplit(":", 1)[0] if raw.count(":") == 1 else raw

    @property
    def admin_console_enabled(self) -> bool:
        """Production serves the console only on its own host."""
        return bool(self.admin_hostname) or not self.is_production

    @property
    def admin_networks(self) -> list[IPv4Network | IPv6Network]:
        return [
            ip_network(part.strip(), strict=False)
            for part in self.ADMIN_ALLOWED_IPS.split(",")
            if part.strip()
        ]

    def insecure_defaults(self) -> list[str]:
        """Names of secrets still set to their placeholder values."""
        found: list[str] = []
        if self.SECRET_KEY == "secret-key-for-sessions-change-me":
            found.append("SECRET_KEY")
        return found


settings = Settings()
