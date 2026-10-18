"""Accounts: register, login, profile, personal OpenRouter key.

Changing the account (profile, password, stored key) needs the browser session; API tokens can
only read it (`GET /me`)."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user, login_session, logout_session, require_session_user
from app.core.config import settings
from app.core.db import get_db
from app.core.ratelimit import enforce_login_limit
from app.core.security import (
    encrypt_secret,
    hash_password,
    key_last4,
    mask_key,
    random_token,
    verify_password,
)
from app.models.models import User, utcnow
from app.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    OkResponse,
    RegisterRequest,
    SetOpenRouterKeyRequest,
    UpdateProfileRequest,
    UserOut,
)
from app.services.credits import apply_transaction
from app.services.openrouter_client import openrouter_client

logger = logging.getLogger(__name__)
router = APIRouter()


def user_out(user: User) -> UserOut:
    return UserOut(
        id=str(user.id),
        email=user.email,
        display_name=user.display_name,
        avatar_seed=user.avatar_seed or "",
        credits_usd=float(user.credits_usd or 0),
        openrouter_key_masked=mask_key(user.openrouter_key_last4),
        created_at=user.created_at,
    )


def _default_name(email: str) -> str:
    local = email.split("@", 1)[0]
    return local.replace(".", " ").replace("_", " ").strip().title()[:100] or "Debater"


@router.post(
    "/register",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(enforce_login_limit)],
)
async def register(
    body: RegisterRequest, request: Request, db: AsyncSession = Depends(get_db)
) -> UserOut:
    exists = await db.scalar(select(User.id).where(User.email == body.email))
    if exists is not None:
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    user = User(
        email=body.email,
        password_hash=hash_password(body.password),
        display_name=(body.display_name or "").strip() or _default_name(body.email),
        avatar_seed=random_token(6),
        last_login_at=utcnow(),
    )
    db.add(user)
    await db.flush()
    if settings.SIGNUP_BONUS_USD > 0:
        await apply_transaction(
            db,
            user.id,
            settings.SIGNUP_BONUS_USD,
            "bonus",
            description="Welcome credits",
            provider="system",
            provider_ref=f"bonus:signup:{user.id}",
        )
    await db.commit()
    await db.refresh(user)
    login_session(request, user)
    logger.info("New account %s", user.email)
    return user_out(user)


@router.post("/login", response_model=UserOut, dependencies=[Depends(enforce_login_limit)])
async def login(
    body: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)
) -> UserOut:
    user = await db.scalar(select(User).where(User.email == body.email))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Wrong email or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="This account is disabled")
    user.last_login_at = utcnow()
    await db.commit()
    login_session(request, user)
    return user_out(user)


@router.post("/logout", response_model=OkResponse)
async def logout(request: Request) -> OkResponse:
    logout_session(request)
    return OkResponse()


@router.get("/me", response_model=UserOut | None)
async def me(user: User | None = Depends(get_current_user)) -> UserOut | None:
    """The signed-in user, or null."""
    return user_out(user) if user else None


@router.patch("/me", response_model=UserOut)
async def update_profile(
    body: UpdateProfileRequest,
    user: User = Depends(require_session_user),
    db: AsyncSession = Depends(get_db),
) -> UserOut:
    if body.display_name is not None:
        user.display_name = body.display_name.strip() or user.display_name
    if body.avatar_seed is not None:
        user.avatar_seed = body.avatar_seed.strip() or random_token(6)
    await db.commit()
    return user_out(user)


@router.post("/me/password", response_model=OkResponse)
async def change_password(
    body: ChangePasswordRequest,
    user: User = Depends(require_session_user),
    db: AsyncSession = Depends(get_db),
) -> OkResponse:
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is wrong")
    user.password_hash = hash_password(body.new_password)
    # Ends the admin console sessions of this account (app.admin.access compares the epoch).
    user.session_epoch += 1
    await db.commit()
    return OkResponse()


@router.put("/me/openrouter-key", response_model=UserOut)
async def set_openrouter_key(
    body: SetOpenRouterKeyRequest,
    user: User = Depends(require_session_user),
    db: AsyncSession = Depends(get_db),
) -> UserOut:
    """Store a personal OpenRouter key (encrypted). Paid models then run on it, not on credits."""
    _credits, error = await openrouter_client.get_credits(api_key=body.key)
    if error:
        raise HTTPException(status_code=400, detail=f"OpenRouter rejected the key: {error}")
    user.openrouter_key_enc = encrypt_secret(body.key)
    user.openrouter_key_last4 = key_last4(body.key)
    await db.commit()
    return user_out(user)


@router.delete("/me/openrouter-key", response_model=UserOut)
async def remove_openrouter_key(
    user: User = Depends(require_session_user), db: AsyncSession = Depends(get_db)
) -> UserOut:
    user.openrouter_key_enc = None
    user.openrouter_key_last4 = None
    await db.commit()
    return user_out(user)
