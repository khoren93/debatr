import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqladmin import Admin
from sqlalchemy import text
from starlette.concurrency import run_in_threadpool
from starlette.middleware.sessions import SessionMiddleware

from app.admin.auth import authentication_backend
from app.admin.views import (
    ApiTokenAdmin,
    CreditTransactionAdmin,
    DebateAdmin,
    LikeAdmin,
    ParticipantAdmin,
    SessionAdmin,
    TurnAdmin,
    UserAdmin,
    VoteAdmin,
)
from app.api import (
    routes_auth,
    routes_billing,
    routes_debates,
    routes_gallery,
    routes_media,
    routes_models,
    routes_presets,
    routes_reactions,
    routes_stream,
    routes_tokens,
)
from app.core.config import settings
from app.core.db import engine
from app.core.logging import setup_logging
from app.core.media_static import MediaStaticFiles
from app.core.redis import close_async_redis, get_async_redis
from app.services.media.tts.elevenlabs import system_key_status

setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
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
    version="0.2.0",
    openapi_url="/api/openapi.json",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    lifespan=lifespan,
)

# Signed session cookie: user login (uid) and admin panel login (token).
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.SECRET_KEY,
    https_only=settings.is_production,
    same_site="lax",
    max_age=settings.SESSION_MAX_AGE,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Admin panel
admin = Admin(app, engine, authentication_backend=authentication_backend, base_url="/api/admin")
admin.add_view(UserAdmin)
admin.add_view(ApiTokenAdmin)
admin.add_view(CreditTransactionAdmin)
admin.add_view(DebateAdmin)
admin.add_view(LikeAdmin)
admin.add_view(VoteAdmin)
admin.add_view(ParticipantAdmin)
admin.add_view(TurnAdmin)
admin.add_view(SessionAdmin)

# Routers
app.include_router(routes_auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(routes_tokens.router, prefix="/api/auth", tags=["api tokens"])
app.include_router(routes_billing.router, prefix="/api/billing", tags=["billing"])
app.include_router(routes_models.router, prefix="/api/models", tags=["models"])
app.include_router(routes_presets.router, prefix="/api/presets", tags=["presets"])
app.include_router(routes_gallery.router, prefix="/api/gallery", tags=["gallery"])
app.include_router(routes_debates.router, prefix="/api/debates", tags=["debates"])
app.include_router(routes_reactions.router, prefix="/api/debates", tags=["reactions"])
app.include_router(routes_stream.router, prefix="/api/debates", tags=["stream"])
app.include_router(routes_media.router, prefix="/api", tags=["media"])

# Generated audio + timeline files. Mounted after the routers so /api/media/voices etc. win.
app.mount(
    "/api/media/files",
    MediaStaticFiles(directory=str(settings.media_root_path), check_dir=False),
    name="media",
)


@app.get("/api", tags=["meta"])
def read_root() -> dict[str, str]:
    return {"message": "Welcome to AI Debates API", "docs": "/api/docs"}


@app.get("/api/health", tags=["meta"])
async def health_check() -> JSONResponse:
    """Liveness + readiness: verifies database and Redis connectivity."""
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

    healthy = all(v == "ok" for v in checks.values())
    return JSONResponse(
        status_code=200 if healthy else 503,
        content={"status": "ok" if healthy else "degraded", "checks": checks},
    )
