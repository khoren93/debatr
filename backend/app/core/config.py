from functools import cached_property
from ipaddress import IPv4Network, IPv6Network, ip_network
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

TERMINAL_DEBATE_STATUSES = frozenset({"completed", "error", "stopped"})


def bare_host(raw: str) -> str:
    """A host setting without scheme, port or path, lowercase ("" when empty)."""
    host = raw.strip().lower().split("://", 1)[-1].split("/", 1)[0]
    return host.rsplit(":", 1)[0] if host.count(":") == 1 else host


class Settings(BaseSettings):
    PROJECT_NAME: str = "Debatr"
    # The commit the image was built from (Docker build-arg GIT_SHA, set by deploy.sh).
    APP_VERSION: str = "dev"
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
    # Free debates (system key, every model free, no balance; services/free_limits): a day's
    # allowance per account (rolling 24 h) and their size. 0 / empty = no limit. Credits or an
    # own OpenRouter key lift them. Levers of the admin console override these.
    FREE_DEBATES_PER_DAY: int = 5
    FREE_MAX_ROUNDS: int = 3
    FREE_MAX_DEBATERS: int = 4
    FREE_LENGTHS: str = "very_short,short"
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
    TTS_DEFAULT_MODEL_ID: str = "eleven_v4"
    TTS_MAX_CHARS_PER_REQUEST: int = 2500
    TTS_CONCURRENCY: int = 2
    # Structures the judge's verdict (winner, headline) and answers the hidden gallery check
    # (services/verdict.py, services/moderation.py) on the debate's key, not billed. A fixed
    # model on purpose: the debate's author picks the host, so the host must not moderate its
    # own debate. MEDIA_HIGHLIGHTS_MODEL is its old name (Short highlights now ask the host).
    VERDICT_MODEL: str = Field(
        default="openai/gpt-4o-mini",
        validation_alias=AliasChoices("VERDICT_MODEL", "MEDIA_HIGHLIGHTS_MODEL"),
    )
    # The same job for a debate whose participants all argue on free models, so it costs
    # nothing: a `:free` model (empty = VERDICT_MODEL). The console's lever overrides it.
    FREE_VERDICT_MODEL: str = "minimax/minimax-m3.1-flash:free"
    # Model that designs the visual scenes (charts, drawn schemes) per turn; empty =
    # VERDICT_MODEL. Runs on the system key and is not billed to the user (~$0.01/debate).
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
    # AI covers (services/media/cover.py): an art director writes the brief from the episode
    # (never the verdict), the image model draws a 16:9 thumbnail with the debaters' logos as
    # references, the visuals model checks it. On the debate's key (an own OpenRouter key pays
    # OpenRouter itself), else paid from the owner's balance: provider cost x markup.
    # AI_COVERS: off | paid (runs paid from the balance or an own key get one automatically) |
    # all_public (free public debates too, at the operator's cost); the console's lever wins.
    AI_COVERS: str = "paid"
    COVER_DIRECTOR_MODEL: str = "anthropic/claude-sonnet-5.5"
    COVER_IMAGE_MODEL: str = "openai/gpt-image-2.5-sunburst"
    COVER_IMAGE_QUALITY: str = "medium"  # low | medium | high (GPT Image)
    COVER_CHECK_MODEL: str = ""  # vision check of the picture; empty = MEDIA_VISUALS_MODEL
    COVER_PRICE_USD: float = 0.035  # provider cost of one cover, for estimates (x markup)
    # The site's server renderer (frontend `web`), which draws the logo references of the covers
    # (/og/logo.png): compose sets http://web:3000; natively `npm run dev` on :5173.
    WEB_INTERNAL_URL: str = "http://localhost:5173"
    # Web fact-check of on-screen figures and quotes (DebateConfig.fact_check). Runs during the
    # debate on the debate's OpenRouter key and is billed like the debate.
    FACT_CHECK_MODEL: str = "perplexity/sonar"
    FACT_CHECK_MAX_PER_TURN: int = 2
    FACT_CHECK_PRICE_USD: float = 0.006  # per check, for estimates
    # Trending topics (services/trending.py): RSS headlines -> a list of topics per show format,
    # one batch per run. Hours between batches; 0 turns automatic refreshes off (the admin can
    # still build one).
    TRENDING_REFRESH_HOURS: int = 24
    # Topics written per format's list in a batch, and how many of the newest batch the wizard
    # shows (older batches are found by search). The console's levers override both.
    TRENDING_TOPIC_COUNT: int = 20
    TRENDING_SHOWN_TOPICS: int = 50
    # The topic writer: trending lists and the wizard's AI topic ideas (services/topic_ideas.py),
    # and the independent safety review of the trending lists (another vendor on purpose). System
    # key, not billed (~$0.03 a batch, ~$0.0001 an idea). The console's levers override both.
    TOPIC_MODEL: str = "anthropic/claude-haiku-5.5"
    TOPIC_REVIEW_MODEL: str = "google/gemini-2.5-flash"
    TOPIC_IDEAS_PER_HOUR: int = 40  # AI topic ideas per account and hour (0 = no limit)
    MEDIA_GAP_MS: int = 600
    MEDIA_LOUDNESS_LUFS: float = -16.0
    FFMPEG_BIN: str = "ffmpeg"
    FFPROBE_BIN: str = "ffprobe"

    # Site
    SITE_URL: str = "http://localhost"
    # Former hosts of the site, comma separated (e.g. "ai-debates.net"): the outer proxy sends
    # their pages to SITE_URL with a 301, and links to them still count as the site's own
    # (oEmbed answers for them, a view from them is internal).
    SITE_ALIASES: str = ""
    SECRET_KEY: str = "secret-key-for-sessions-change-me"
    # Search engines (app/api/routes_seo, services/indexnow). AI crawlers (GPTBot, ClaudeBot,
    # PerplexityBot, Google-Extended…) may read the public pages unless this is false.
    SEO_ALLOW_AI_CRAWLERS: bool = True
    # IndexNow (Bing, Yandex, Seznam, Naver, Yep): any 8-128 letters, digits or dashes, served
    # at /{key}.txt. Changed public pages are announced at most once a minute; only in production
    # with an https SITE_URL. Empty = off.
    INDEXNOW_KEY: str = ""
    # Visits (app.services.audience; the admin console's Audience page). The levers
    # analytics_enabled / analytics_ip_days override the two env values.
    ANALYTICS_ENABLED: bool = True
    ANALYTICS_IP_DAYS: int = 90  # IP and User-Agent of a visit are cleared after this (0: kept)
    PRESENCE_RATE_LIMIT: int = 600  # beacons per IP per 10 minutes (0 disables)
    # IP → country, region and city: DB-IP's free "IP to City Lite" database (CC BY 4.0), fetched
    # monthly into this folder by the background queue (`python -m app.manage geoip update` now).
    # Empty GEOIP_URL: no download (put a GeoLite2-City / DB-IP .mmdb there by hand).
    GEOIP_DIR: str = "./geoip"
    GEOIP_URL: str = "https://download.db-ip.com/free/dbip-city-lite-{month}.mmdb.gz"
    # IP → network (AS number and operator) the same way, to tell data centres from home and
    # mobile networks (audience/bots.py). Empty: no download (asn.mmdb by hand, or none).
    GEOIP_ASN_URL: str = "https://download.db-ip.com/free/dbip-asn-lite-{month}.mmdb.gz"

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
    # Development only: the console signs in with the password alone (no authenticator, no
    # enrollment, no sudo codes). Ignored in production.
    ADMIN_SKIP_2FA: bool = False
    # Optional operator alerts to Telegram (app.services.alerts): a bot from @BotFather and the
    # chat it writes to (your user id, or a group's id with the bot in it).
    ALERT_TELEGRAM_BOT_TOKEN: str | None = None
    ALERT_TELEGRAM_CHAT_ID: str | None = None
    ALLOWED_ORIGINS: str = "http://localhost,http://localhost:5173,http://localhost:3000"

    # Accounts, credits and billing
    SESSION_MAX_AGE: int = 60 * 60 * 24 * 30  # seconds the login cookie stays valid
    LOGIN_RATE_LIMIT: int = 30  # login/register attempts per IP per hour (0 disables)
    SIGNUP_BONUS_USD: float = 0.0  # welcome credits for every new account (0 disables)
    # Prices (levers of the admin console override them; a run keeps the prices it started
    # with, services/credits.Prices). The provider cost of models, fact-checks and AI pictures
    # is charged times CREDIT_MARKUP; a completed paid debate costs at least
    # MIN_DEBATE_CHARGE_USD; premium (ElevenLabs) voices on the system key cost
    # TTS_CREDIT_PRICE_PER_1K_CHARS per 1000 characters; a rap battle's generated music on the
    # system key costs MUSIC_CREDIT_PRICE_PER_MIN a minute (ElevenLabs: $0.15).
    CREDIT_MARKUP: float = 1.2
    MIN_DEBATE_CHARGE_USD: float = 0.0
    TTS_CREDIT_PRICE_PER_1K_CHARS: float = 0.15
    MUSIC_CREDIT_PRICE_PER_MIN: float = 0.30
    TOPUP_AMOUNTS_USD: str = "5,10,25"
    STRIPE_SECRET_KEY: str | None = None
    STRIPE_WEBHOOK_SECRET: str | None = None
    STRIPE_CURRENCY: str = "usd"
    # Development only: top-ups are credited instantly without Stripe.
    DEV_FAKE_PAYMENTS: bool = False

    # Where people write to us: the site's Contact link and /privacy (`GET /api/status`), and
    # the Reply-To of its mail unless MAIL_REPLY_TO says otherwise. Empty: no contact address.
    SUPPORT_EMAIL: str = ""

    # Mail (services/mail): the SMTP relay of the sending service (Resend: smtp.resend.com,
    # port 465 = TLS from the start, 587 = STARTTLS; user "resend", password = an API key with
    # sending access). Without a host, a password and MAIL_FROM nothing is sent: the message is
    # logged.
    MAIL_SMTP_HOST: str = ""
    MAIL_SMTP_PORT: int = 465
    MAIL_SMTP_USER: str = "resend"
    MAIL_SMTP_PASSWORD: str | None = None
    MAIL_FROM: str = ""  # e.g. "Debatr <noreply@example.com>", on a domain the service verified
    MAIL_REPLY_TO: str = ""  # where replies go; empty: SUPPORT_EMAIL
    # Signing secret (whsec_…) of the sending service's webhook to POST /api/mail/events
    # (Resend: delivered, bounced, complained…); without it the console shows only what the relay
    # said. The console's Mail page keeps letters (never their text) for MAIL_LOG_DAYS.
    MAIL_WEBHOOK_SECRET: str | None = None
    MAIL_LOG_DAYS: int = 90

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

    @property
    def geoip_path(self) -> Path:
        return Path(self.GEOIP_DIR).expanduser().resolve()

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
        return bare_host(self.ADMIN_HOST)

    @cached_property
    def site_aliases(self) -> tuple[str, ...]:
        """SITE_ALIASES as hosts without scheme, port, path or "www."."""
        hosts = (bare_host(raw).removeprefix("www.") for raw in self.SITE_ALIASES.split(","))
        return tuple(dict.fromkeys(host for host in hosts if host))

    @property
    def admin_console_enabled(self) -> bool:
        """Production serves the console only on its own host."""
        return bool(self.admin_hostname) or not self.is_production

    @property
    def admin_skip_2fa(self) -> bool:
        """ADMIN_SKIP_2FA, honoured outside production only."""
        return self.ADMIN_SKIP_2FA and not self.is_production

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
