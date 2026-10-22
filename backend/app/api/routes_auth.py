"""Accounts: register, login, profile, personal OpenRouter key, email confirmation and password
reset (services/email_check: the links we mail).

Changing the account (profile, password, stored key) needs the browser session; API tokens can
only read it (`GET /me`)."""

import hashlib
import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user, login_session, logout_session, require_session_user
from app.core.db import get_db
from app.core.ratelimit import WINDOW_SECONDS, enforce_limit, enforce_login_limit
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
    ForgotPasswordRequest,
    LoginRequest,
    OkResponse,
    RegisterRequest,
    ResetPasswordRequest,
    SetOpenRouterKeyRequest,
    UpdateProfileRequest,
    UserOut,
    VerifyEmailOut,
    VerifyEmailRequest,
)
from app.services import alerts, email_check, mail, runtime_settings
from app.services.admin import audit
from app.services.credits import apply_transaction
from app.services.official import reserved_name
from app.services.openrouter_client import openrouter_client

logger = logging.getLogger(__name__)
router = APIRouter()


def user_out(user: User) -> UserOut:
    return UserOut(
        id=str(user.id),
        email=user.email,
        display_name=user.display_name,
        avatar_seed=user.avatar_seed or "",
        official=bool(user.official),
        email_verified=user.email_verified_at is not None,
        email_required=email_check.pending(user),
        credits_usd=float(user.credits_usd or 0),
        openrouter_key_masked=mask_key(user.openrouter_key_last4),
        created_at=user.created_at,
    )


def _default_name(email: str) -> str:
    local = email.split("@", 1)[0]
    name = local.replace(".", " ").replace("_", " ").strip().title()[:100]
    return name if name and not reserved_name(name) else "Debater"


def _check_name(name: str, user: User | None = None) -> None:
    """The brand's name is the official account's alone (services/official)."""
    if reserved_name(name) and not (user is not None and user.official):
        raise HTTPException(status_code=400, detail="This name is reserved. Pick another one.")


@router.post(
    "/register",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(enforce_login_limit)],
)
async def register(
    body: RegisterRequest,
    request: Request,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> UserOut:
    levers = await runtime_settings.current()
    if not levers.registration_open:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Sign-ups are closed for now. Accounts that exist can still sign in.",
        )
    _check_name(body.display_name or "")
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
    if levers.signup_bonus_usd > 0:
        await apply_transaction(
            db,
            user.id,
            levers.signup_bonus_usd,
            "bonus",
            description="Welcome credits",
            provider="system",
            provider_ref=f"bonus:signup:{user.id}",
        )
    await db.commit()
    await db.refresh(user)
    login_session(request, user)
    logger.info("New account %s", user.email)
    letter = await email_check.mail_link("verify", user)
    if letter is not None:
        background.add_task(mail.send, letter)
    alerts.notify_soon(
        alerts.signup_alert(
            str(user.id),
            user.email,
            user.display_name,
            audit.client_ip(request),
            audit.user_agent(request),
            levers.signup_bonus_usd,
        )
    )
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


LINK_GONE = "This link has expired or was already used. Ask for a new one."


@router.post(
    "/password/forgot", response_model=OkResponse, dependencies=[Depends(enforce_login_limit)]
)
async def forgot_password(
    body: ForgotPasswordRequest,
    request: Request,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> OkResponse:
    """Mail a reset link. The same answer whether the account exists or not."""
    await enforce_limit(
        request,
        bucket="reset_mail",
        key=hashlib.sha256(body.email.encode("utf-8")).hexdigest()[:32],
        limit=email_check.MAILS_PER_HOUR,
        window_seconds=WINDOW_SECONDS,
        what="reset emails for this address",
    )
    user = await db.scalar(select(User).where(User.email == body.email))
    if user is not None and user.is_active:
        letter = await email_check.mail_link("reset", user)
        if letter is not None:
            background.add_task(mail.send, letter)
    return OkResponse()


@router.post("/password/reset", response_model=UserOut, dependencies=[Depends(enforce_login_limit)])
async def reset_password(
    body: ResetPasswordRequest, request: Request, db: AsyncSession = Depends(get_db)
) -> UserOut:
    """Set a new password from a mailed link (once), confirm the address it went to, end every
    other session and sign this browser in."""
    data = await email_check.read("reset", body.token)
    user = await db.get(User, uuid.UUID(data["uid"])) if data else None
    if user is None or not email_check.matches(data, user, epoch=True):
        raise HTTPException(status_code=400, detail=LINK_GONE)
    user.password_hash = hash_password(body.password)
    user.session_epoch += 1
    confirmed = email_check.confirm(user)
    if user.admin_role:
        # The console's password too (its second factor still guards the sign-in).
        await audit.record(db, "auth.password_reset", request=request, actor=user, commit=False)
    await db.commit()
    if confirmed:
        await email_check.publish_waiting(db, user)
    login_session(request, user)
    return user_out(user)


@router.post("/email/verify", response_model=VerifyEmailOut)
async def verify_email(
    body: VerifyEmailRequest, db: AsyncSession = Depends(get_db)
) -> VerifyEmailOut:
    """Confirm the address a mailed link went to; debates that waited for it go public. Works
    without a session (the link may be opened on another device)."""
    data = await email_check.read("verify", body.token)
    user = await db.get(User, uuid.UUID(data["uid"])) if data else None
    if user is None or not email_check.matches(data, user):
        raise HTTPException(status_code=400, detail=LINK_GONE)
    if not email_check.confirm(user):
        return VerifyEmailOut()
    await db.commit()
    return VerifyEmailOut(published=await email_check.publish_waiting(db, user))


@router.post("/email/resend", response_model=OkResponse)
async def resend_confirmation(
    request: Request,
    background: BackgroundTasks,
    user: User = Depends(require_session_user),
) -> OkResponse:
    """Mail the signed-in account a new confirmation link."""
    if user.email_verified_at is not None:
        return OkResponse()
    await enforce_limit(
        request,
        bucket="verify_mail",
        key=str(user.id),
        limit=email_check.MAILS_PER_HOUR,
        window_seconds=WINDOW_SECONDS,
        what="confirmation emails",
    )
    letter = await email_check.mail_link("verify", user)
    if letter is None:
        raise HTTPException(
            status_code=503, detail="Could not send the email now. Try again later."
        )
    background.add_task(mail.send, letter)
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
        _check_name(body.display_name, user)
        user.display_name = body.display_name.strip() or user.display_name
    if body.avatar_seed is not None:
        user.avatar_seed = body.avatar_seed.strip() or random_token(6)
    await db.commit()
    return user_out(user)


@router.post("/me/password", response_model=OkResponse)
async def change_password(
    body: ChangePasswordRequest,
    request: Request,
    user: User = Depends(require_session_user),
    db: AsyncSession = Depends(get_db),
) -> OkResponse:
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is wrong")
    user.password_hash = hash_password(body.new_password)
    # Ends every other session of this account: site cookies (core.auth compares the epoch) and
    # admin console sessions (app.admin.access); this browser stays signed in.
    user.session_epoch += 1
    await db.commit()
    login_session(request, user)
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
