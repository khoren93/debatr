"""Sign-in with Google (services/google_auth): `/api/auth/google/*`.

- `GET /google/start?next=&link=` (a navigation from the site's own page): a new flow, its
  state in a short SameSite=Lax cookie (it has to come back with Google's cross-site redirect),
  then Google's account chooser. `link=true` connects Google to the signed-in account.
- `GET /google/callback`: Google sends the browser back here. The answer is a small page that
  moves on to the site by itself: the session cookie is SameSite=Strict, and a redirect at the
  end of a cross-site arrival would be cross-site too (the cookie would stay home, the page would
  render signed out); a navigation the page starts is same-site. Problems land on
  `/login?error=google_<code>` (to link: `/account?tab=security&google=<code>`).
- `DELETE /google`: disconnect Google, unless it is the account's only way in.
"""

import hmac
import json
import logging
import uuid
from html import escape
from typing import Any
from urllib.parse import quote, urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes_auth import account_out, create_account, default_name
from app.core.auth import (
    get_current_user,
    login_session,
    request_api_token,
    require_session_user,
)
from app.core.config import settings
from app.core.db import get_db
from app.core.ratelimit import enforce_login_limit
from app.models.models import User, UserIdentity, utcnow
from app.schemas.auth import UserOut
from app.services import alerts, email_check, google_auth, runtime_settings
from app.services.admin import audit
from app.services.google_auth import PROVIDER, Flow, GoogleAccount
from app.services.official import reserved_name

logger = logging.getLogger(__name__)
router = APIRouter()

COOKIE_PATH = "/api/auth/google"
DEFAULT_NEXT = "/library"
SECURITY_TAB = "/account?tab=security"
AUTH_PAGES = ("/login", "/register")


def _secure(request: Request) -> bool:
    return settings.is_production or request.url.scheme == "https"


def state_cookie(request: Request) -> str:
    return "__Secure-google_state" if _secure(request) else "google_state"


def safe_next(raw: str | None) -> str | None:
    """A path on this site to land on (never another host, a scheme or the sign-in pages)."""
    if not raw or len(raw) > 500 or not raw.startswith("/") or raw.startswith(("//", "/\\")):
        return None
    if any(ord(ch) < 32 for ch in raw) or raw.split("?")[0] in AUTH_PAGES:
        return None
    return raw


def failure_target(code: str, mode: str = "login", next_path: str | None = None) -> str:
    """Where a sign-in that did not go through lands (the page explains `code`)."""
    if mode == "link":
        return f"{SECURITY_TAB}&google={code}"
    query = {"error": f"google_{code}"}
    if next_path:
        query["next"] = next_path
    return f"/login?{urlencode(query, quote_via=quote)}"


