"""Likes and audience votes on public debates.

Only signed-in users other than the owner can like or vote, and only on public debates
(votes also need a finished debate with at least two debaters). `debates.likes_count` and
`debates.votes_count` are kept in step with the rows using atomic increments.
"""

import uuid

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.serializers import debater_models, is_owner
from app.models.models import Debate, DebateLike, DebateVote, User, utcnow
from app.schemas.schemas import AudienceOut, EngagementOut


def like_blocker(debate: Debate, viewer: User | None) -> str | None:
    """Why the viewer cannot like this debate, or None when they can."""
    if not debate.is_public:
        return "not_public"
    if viewer is None:
        return "sign_in"
    if is_owner(debate, viewer):
        return "owner"
    return None


def vote_blocker(debate: Debate, viewer: User | None) -> str | None:
    """Why the viewer cannot vote on this debate, or None when they can."""
    if not debate.is_public:
        return "not_public"
    if debate.status != "completed" or len(debater_models(debate)) < 2:
        return "not_finished"
    if viewer is None:
        return "sign_in"
    if is_owner(debate, viewer):
        return "owner"
    return None


async def vote_counts(db: AsyncSession, debate: Debate) -> dict[str, int]:
    rows = await db.execute(
        select(DebateVote.participant_id, func.count())
        .where(DebateVote.debate_id == debate.id)
        .group_by(DebateVote.participant_id)
    )
    known = debater_models(debate)
    return {pid: int(n) for pid, n in rows.all() if pid in known}


async def audience_out(db: AsyncSession, debate: Debate, viewer: User | None) -> AudienceOut:
    counts = await vote_counts(db, debate)
    my_vote = None
    if viewer is not None:
        my_vote = await db.scalar(
            select(DebateVote.participant_id).where(
                DebateVote.debate_id == debate.id, DebateVote.user_id == viewer.id
            )
        )
    reason = vote_blocker(debate, viewer)
    return AudienceOut(
        total=sum(counts.values()),
        counts=counts,
        my_vote=my_vote,
        can_vote=reason is None,
        reason=reason,
    )


async def engagement_out(db: AsyncSession, debate: Debate, viewer: User | None) -> EngagementOut:
    liked = False
    if viewer is not None:
        liked = (
            await db.scalar(
                select(DebateLike.user_id).where(
                    DebateLike.debate_id == debate.id, DebateLike.user_id == viewer.id
                )
            )
            is not None
        )
    return EngagementOut(
        likes=debate.likes_count or 0,
        liked=liked,
        can_like=like_blocker(debate, viewer) is None,
        audience=await audience_out(db, debate, viewer),
    )


async def _bump(db: AsyncSession, debate: Debate, column: str, delta: int) -> int:
    counter = getattr(Debate, column)
    value = await db.scalar(
        update(Debate)
        .where(Debate.id == debate.id)
        .values({column: func.greatest(counter + delta, 0)})
        .returning(counter)
    )
    return int(value or 0)


async def set_like(db: AsyncSession, debate: Debate, user: User, liked: bool) -> int:
    """Like or unlike; returns the new like count. Repeating the same call is a no-op."""
    if liked:
        changed = await db.scalar(
            insert(DebateLike)
            .values(user_id=user.id, debate_id=debate.id, created_at=utcnow())
            .on_conflict_do_nothing()
            .returning(DebateLike.user_id)
        )
    else:
        changed = await db.scalar(
            delete(DebateLike)
            .where(DebateLike.debate_id == debate.id, DebateLike.user_id == user.id)
            .returning(DebateLike.user_id)
        )
    count = (
        await _bump(db, debate, "likes_count", 1 if liked else -1)
        if changed is not None
        else int(debate.likes_count or 0)
    )
    await db.commit()
    return count


async def cast_vote(db: AsyncSession, debate: Debate, user: User, participant_id: str) -> None:
    """Vote for a debater, or move an earlier vote to another one."""
    now = utcnow()
    inserted = await db.scalar(
        insert(DebateVote)
        .values(
            user_id=user.id,
            debate_id=debate.id,
            participant_id=participant_id,
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_nothing()
        .returning(DebateVote.user_id)
    )
    if inserted is not None:
        await _bump(db, debate, "votes_count", 1)
    else:
        await db.execute(
            update(DebateVote)
            .where(DebateVote.debate_id == debate.id, DebateVote.user_id == user.id)
            .values(participant_id=participant_id, updated_at=now)
        )
    await db.commit()


async def retract_vote(db: AsyncSession, debate: Debate, user: User) -> None:
    removed = await db.scalar(
        delete(DebateVote)
        .where(DebateVote.debate_id == debate.id, DebateVote.user_id == user.id)
        .returning(DebateVote.user_id)
    )
    if removed is not None:
        await _bump(db, debate, "votes_count", -1)
    await db.commit()


async def recount(db: AsyncSession, debate_id: uuid.UUID, *, commit: bool = True) -> None:
    """Rebuild both counters from the rows (after rows were removed outside the API)."""
    likes = select(func.count()).where(DebateLike.debate_id == debate_id).scalar_subquery()
    votes = select(func.count()).where(DebateVote.debate_id == debate_id).scalar_subquery()
    await db.execute(
        update(Debate).where(Debate.id == debate_id).values(likes_count=likes, votes_count=votes)
    )
    if commit:
        await db.commit()
