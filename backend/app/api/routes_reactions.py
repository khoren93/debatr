"""Views, likes and audience votes ("who argued better?") on public debates."""

from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes_debates import load_debate
from app.api.serializers import debater_models
from app.core.auth import get_current_user, require_user
from app.core.config import settings
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
from app.services.views import classify, count_view, host_of, is_bot

router = APIRouter()

#: Longest beacon body read (it is a few fields).
BEACON_MAX_BYTES = 2048


class ViewBeacon(BaseModel):
    """What the page tells about a view (frontend api/debates.countView). Sent as text/plain, so
    the browser sends it without a preflight; an empty or unreadable body is a page view with no
    known referrer."""

    place: Literal["page", "embed"] = "page"
    referrer: str = Field(
        default="", max_length=512
    )  # the referrer's host (never the whole address)
    internal: bool = False  # a navigation inside the site
    ref: str = Field(default="", max_length=32)  # the page's ?ref= ("embed": a player's link)


def _beacon(body: bytes) -> ViewBeacon:
    try:
        return ViewBeacon.model_validate_json(body[:BEACON_MAX_BYTES] or b"{}")
    except ValidationError:
        return ViewBeacon()


_BLOCKED = {
    "not_public": (404, "This debate is not public"),
    "owner": (403, "You cannot rate your own debate"),
    "not_finished": (409, "Voting opens once the debate has finished"),
}


def _raise_if_blocked(reason: str | None) -> None:
    if reason is not None:
        status, detail = _BLOCKED.get(reason, (403, "Not allowed"))
        raise HTTPException(status_code=status, detail=detail)


@router.post("/{debate_id}/view", status_code=204)
async def view_debate(
    debate_id: str,
    request: Request,
    viewer: User | None = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """The page of a public debate was shown (its beacon after hydration) or its embedded player
    started: one view per IP in six hours, never the owner's, never a bot's, kept with where it
    came from (services/views). Private debates count nothing and answer the same."""
    debate = await load_debate(db, debate_id)
    if is_bot(request.headers.get("user-agent")):
        return Response(status_code=204)
    beacon = _beacon(await request.body())
    host = host_of(beacon.referrer)
    site_host = host_of(urlsplit(settings.SITE_URL).netloc) or ""
    source = classify(
        host,
        site_host=site_host,
        site_aliases=settings.site_aliases,
        place=beacon.place,
        ref=beacon.ref,
        internal=beacon.internal,
    )
    client = request.client.host if request.client else "unknown"
    await count_view(
        db, debate, viewer, client=client, place=beacon.place, source=source, embed_host=host
    )
    return Response(status_code=204)


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
