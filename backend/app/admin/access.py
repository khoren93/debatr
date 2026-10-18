"""Who may use the admin console: the `/api/admin/*` routes and sqladmin under `/api/admin/db`.

`resolve_admin` turns the console's session cookie into an AdminContext. It refuses API tokens
(an `Authorization` header is never accepted here), sessions that ended, and accounts that are
disabled, lost their role, have no second factor or bumped their `session_epoch` (password
change, 2FA reset, "sign out everywhere"). Unsafe methods also need the session's CSRF token in
`X-CSRF-Token`, on top of AdminGate's Fetch Metadata and Origin checks. `require_admin(perm)`
adds the role check and `require_sudo` a TOTP code confirmed within the last few minutes.
"""

import hmac
import time
import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import AsyncSessionLocal, get_db
from app.core.ratelimit import enforce_limit
from app.core.redis import get_async_redis
from app.models.models import User
from app.services.admin import sessions
from app.services.admin.audit import client_ip, user_agent
from app.services.admin.sessions import AdminSession

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
CSRF_HEADER = "X-CSRF-Token"
# Set on a 403 that a fresh TOTP code would lift (the console then asks for one and retries).
SUDO_HEADER = "X-Admin-Sudo"
ROLES = ("admin", "moderator")
PERMISSIONS: dict[str, frozenset[str]] = {
    "admin": frozenset({"*"}),
    # Prepared for a helper: moderation and reading debates, nothing about money or accounts.
    "moderator": frozenset({"console", "debates.read", "moderation"}),
}
API_REQUESTS_PER_WINDOW = 1200
API_WINDOW_SECONDS = 600


# Console reads run in a read-only transaction with a statement timeout, so a heavy statistics
# query can neither change data nor hold the production database.
READ_TIMEOUT_MS = 5000


async def read_only_db() -> AsyncGenerator[AsyncSession]:
    async with AsyncSessionLocal() as db:
        await db.execute(text("SET TRANSACTION READ ONLY"))
        await db.execute(text(f"SET LOCAL statement_timeout = {READ_TIMEOUT_MS}"))
        yield db


def can(role: str | None, permission: str) -> bool:
    granted = PERMISSIONS.get(role or "", frozenset())
    return "*" in granted or permission in granted


# --- cookies ----------------------------------------------------------------------------------


def is_secure(request: Request) -> bool:
    return settings.is_production or request.url.scheme == "https"


def _cookie_name(request: Request, base: str) -> str:
    # `__Host-`: Secure, Path=/, no Domain, so a sibling subdomain can neither read nor plant
    # it. Browsers accept the prefix only over https; plain-http development drops it.
    return f"__Host-{base}" if is_secure(request) else base


def session_cookie_name(request: Request) -> str:
    return _cookie_name(request, "debatr_admin")


def ticket_cookie_name(request: Request) -> str:
    return _cookie_name(request, "debatr_admin_signin")


def set_cookie(response: Response, request: Request, name: str, value: str, max_age: int) -> None:
    response.set_cookie(
        name,
        value,
        max_age=max_age,
        path="/",
        secure=is_secure(request),
        httponly=True,
        samesite="strict",
    )


def clear_cookie(response: Response, request: Request, name: str) -> None:
    response.delete_cookie(
        name, path="/", secure=is_secure(request), httponly=True, samesite="strict"
    )


# --- the signed-in admin ----------------------------------------------------------------------


@dataclass
class AdminContext:
    user: User
    session: AdminSession
    session_hash: str
    ip: str | None
    user_agent: str | None

    def can(self, permission: str) -> bool:
        return can(self.user.admin_role, permission)


def _unauthorized(detail: str = "Sign in to the admin console") -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


def account_allows_console(user: User | None, session: AdminSession) -> bool:
    """The account still may use this session (checked on every request)."""
    return (
        user is not None
        and user.is_active
        and user.admin_role in ROLES
        and user.totp_enabled_at is not None
        and user.session_epoch == session.epoch
        and str(user.id) == session.user_id
    )


async def resolve_admin(
    request: Request, db: AsyncSession, *, now: float | None = None
) -> AdminContext | None:
    """The live console session of this request, or None. Ends sessions the account no longer
    allows."""
    if request.headers.get("authorization"):
        return None
    token = request.cookies.get(session_cookie_name(request))
    if not token:
        return None
    moment = time.time() if now is None else now
    redis = get_async_redis()
    hashed = sessions.token_hash(token)
    session = await sessions.load_session(redis, hashed, moment)
    if session is None:
        return None
    try:
        user = await db.get(User, uuid.UUID(session.user_id))
    except ValueError:
        user = None
    if not account_allows_console(user, session):
        await sessions.delete_session(redis, session.user_id, hashed)
        return None
    assert user is not None
    if moment - session.last_seen_at >= sessions.TOUCH_EVERY_SECONDS:
        session.last_seen_at = moment
        await sessions.save_session(redis, hashed, session, moment)
    return AdminContext(
        user=user,
        session=session,
        session_hash=hashed,
        ip=client_ip(request),
        user_agent=user_agent(request),
    )


def csrf_ok(request: Request, session: AdminSession) -> bool:
    if request.method in SAFE_METHODS:
        return True
    sent = request.headers.get(CSRF_HEADER) or ""
    return hmac.compare_digest(sent.encode(), session.csrf.encode())


async def enforce_admin_api_limit(request: Request) -> None:
    await enforce_limit(
        request,
        bucket="admin_api",
        limit=API_REQUESTS_PER_WINDOW,
        window_seconds=API_WINDOW_SECONDS,
        what="admin requests",
    )


async def current_admin(request: Request, db: AsyncSession = Depends(get_db)) -> AdminContext:
    ctx = await resolve_admin(request, db)
    if ctx is None:
        raise _unauthorized()
    if not csrf_ok(request, ctx.session):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing CSRF token")
    request.state.admin = ctx
    return ctx


def require_admin(permission: str = "console") -> Callable[..., Awaitable[AdminContext]]:
    """Dependency: a console session whose role grants `permission`."""

    async def dependency(ctx: AdminContext = Depends(current_admin)) -> AdminContext:
        if not ctx.can(permission):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed")
        return ctx

    return dependency


def sudo_required() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Confirm with a code from your authenticator app",
        headers={SUDO_HEADER: "required"},
    )


async def require_sudo(ctx: AdminContext = Depends(current_admin)) -> AdminContext:
    if not ctx.session.is_sudo(time.time()):
        raise sudo_required()
    return ctx
