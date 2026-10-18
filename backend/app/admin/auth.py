"""Login of the sqladmin panel (/api/admin): the ADMIN_USER / ADMIN_PASSWORD account.

Attempts are capped per IP (`enforce_admin_login_limit`: a 429 page after that), every attempt
is logged with the client IP, and the login ends after ADMIN_SESSION_SECONDS although it lives
in the same signed cookie as the user login (see app.core.auth).
"""

import hmac
import logging

from sqladmin.authentication import AuthenticationBackend
from starlette.requests import Request

from app.core.auth import (
    ADMIN_SESSION_KEY,
    admin_login_session,
    admin_logout_session,
    is_admin_session,
    session_cookie_options,
)
from app.core.config import settings
from app.core.ratelimit import enforce_admin_login_limit

logger = logging.getLogger(__name__)


def credentials_match(given: str, expected: str) -> bool:
    """Constant-time comparison of UTF-8 bytes: `compare_digest` raises on non-ASCII strings,
    which turned a Cyrillic password into a 500."""
    return hmac.compare_digest(given.encode("utf-8"), expected.encode("utf-8"))


def _client(request: Request) -> str:
    return request.client.host if request.client else "unknown"


class AdminAuth(AuthenticationBackend):
    async def login(self, request: Request) -> bool:
        await enforce_admin_login_limit(request)
        form = await request.form()
        username = str(form.get("username") or "")
        password = str(form.get("password") or "")

        # Both checks always run, so the response time does not tell which one failed.
        user_ok = credentials_match(username, settings.ADMIN_USER)
        pass_ok = credentials_match(password, settings.ADMIN_PASSWORD)
        if user_ok and pass_ok:
            admin_login_session(request)
            logger.info("Admin panel sign-in from %s", _client(request))
            return True
        logger.warning("Failed admin panel sign-in from %s", _client(request))
        return False

    async def logout(self, request: Request) -> bool:
        admin_logout_session(request)
        return True

    async def authenticate(self, request: Request) -> bool:
        if is_admin_session(request):
            return True
        if ADMIN_SESSION_KEY in request.session:  # ended: drop the stale flag
            admin_logout_session(request)
        return False


authentication_backend = AdminAuth(secret_key=settings.SECRET_KEY, **session_cookie_options())
