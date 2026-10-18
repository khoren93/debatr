import uuid
from typing import Any

from sqladmin import ModelView, action
from sqladmin.filters import BooleanFilter, StaticValuesFilter
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import RedirectResponse

from app.admin.auth import record_action
from app.core.db import AsyncSessionLocal
from app.models.models import (
    AdminAuditLog,
    ApiToken,
    CreditTransaction,
    Debate,
    DebateLike,
    DebateParticipant,
    DebateVote,
    Session,
    TrendingBatch,
    TrendingTopic,
    Turn,
    User,
)
from app.services.debate_control import ACTIVE_STATUSES, stop_debate
from app.services.engagement import recount
from app.services.moderation import mark_admin_decision, publish_async, wants_public
from app.services.queue_manager import enqueue_trending_refresh
from app.services.trending import TOPIC_CATEGORIES


class UserAdmin(ModelView, model=User):
    """Accounts. The details page and the form are allowlists, so a new column (a secret one
    included) never shows up there by itself. The balance changes only through the ledger
    (`python -m app.manage credits`); the email is the login, which the form would not validate
    (lowercase, unique), so it is not editable here. Deleting is off: the
    debates of a deleted owner would become ownerless rows that anyone with the link may read
    (`serializers.can_view`); disable the account instead."""

    column_list = [
        User.id,
        User.email,
        User.display_name,
        User.credits_usd,
        User.is_active,
        User.created_at,
        User.last_login_at,
    ]
    column_searchable_list = [User.email, User.display_name]
    column_sortable_list = [User.created_at, User.credits_usd, User.last_login_at]
    column_default_sort = (User.created_at, True)
    column_details_list = [
        User.id,
        User.email,
        User.display_name,
        User.credits_usd,
        User.openrouter_key_last4,
        User.is_active,
        User.created_at,
        User.last_login_at,
    ]
    form_columns = [User.display_name, User.is_active]
    can_create = False
    can_delete = False
    name = "User"
    name_plural = "Users"
    icon = "fa-solid fa-user"


class ApiTokenAdmin(ModelView, model=ApiToken):
    """Personal API tokens (CLI / agents). Only the hash is stored; deleting revokes."""

    column_list = [
        ApiToken.id,
        ApiToken.user_id,
        ApiToken.name,
        ApiToken.token_last4,
        ApiToken.spend_limit_usd,
        ApiToken.created_at,
        ApiToken.last_used_at,
        ApiToken.expires_at,
    ]
    column_searchable_list = [ApiToken.name]
    column_sortable_list = [ApiToken.created_at, ApiToken.last_used_at]
    column_default_sort = (ApiToken.created_at, True)
    column_details_exclude_list = [ApiToken.token_hash]
    can_create = False
    can_edit = False
    can_delete = True
    name = "API token"
    name_plural = "API tokens"
    icon = "fa-solid fa-key"


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
        Debate.moderation_status,
        Debate.media_status,
        Debate.views,
        Debate.likes_count,
        Debate.votes_count,
        Debate.created_at,
        Debate.ended_at,
    ]
    column_searchable_list = [Debate.id, Debate.title, Debate.status, Debate.slug]
    column_filters = [
        StaticValuesFilter(
            Debate.moderation_status,
            values=[(s, s) for s in ("flagged", "approved", "rejected", "none")],
            title="Moderation",
        ),
        BooleanFilter(Debate.is_public, title="Public"),
    ]
    column_sortable_list = [
        Debate.created_at,
        Debate.status,
        Debate.views,
        Debate.likes_count,
        Debate.votes_count,
    ]
    column_default_sort = (Debate.created_at, True)
    # Status, publishing, moderation, owner and totals follow their own rules (Stop, the
    # moderation actions, the ledger), so the form edits only the labels.
    form_columns = [Debate.title, Debate.category]
    can_delete = True
    name = "Debate"
    name_plural = "Debates"
    icon = "fa-solid fa-comments"

    async def _moderate(self, request: Request, *, approved: bool) -> RedirectResponse:
        """Approve (and publish when the owner asked for the gallery) or reject."""
        pks = _pks(request)
        async with AsyncSessionLocal() as db:
            for pk in pks:
                debate = await db.get(Debate, uuid.UUID(pk))
                if debate is None:
                    continue
                mark_admin_decision(debate, approved=approved)
                if approved and debate.status == "completed" and wants_public(debate):
                    await publish_async(db, debate)
            await db.commit()
        verdict = "moderation.approved" if approved else "moderation.rejected"
        await record_action(request, verdict, "debate", list(pks))
        return _back(request, self)

    @action(
        name="approve",
        label="Approve for gallery",
        confirmation_message="Approve these debates? Ones whose owner wants them public go live.",
    )
    async def approve(self, request: Request) -> RedirectResponse:
        return await self._moderate(request, approved=True)

    @action(
        name="reject",
        label="Reject",
        confirmation_message="Reject these debates? They are removed from the gallery.",
    )
    async def reject(self, request: Request) -> RedirectResponse:
        return await self._moderate(request, approved=False)

    @action(
        name="stop",
        label="Stop",
        confirmation_message="Stop these debates? A running turn ends early.",
    )
    async def stop(self, request: Request) -> RedirectResponse:
        stopped: list[str | None] = []
        async with AsyncSessionLocal() as db:
            for pk in _pks(request):
                debate = await db.get(Debate, uuid.UUID(pk))
                if debate is not None and debate.status in ACTIVE_STATUSES:
                    await stop_debate(db, debate)
                    stopped.append(pk)
        await record_action(request, "debate.stopped", "debate", stopped)
        return _back(request, self)


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
    can_edit = False  # the lineup feeds the leaderboard
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
    can_edit = False  # what a model said is never rewritten
    can_delete = False
    name = "Turn"
    name_plural = "Turns"
    icon = "fa-solid fa-microphone"


