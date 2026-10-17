"""Login state for API requests.

Browsers sign in with the signed session cookie (SessionMiddleware), which carries the user id;
the same cookie also holds the admin panel login, under a different key. The CLI, scripts and AI
agents (MCP) send a personal API token instead: `Authorization: Bearer debatr_…`. A token acts as
its owner, except for account management (password, tokens, stored keys, payments), which needs
the browser session (`require_session_user`).
"""

import uuid
from datetime import timedelta

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.security import hash_api_token, looks_like_api_token
from app.models.models import ApiToken, User, utcnow

SESSION_USER_KEY = "uid"
ADMIN_SESSION_KEY = "token"
# `api_tokens.last_used_at` is refreshed at most this often (not on every request).
TOKEN_TOUCH_INTERVAL = timedelta(minutes=1)


def login_session(request: Request, user: User) -> None:
    request.session[SESSION_USER_KEY] = str(user.id)


def logout_session(request: Request) -> None:
    request.session.pop(SESSION_USER_KEY, None)


def is_admin_session(request: Request) -> bool:
    return request.session.get(ADMIN_SESSION_KEY) == "authenticated"


def bearer_token(request: Request) -> str | None:
    """The credentials of an `Authorization: Bearer …` header ("" when empty), or None when the
    request has no bearer header."""
    header = request.headers.get("authorization")
    if not header:
        return None
    scheme, _, credentials = header.strip().partition(" ")
    if scheme.lower() != "bearer":
        return None
    return credentials.strip()


def request_api_token(request: Request) -> ApiToken | None:
    """The API token that authenticated this request (set by `get_current_user`)."""
    token = getattr(request.state, "api_token", None)
    return token if isinstance(token, ApiToken) else None


def _token_error(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": 'Bearer realm="debatr"'},
    )


async def _user_from_api_token(request: Request, db: AsyncSession, raw: str) -> User:
    """Resolve a bearer token. A bad token is an error, never an anonymous request, so a script
    with a revoked token fails loudly instead of quietly losing access."""
    if not looks_like_api_token(raw):
        raise _token_error("Invalid API token")
    row = (
        await db.execute(
            select(ApiToken, User)
            .join(User, User.id == ApiToken.user_id)
            .where(ApiToken.token_hash == hash_api_token(raw))
        )
    ).first()
    if row is None:
        raise _token_error("Invalid or revoked API token")
    token, user = row.tuple()
    now = utcnow()
    if token.expires_at is not None and token.expires_at <= now:
        raise _token_error("This API token has expired")
    if not user.is_active:
        raise _token_error("This account is disabled")
    if token.last_used_at is None or now - token.last_used_at >= TOKEN_TOUCH_INTERVAL:
        token.last_used_at = now
        await db.commit()
    request.state.api_token = token
    return user


async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)) -> User | None:
    """The user behind the request (API token or session cookie), or None when anonymous."""
    raw_token = bearer_token(request)
    if raw_token is not None:
        return await _user_from_api_token(request, db, raw_token)
    raw = request.session.get(SESSION_USER_KEY)
    if not raw:
        return None
    try:
        user_id = uuid.UUID(str(raw))
    except ValueError:
        logout_session(request)
        return None
    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        logout_session(request)
        return None
    return user


async def require_user(user: User | None = Depends(get_current_user)) -> User:
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sign in to continue")
    return user


async def require_session_user(request: Request, user: User = Depends(require_user)) -> User:
    """Account management: only the browser session, never an API token (a leaked token must
    not be able to change the password, mint more tokens or move money)."""
    if request_api_token(request) is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="API tokens cannot manage the account: sign in on the website for this",
        )
    return user
