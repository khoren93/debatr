"""Likes and audience votes ("who argued better?") on public debates."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes_debates import load_debate
from app.api.serializers import debater_models
from app.core.auth import require_user
from app.core.db import get_db
from app.models.models import User
from app.schemas.schemas import AudienceOut, LikeOut, VoteRequest
from app.services.engagement import (
    audience_out,
    cast_vote,
    like_blocker,
    retract_vote,
    set_like,
    vote_blocker,
)

router = APIRouter()

_BLOCKED = {
    "not_public": (404, "This debate is not public"),
    "owner": (403, "You cannot rate your own debate"),
    "not_finished": (409, "Voting opens once the debate has finished"),
}


def _raise_if_blocked(reason: str | None) -> None:
    if reason is not None:
        status, detail = _BLOCKED.get(reason, (403, "Not allowed"))
        raise HTTPException(status_code=status, detail=detail)


@router.put("/{debate_id}/like", response_model=LikeOut)
async def like_debate(
    debate_id: str, user: User = Depends(require_user), db: AsyncSession = Depends(get_db)
) -> LikeOut:
    debate = await load_debate(db, debate_id)
    _raise_if_blocked(like_blocker(debate, user))
    return LikeOut(liked=True, likes=await set_like(db, debate, user, True))


@router.delete("/{debate_id}/like", response_model=LikeOut)
async def unlike_debate(
    debate_id: str, user: User = Depends(require_user), db: AsyncSession = Depends(get_db)
) -> LikeOut:
    debate = await load_debate(db, debate_id)
    _raise_if_blocked(like_blocker(debate, user))
    return LikeOut(liked=False, likes=await set_like(db, debate, user, False))


@router.put("/{debate_id}/vote", response_model=AudienceOut)
async def vote(
    debate_id: str,
    body: VoteRequest,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> AudienceOut:
    """Vote for the debater who argued better (a second call moves the vote)."""
    debate = await load_debate(db, debate_id)
    _raise_if_blocked(vote_blocker(debate, user))
    if body.participant_id not in debater_models(debate):
        raise HTTPException(status_code=422, detail="Unknown debater")
    await cast_vote(db, debate, user, body.participant_id)
    return await audience_out(db, debate, user)


@router.delete("/{debate_id}/vote", response_model=AudienceOut)
async def unvote(
    debate_id: str, user: User = Depends(require_user), db: AsyncSession = Depends(get_db)
) -> AudienceOut:
    debate = await load_debate(db, debate_id)
    _raise_if_blocked(vote_blocker(debate, user))
    await retract_vote(db, debate, user)
    return await audience_out(db, debate, user)