def hop(target: str) -> HTMLResponse:
    """A page that goes on to `target` (a path of the site) by itself: script, meta refresh or
    the link (see the module docstring for why not a redirect)."""
    href = escape(target, quote=True)
    script = json.dumps(target).replace("<", "\\u003c")
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<meta name="robots" content="noindex"><meta http-equiv="refresh" content="0;url={href}">
<title>Signing in…</title>
<style>html{{background:#0a0b0f;color:#8b90a0;font:14px/1.5 system-ui,sans-serif}}
body{{display:grid;place-items:center;min-height:90vh;margin:0}}a{{color:#d9ff3d}}</style>
</head><body><p>Signing in… <a href="{href}">Continue</a></p>
<script>location.replace({script})</script></body></html>"""
    return HTMLResponse(
        page, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}
    )


def _finish(request: Request, target: str) -> HTMLResponse:
    response = hop(target)
    response.delete_cookie(
        state_cookie(request), path=COOKIE_PATH, secure=_secure(request), httponly=True
    )
    return response


@router.get("/google/start", dependencies=[Depends(enforce_login_limit)])
async def google_start(
    request: Request,
    next: str | None = None,
    link: bool = False,
    user: User | None = Depends(get_current_user),
) -> Response:
    if not google_auth.enabled():
        return RedirectResponse("/login?error=google_off", status_code=status.HTTP_302_FOUND)
    if link and (user is None or request_api_token(request) is not None):
        return RedirectResponse(
            f"/login?next={quote(SECURITY_TAB, safe='')}", status_code=status.HTTP_302_FOUND
        )
    target = SECURITY_TAB if link else safe_next(next)
    try:
        state, url = await google_auth.begin(
            "link" if link else "login", next_path=target, user=user if link else None
        )
    except RedisError:
        logger.warning("Could not store a Google sign-in flow")
        target = failure_target("failed", "link" if link else "login", target)
        return RedirectResponse(target, status_code=status.HTTP_302_FOUND)
    response = RedirectResponse(url, status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        state_cookie(request),
        state,
        max_age=google_auth.FLOW_SECONDS,
        path=COOKIE_PATH,
        secure=_secure(request),
        httponly=True,
        samesite="lax",
    )
    return response


@router.get("/google/callback", response_class=HTMLResponse)
async def google_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    cookie = request.cookies.get(state_cookie(request)) or ""
    flow = None
    if state and cookie and hmac.compare_digest(state.encode(), cookie.encode()):
        try:
            flow = await google_auth.take(state)
        except RedisError:
            logger.warning("Could not read a Google sign-in flow")
    if flow is None:
        return _finish(request, failure_target("expired"))
    if error or not code:
        problem = "cancelled" if error else "failed"
        return _finish(request, failure_target(problem, flow.mode, flow.next))
    try:
        account = await google_auth.exchange(code, flow)
    except (google_auth.GoogleError, httpx.HTTPError, ValueError) as e:
        logger.warning("Google sign-in failed: %s", e)
        return _finish(request, failure_target("failed", flow.mode, flow.next))
    if flow.mode == "link":
        return await _link(request, db, flow, account)
    return await _sign_in(request, db, flow, account)


async def _tied_user(db: AsyncSession, account: GoogleAccount) -> tuple[User | None, Any]:
    identity = await db.scalar(
        select(UserIdentity).where(
            UserIdentity.provider == PROVIDER, UserIdentity.subject == account.subject
        )
    )
    user = await db.get(User, identity.user_id) if identity is not None else None
    return user, identity


def _identity(user: User, account: GoogleAccount) -> UserIdentity:
    now = utcnow()
    return UserIdentity(
        user_id=user.id,
        provider=PROVIDER,
        subject=account.subject,
        email=account.email,
        created_at=now,
        last_used_at=now,
    )


async def _sign_in(
    request: Request, db: AsyncSession, flow: Flow, account: GoogleAccount
) -> HTMLResponse:
    tied, identity = await _tied_user(db, account)
    same_email = (
        await db.scalar(select(User).where(User.email == account.email)) if tied is None else None
    )
    levers = await runtime_settings.current()
    decision = google_auth.decide(
        account, tied=tied, same_email=same_email, registration_open=levers.registration_open
    )
    created = False
    if decision.action == "sign_in" and tied is not None and identity is not None:
        user = tied
        identity.email, identity.last_used_at = account.email, utcnow()
    elif decision.action == "join" and same_email is not None:
        user = same_email
        db.add(_identity(user, account))
    elif decision.action == "create":
        name = account.name if account.name and not reserved_name(account.name) else ""
        user = await create_account(
            db,
            email=account.email,
            display_name=name or default_name(account.email),
            password_hash=None,
            bonus_usd=levers.signup_bonus_usd,
            verified=True,
        )
        db.add(_identity(user, account))
        created = True
    else:
        return _finish(request, failure_target(decision.error or "failed", flow.mode, flow.next))
    user.last_login_at = utcnow()
    confirmed = account.email == user.email and account.email_verified and email_check.confirm(user)
    await db.commit()
    if confirmed:
        await email_check.publish_waiting(db, user)
    login_session(request, user)
    if created:
        logger.info("New account %s (Google)", user.email)
        alerts.notify_soon(
            alerts.signup_alert(
                str(user.id),
                user.email,
                user.display_name,
                audit.client_ip(request),
                audit.user_agent(request),
                levers.signup_bonus_usd,
                via="Google",
            )
        )
    return _finish(request, flow.next or DEFAULT_NEXT)


async def _link(
    request: Request, db: AsyncSession, flow: Flow, account: GoogleAccount
) -> HTMLResponse:
    uid = _uuid(flow.uid)
    user = await db.get(User, uid) if uid is not None else None
    tied, _ = await _tied_user(db, account)
    current = (
        await db.scalar(
            select(UserIdentity).where(
                UserIdentity.user_id == user.id, UserIdentity.provider == PROVIDER
            )
        )
        if user is not None
        else None
    )
    decision = google_auth.decide_link(flow, user=user, tied=tied, current=current)
    if decision.action == "refuse" or user is None:
        return _finish(request, failure_target(decision.error or "expired", "link"))
    if decision.action == "join":
        db.add(_identity(user, account))
    confirmed = account.email == user.email and account.email_verified and email_check.confirm(user)
    await db.commit()
    if confirmed:
        await email_check.publish_waiting(db, user)
    # Signed in again: the arrival from Google came without the Strict session cookie.
    login_session(request, user)
    return _finish(request, f"{SECURITY_TAB}&google=linked")


def _uuid(raw: str | None) -> uuid.UUID | None:
    try:
        return uuid.UUID(raw) if raw else None
    except ValueError:
        return None


@router.delete("/google", response_model=UserOut)
async def disconnect_google(
    user: User = Depends(require_session_user), db: AsyncSession = Depends(get_db)
) -> UserOut:
    """Disconnect Google; refused while it is the account's only way to sign in."""
    identity = await db.scalar(
        select(UserIdentity).where(
            UserIdentity.user_id == user.id, UserIdentity.provider == PROVIDER
        )
    )
    if identity is not None:
        if not user.password_hash:
            raise HTTPException(
                status_code=409,
                detail="Set a password first: Google is your only way to sign in.",
            )
        await db.delete(identity)
        await db.commit()
    return await account_out(db, user)