class SessionAdmin(ModelView, model=Session):
    column_list = [Session.id, Session.created_at, Session.last_seen_at]
    can_edit = False
    can_delete = False
    name = "Legacy session"
    name_plural = "Legacy sessions"
    icon = "fa-solid fa-clock-rotate-left"


def _pks(request: Request) -> list[str]:
    return [pk for pk in request.query_params.get("pks", "").split(",") if pk]


def _back(request: Request, view: ModelView) -> RedirectResponse:
    referer = request.headers.get("referer")
    return RedirectResponse(referer or request.url_for("admin:list", identity=view.identity))


class TrendingBatchAdmin(ModelView, model=TrendingBatch):
    """Trending-topic refreshes; the newest batch is what the wizard shows."""

    column_list = [
        TrendingBatch.created_at,
        TrendingBatch.model,
        TrendingBatch.topic_count,
        TrendingBatch.cost_usd,
        TrendingBatch.id,
    ]
    column_details_exclude_list = [TrendingBatch.topics]
    column_sortable_list = [TrendingBatch.created_at, TrendingBatch.cost_usd]
    column_default_sort = (TrendingBatch.created_at, True)
    can_create = False
    can_edit = False
    can_delete = True
    name = "Trending batch"
    name_plural = "Trending batches"
    icon = "fa-solid fa-newspaper"

    @action(
        name="build_now",
        label="Build a new batch now",
        confirmation_message="Fetch the news and build a new batch now (takes about a minute)?",
    )
    async def build_now(self, request: Request) -> RedirectResponse:
        await run_in_threadpool(enqueue_trending_refresh, True)
        await record_action(request, "trending.build_requested", "trending_batch", [None])
        return _back(request, self)


class TrendingTopicAdmin(ModelView, model=TrendingTopic):
    """Topics of every batch. Hide one to take it off the site at once."""

    column_list = [
        TrendingTopic.rank,
        TrendingTopic.question,
        TrendingTopic.category,
        TrendingTopic.heat,
        TrendingTopic.outlets,
        TrendingTopic.is_hidden,
        TrendingTopic.created_at,
    ]
    column_searchable_list = [TrendingTopic.question, TrendingTopic.label]
    column_filters = [
        StaticValuesFilter(
            TrendingTopic.category, values=[(c, c) for c in TOPIC_CATEGORIES], title="Category"
        ),
        BooleanFilter(TrendingTopic.is_hidden, title="Hidden"),
    ]
    column_sortable_list = [TrendingTopic.created_at, TrendingTopic.rank, TrendingTopic.heat]
    column_default_sort = [(TrendingTopic.created_at, True), (TrendingTopic.rank, False)]
    form_excluded_columns = [TrendingTopic.batch, TrendingTopic.created_at]
    can_create = False
    can_delete = True
    name = "Trending topic"
    name_plural = "Trending topics"
    icon = "fa-solid fa-fire"

    async def _set_hidden(self, request: Request, hidden: bool) -> RedirectResponse:
        pks = _pks(request)
        async with AsyncSessionLocal() as db:
            for pk in pks:
                topic = await db.get(TrendingTopic, uuid.UUID(pk))
                if topic is not None:
                    topic.is_hidden = hidden
            await db.commit()
        action_name = "trending.hidden" if hidden else "trending.shown"
        await record_action(request, action_name, "trending_topic", list(pks))
        return _back(request, self)

    @action(name="hide", label="Hide from the site")
    async def hide(self, request: Request) -> RedirectResponse:
        return await self._set_hidden(request, True)

    @action(name="show", label="Show again")
    async def show(self, request: Request) -> RedirectResponse:
        return await self._set_hidden(request, False)


class AuditLogAdmin(ModelView, model=AdminAuditLog):
    """The admin audit log, read-only (the table itself refuses changes)."""

    column_list = [
        AdminAuditLog.created_at,
        AdminAuditLog.action,
        AdminAuditLog.ok,
        AdminAuditLog.actor_email,
        AdminAuditLog.target_type,
        AdminAuditLog.target_id,
        AdminAuditLog.ip,
        AdminAuditLog.reason,
    ]
    column_searchable_list = [AdminAuditLog.action, AdminAuditLog.actor_email]
    column_sortable_list = [AdminAuditLog.created_at, AdminAuditLog.action]
    column_default_sort = (AdminAuditLog.created_at, True)
    column_filters = [BooleanFilter(AdminAuditLog.ok, title="Succeeded")]
    can_create = False
    can_edit = False
    can_delete = False
    name = "Audit entry"
    name_plural = "Audit log"
    icon = "fa-solid fa-list-check"
