"""Personal API tokens and `debatr login` (device authorization).

- GET    /api/auth/tokens                        the user's tokens (browser session)
- POST   /api/auth/tokens                        create one; the secret is in this response only
- DELETE /api/auth/tokens/{id}                   revoke one (browser session)
- GET    /api/auth/tokens/current                the token making the request (with its budget)
- DELETE /api/auth/tokens/current                a token revokes itself (`debatr logout`)
- POST   /api/auth/device                        the CLI starts a login request
- POST   /api/auth/device/token                  the CLI polls it with its secret device code
- GET    /api/auth/device/{user_code}            the browser shows the request
- POST   /api/auth/device/{user_code}/approve    …and approves it (creates a token)
- POST   /api/auth/device/{user_code}/deny       …or denies it
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, HTTPException, Request, status
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import request_api_token, require_session_user, require_user
from app.core.config import settings
from app.core.db import get_db
from app.core.ratelimit import enforce_device_code_limit, enforce_login_limit
from app.models.models import ApiToken, User
from app.schemas.auth import (
    ApiTokenCreated,
    ApiTokenOut,
    CreateApiTokenRequest,
    DeviceInfoOut,
    DevicePollOut,
    DevicePollRequest,
    DeviceStartOut,
    DeviceStartRequest,
    OkResponse,
)
from app.services import api_tokens
from app.services.credits import ZERO

router = APIRouter()

DEVICE_PATH = "/device"


def _current_token(request: Request) -> ApiToken:
    token = request_api_token(request)
    if token is None:
        raise HTTPException(status_code=400, detail="This request is not made with an API token")
    return token


async def _check_room(db: AsyncSession, user: User) -> None:
    if await api_tokens.count_active_tokens(db, user.id) >= api_tokens.MAX_TOKENS_PER_USER:
        raise HTTPException(
            status_code=409,
            detail=f"You have {api_tokens.MAX_TOKENS_PER_USER} active tokens: revoke one first",
        )


@asynccontextmanager
async def _device_store() -> AsyncIterator[None]:
    """Login requests live in Redis; without it the device flow is unavailable."""
    try:
        yield
    except RedisError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Signing in from the terminal is unavailable right now, try again later",
        ) from e


def _user_code(raw: str) -> str:
    code = api_tokens.normalize_user_code(raw)
    if code is None:
        raise HTTPException(status_code=404, detail="This code is invalid or has expired")
    return code


# --- tokens ---------------------------------------------------------------------


@router.get("/tokens", response_model=list[ApiTokenOut])
async def list_tokens(
    user: User = Depends(require_session_user), db: AsyncSession = Depends(get_db)
) -> list[ApiTokenOut]:
    tokens = (
        (
            await db.execute(
                select(ApiToken)
                .where(ApiToken.user_id == user.id)
                .order_by(ApiToken.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    spent = await api_tokens.spent_by_tokens(db, [t.id for t in tokens])
    return [api_tokens.token_out(t, spent.get(t.id, ZERO)) for t in tokens]


@router.post("/tokens", response_model=ApiTokenCreated, status_code=status.HTTP_201_CREATED)
async def create_token(
    body: CreateApiTokenRequest,
    user: User = Depends(require_session_user),
    db: AsyncSession = Depends(get_db),
) -> ApiTokenCreated:
    await _check_room(db, user)
    token, secret = await api_tokens.create_token(
        db,
        user,
        name=body.name,
        expires_in_days=body.expires_in_days,
        spend_limit_usd=body.spend_limit_usd,
    )
    return ApiTokenCreated(**api_tokens.token_out(token).model_dump(), token=secret)


@router.get("/tokens/current", response_model=ApiTokenOut)
async def current_token(
    request: Request,
    _user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> ApiTokenOut:
    """The token making this request, with what it has spent (used by `debatr whoami`)."""
    token = _current_token(request)
    spent = (await api_tokens.spent_by_tokens(db, [token.id])).get(token.id, ZERO)
    return api_tokens.token_out(token, spent)


@router.delete("/tokens/current", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_current_token(
    request: Request,
    _user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Revoke the token making this request (`debatr logout`)."""
    await db.delete(_current_token(request))
    await db.commit()


