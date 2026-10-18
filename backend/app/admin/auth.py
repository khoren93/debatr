"""sqladmin (/api/admin/db) behind the admin console's own sign-in.

There is no password of its own any more: a request passes when it carries a live console
session of an account with the `admin` role (app.admin.access), on the console's host
(AdminGate). Anything else goes to the console's sign-in page, and signing out here ends the
console session. sqladmin's actions are GET links: the session cookie is SameSite=Strict and
AdminGate refuses requests started by other origins, so a link elsewhere cannot fire them.
"""

import uuid

from sqladmin.audit import AuditBackend, AuditEntry
from sqladmin.authentication import AuthenticationBackend
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from app.admin.access import resolve_admin
from app.core.auth import session_cookie_options
from app.core.config import settings
from app.core.db import AsyncSessionLocal
from app.core.redis import get_async_redis
from app.services.admin import audit, sessions

SIGN_IN = "/admin/login?next=/api/admin/db/"


class AdminAuth(AuthenticationBackend):
    async def login(self, request: Request) -> Response:
        return RedirectResponse(SIGN_IN, status_code=302)

    async def logout(self, request: Request) -> Response:
        async with AsyncSessionLocal() as db:
            ctx = await resolve_admin(request, db)
        if ctx is not None:
            await sessions.delete_session(get_async_redis(), ctx.session.user_id, ctx.session_hash)
        return RedirectResponse("/admin/login", status_code=302)

    async def authenticate(self, request: Request) -> Response | bool:
        async with AsyncSessionLocal() as db:
            ctx = await resolve_admin(request, db)
        if ctx is None:
            return RedirectResponse(SIGN_IN, status_code=302)
        if not ctx.can("database"):
            return RedirectResponse("/admin", status_code=302)
        request.state.admin_user_id = ctx.user.id
        request.state.admin_email = ctx.user.email
        return True


def actor_of(request: Request) -> tuple[uuid.UUID | None, str | None]:
    """The admin behind a sqladmin request (set by `AdminAuth.authenticate`)."""
    return (
        getattr(request.state, "admin_user_id", None),
        getattr(request.state, "admin_email", None),
    )


async def record_action(
    request: Request,
    action: str,
    target_type: str,
    target_ids: list[str | None],
    **extra: object,
) -> None:
    """Audit a sqladmin action (approve, hide, stop…), one row per object."""
    actor_id, actor_email = actor_of(request)
    async with AsyncSessionLocal() as db:
        for target_id in target_ids:
            await audit.record(
                db,
                action,
                request=request,
                actor_user_id=actor_id,
                actor_email=actor_email,
                target_type=target_type,
                target_id=target_id,
                after=dict(extra) or None,
                commit=False,
            )
        await db.commit()


class SqladminAudit(AuditBackend):
    """Rows created, edited or deleted in sqladmin, into the admin audit log."""

    async def log(self, entry: AuditEntry, request: Request) -> None:
        actor_id, actor_email = actor_of(request)
        async with AsyncSessionLocal() as db:
            await audit.record(
                db,
                f"db.{entry.action}",
                request=request,
                actor_user_id=actor_id,
                actor_email=actor_email,
                target_type=entry.identity[:32],
                target_id=entry.pk,
                after={"changes": entry.changes} if entry.changes is not None else None,
            )


# sqladmin always adds a SessionMiddleware of its own (for its flash messages): same options as
# the site's, so it never issues a laxer cookie.
authentication_backend = AdminAuth(secret_key=settings.SECRET_KEY, **session_cookie_options())
