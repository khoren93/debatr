import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.concurrency import run_in_threadpool
from starlette.middleware.sessions import SessionMiddleware

from app.admin.gate import AdminGate
from app.api import admin as admin_api
from app.api import (
    routes_auth,
    routes_billing,
    routes_debates,
    routes_formats,
    routes_gallery,
    routes_media,
    routes_models,
    routes_motions,
    routes_presets,
    routes_reactions,
    routes_seo,
    routes_status,
    routes_stream,
    routes_tokens,
    routes_topics,
)
from app.core.auth import session_cookie_options
from app.core.config import settings
from app.core.db import engine
from app.core.logging import setup_logging
from app.core.media_static import MediaStaticFiles
from app.core.redis import close_async_redis, get_async_redis, get_sync_redis
from app.services import queue_manager
from app.services.media.tts.elevenlabs import system_key_status

setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    if not settings.admin_console_enabled:
        logger.error("ADMIN_HOST is not set: the admin console is off (see .env.example)")
    if settings.ADMIN_SKIP_2FA:
        if settings.is_production:
            logger.error("ADMIN_SKIP_2FA is ignored in production: the console asks for 2FA")
        else:
            logger.warning("ADMIN_SKIP_2FA: the admin console signs in with the password alone")
    insecure = settings.insecure_defaults()
    if insecure:
        message = f"Placeholder secrets in use: {', '.join(insecure)}"
        if settings.is_production:
            logger.error(message)
        else:
            logger.warning(message)
    if not settings.OPENROUTER_API_KEY:
        logger.warning("OPENROUTER_API_KEY is not set; only user-supplied keys will work")
    if not settings.ELEVENLABS_API_KEY:
        logger.info("ELEVENLABS_API_KEY is not set; media builds use the free Edge voices")
    else:
        ok, reason = await run_in_threadpool(system_key_status)
        if not ok:
            logger.warning("ELEVENLABS_API_KEY was rejected (%s); premium voices are off", reason)
    settings.media_root_path.mkdir(parents=True, exist_ok=True)
    yield
    await close_async_redis()
    await engine.dispose()


app = FastAPI(
    title=settings.PROJECT_NAME,
    description="API for AI-driven debates using OpenRouter",
    version="1.3.0",
    openapi_url="/api/openapi.json",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    lifespan=lifespan,
)

# Signed session cookie of the site: the user's id and session epoch (app.core.auth).
app.add_middleware(SessionMiddleware, secret_key=settings.SECRET_KEY, **session_cookie_options())

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Outermost: the admin console's host, IP, Fetch Metadata and Origin checks run before CORS,
# so no other origin ever gets a CORS answer from /api/admin.
app.add_middleware(AdminGate)

# Routers
app.include_router(admin_api.router, prefix="/api/admin")
app.include_router(routes_status.router, prefix="/api", tags=["meta"])
app.include_router(routes_auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(routes_tokens.router, prefix="/api/auth", tags=["api tokens"])
app.include_router(routes_billing.router, prefix="/api/billing", tags=["billing"])
app.include_router(routes_models.router, prefix="/api/models", tags=["models"])
app.include_router(routes_presets.router, prefix="/api/presets", tags=["presets"])
app.include_router(routes_formats.router, prefix="/api/formats", tags=["formats"])
app.include_router(routes_topics.router, prefix="/api/topics", tags=["topics"])
app.include_router(routes_gallery.router, prefix="/api/gallery", tags=["gallery"])
app.include_router(routes_motions.router, prefix="/api/motions", tags=["gallery"])
app.include_router(routes_debates.router, prefix="/api/debates", tags=["debates"])
app.include_router(routes_reactions.router, prefix="/api/debates", tags=["reactions"])
app.include_router(routes_stream.router, prefix="/api/debates", tags=["stream"])
app.include_router(routes_media.router, prefix="/api", tags=["media"])
# robots.txt, the sitemaps and the IndexNow key, outside /api (frontend/Caddyfile routes them).
app.include_router(routes_seo.router)

# Generated audio + timeline files. Mounted after the routers so /api/media/voices etc. win.
app.mount(
    "/api/media/files",
    MediaStaticFiles(directory=str(settings.media_root_path), check_dir=False),
    name="media",
)


@app.get("/api", tags=["meta"])
def read_root() -> dict[str, str]:
    return {"message": "Welcome to AI Debates API", "docs": "/api/docs"}


async def _connectivity() -> dict[str, str]:
    checks: dict[str, str] = {}
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {e.__class__.__name__}"
    try:
        await get_async_redis().ping()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {e.__class__.__name__}"
    return checks


def _health(checks: dict[str, str]) -> JSONResponse:
    healthy = all(v == "ok" for v in checks.values())
    return JSONResponse(
        status_code=200 if healthy else 503,
        content={"status": "ok" if healthy else "degraded", "checks": checks},
    )


@app.get("/api/health", tags=["meta"])
async def health_check() -> JSONResponse:
    """Liveness + readiness: verifies database and Redis connectivity."""
    return _health(await _connectivity())


@app.get("/api/health/full", tags=["meta"])
async def full_health_check() -> JSONResponse:
    """For an outside uptime monitor: also 503 when a queue has no worker or the cron scheduler
    is gone. The Telegram alerts run on those processes, so they cannot report their own end
    (nor a server that is down). Not the container's healthcheck: the API is fine without them."""
    checks = await _connectivity()
    if checks["redis"] == "ok":
        try:
            checks |= await run_in_threadpool(queue_manager.process_checks, get_sync_redis())
        except Exception as e:
            checks["workers"] = f"error: {e.__class__.__name__}"
    return _health(checks)
