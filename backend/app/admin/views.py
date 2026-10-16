from typing import Any

from sqladmin import ModelView
from starlette.requests import Request

from app.core.db import AsyncSessionLocal
from app.models.models import (
    CreditTransaction,
    Debate,
    DebateLike,
    DebateParticipant,
    DebateVote,
    Session,
    Turn,
    User,
)
from app.services.engagement import recount


class UserAdmin(ModelView, model=User):
    column_list = [
        User.id,
        User.email,
        User.display_name,
        User.plan,
        User.credits_usd,
        User.is_active,
        User.created_at,
        User.last_login_at,
    ]
    column_searchable_list = [User.email, User.display_name]
    column_sortable_list = [User.created_at, User.credits_usd, User.last_login_at]
    column_default_sort = (User.created_at, True)
    column_details_exclude_list = [User.password_hash, User.openrouter_key_enc]
    form_excluded_columns = [
        User.password_hash,
        User.openrouter_key_enc,
        User.debates,
        User.transactions,
    ]
    can_create = False
    can_delete = True
    name = "User"
    name_plural = "Users"
    icon = "fa-solid fa-user"


class CreditTransactionAdmin(ModelView, model=CreditTransaction):
    column_list = [
        CreditTransaction.id,
        CreditTransaction.user_id,
        CreditTransaction.kind,
        CreditTransaction.amount_usd,
        CreditTransaction.balance_after_usd,
        CreditTransaction.description,
        CreditTransaction.provider,
        CreditTransaction.created_at,
    ]
    column_searchable_list = [CreditTransaction.kind, CreditTransaction.provider_ref]
    column_sortable_list = [CreditTransaction.created_at, CreditTransaction.amount_usd]
    column_default_sort = (CreditTransaction.created_at, True)
    can_create = False
    can_edit = False
    can_delete = False
    name = "Credit transaction"
    name_plural = "Credit transactions"
    icon = "fa-solid fa-coins"


class DebateAdmin(ModelView, model=Debate):
    column_list = [
        Debate.id,
        Debate.title,
        Debate.status,
        Debate.user_id,
        Debate.is_public,
        Debate.media_status,
        Debate.views,
        Debate.likes_count,
        Debate.votes_count,
        Debate.created_at,
        Debate.ended_at,
    ]
    column_searchable_list = [Debate.id, Debate.title, Debate.status, Debate.slug]
    column_sortable_list = [
        Debate.created_at,
        Debate.status,
        Debate.views,
        Debate.likes_count,
        Debate.votes_count,
    ]
    column_default_sort = (Debate.created_at, True)
    can_delete = True
    name = "Debate"
    name_plural = "Debates"
    icon = "fa-solid fa-comments"


class _RecountOnDelete:
    """Deleting likes/votes here keeps the denormalized counters on the debate in step."""

    async def after_model_delete(self, model: Any, request: Request) -> None:
        async with AsyncSessionLocal() as db:
            await recount(db, model.debate_id)


class LikeAdmin(_RecountOnDelete, ModelView, model=DebateLike):
    column_list = [DebateLike.debate_id, DebateLike.user_id, DebateLike.created_at]
    column_sortable_list = [DebateLike.created_at]
    column_default_sort = (DebateLike.created_at, True)
    can_create = False
    can_edit = False
    can_delete = True
    name = "Like"
    name_plural = "Likes"
    icon = "fa-solid fa-heart"


class VoteAdmin(_RecountOnDelete, ModelView, model=DebateVote):
    column_list = [
        DebateVote.debate_id,
        DebateVote.user_id,
        DebateVote.participant_id,
        DebateVote.updated_at,
    ]
    column_sortable_list = [DebateVote.created_at, DebateVote.updated_at]
    column_default_sort = (DebateVote.updated_at, True)
    can_create = False
    can_edit = False
    can_delete = True
    name = "Vote"
    name_plural = "Votes"
    icon = "fa-solid fa-check-to-slot"


class ParticipantAdmin(ModelView, model=DebateParticipant):
    column_list = [
        DebateParticipant.id,
        DebateParticipant.debate_id,
        DebateParticipant.role,
        DebateParticipant.persona_name,
        DebateParticipant.model_id,
    ]
    can_delete = False
    name = "Participant"
    name_plural = "Participants"
    icon = "fa-solid fa-users"


class TurnAdmin(ModelView, model=Turn):
    column_list = [
        Turn.id,
        Turn.debate_id,
        Turn.seq_index,
        Turn.turn_type,
        Turn.speaker_name,
        Turn.model_used,
        Turn.created_at,
    ]
    column_sortable_list = [Turn.created_at, Turn.seq_index]
    can_delete = False
    name = "Turn"
    name_plural = "Turns"
    icon = "fa-solid fa-microphone"


class SessionAdmin(ModelView, model=Session):
    column_list = [Session.id, Session.created_at, Session.last_seen_at]
    can_delete = False
    name = "Legacy session"
    name_plural = "Legacy sessions"
    icon = "fa-solid fa-clock-rotate-left"