@router.delete("/tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_token(
    token_id: str,
    user: User = Depends(require_session_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    try:
        parsed = uuid.UUID(token_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail="Token not found") from e
    token = await db.get(ApiToken, parsed)
    if token is None or token.user_id != user.id:
        raise HTTPException(status_code=404, detail="Token not found")
    await db.delete(token)
    await db.commit()


# --- device flow ------------------------------------------------------------------


@router.post(
    "/device",
    response_model=DeviceStartOut,
    dependencies=[Depends(enforce_login_limit)],
)
async def start_device(body: DeviceStartRequest | None = None) -> DeviceStartOut:
    """Start `debatr login`. The CLI opens the verification page and polls `/device/token`."""
    async with _device_store():
        device_code, req = await api_tokens.start_device(
            body.client_name if body else DeviceStartRequest().client_name
        )
    verification_uri = f"{settings.SITE_URL.rstrip('/')}{DEVICE_PATH}"
    return DeviceStartOut(
        device_code=device_code,
        user_code=req.user_code,
        verification_uri=verification_uri,
        verification_uri_complete=f"{verification_uri}?code={req.user_code}",
        expires_in=api_tokens.DEVICE_TTL,
        interval=api_tokens.DEVICE_POLL_INTERVAL,
    )


@router.post("/device/token", response_model=DevicePollOut)
async def poll_device(body: DevicePollRequest, db: AsyncSession = Depends(get_db)) -> DevicePollOut:
    """`pending` until the user decides; the approved token is returned exactly once."""
    async with _device_store():
        state, secret, token_id = await api_tokens.poll_device(body.device_code)
    if state != "approved" or secret is None or token_id is None:
        return DevicePollOut(status=state if state != "approved" else "expired")
    token = await db.get(ApiToken, uuid.UUID(token_id))
    if token is None:  # revoked in the browser before the CLI picked it up
        return DevicePollOut(status="expired")
    return DevicePollOut(status="approved", token=secret, api_token=api_tokens.token_out(token))


@router.get(
    "/device/{user_code}",
    response_model=DeviceInfoOut,
    dependencies=[Depends(enforce_device_code_limit)],
)
async def device_info(user_code: str, _user: User = Depends(require_session_user)) -> DeviceInfoOut:
    code = _user_code(user_code)
    async with _device_store():
        req = await api_tokens.find_device(code)
    if req is None:
        raise HTTPException(status_code=404, detail="This code is invalid or has expired")
    return DeviceInfoOut(
        user_code=req.user_code,
        client_name=req.client_name,
        status=req.status,
        expires_at=req.expires_at,
    )


@router.post(
    "/device/{user_code}/approve",
    response_model=ApiTokenOut,
    dependencies=[Depends(enforce_device_code_limit)],
)
async def approve_device(
    user_code: str,
    body: CreateApiTokenRequest,
    user: User = Depends(require_session_user),
    db: AsyncSession = Depends(get_db),
) -> ApiTokenOut:
    code = _user_code(user_code)
    await _check_room(db, user)
    async with _device_store():
        token = await api_tokens.approve_device(
            db,
            user,
            code,
            name=body.name,
            expires_in_days=body.expires_in_days,
            spend_limit_usd=body.spend_limit_usd,
        )
    if token is None:
        raise HTTPException(
            status_code=409, detail="This request has expired or was already answered"
        )
    return api_tokens.token_out(token)


@router.post(
    "/device/{user_code}/deny",
    response_model=OkResponse,
    dependencies=[Depends(enforce_device_code_limit)],
)
async def deny_device(user_code: str, _user: User = Depends(require_session_user)) -> OkResponse:
    code = _user_code(user_code)
    async with _device_store():
        denied = await api_tokens.deny_device(code)
    if not denied:
        raise HTTPException(
            status_code=409, detail="This request has expired or was already answered"
        )
    return OkResponse()
