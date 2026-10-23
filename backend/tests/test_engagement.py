import uuid
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException

from app.api import routes_reactions
from app.models.models import Debate, DebateParticipant, User
from app.services.engagement import like_blocker, vote_blocker


def _user(*, required: bool = False, confirmed: bool = False) -> User:
    return User(
        id=uuid.uuid4(),
        email="u@example.com",
        password_hash="x",
        display_name="U",
        email_check_required=required,
        email_verified_at=datetime.now(UTC) if confirmed else None,
    )


def _debate(owner: User, *, public: bool = True, status: str = "completed") -> Debate:
    debate = Debate(id=uuid.uuid4(), user_id=owner.id, status=status, is_public=public)
    debate.participants = [
        DebateParticipant(role="moderator", model_id="m"),
        DebateParticipant(role="debater", model_id="a"),
        DebateParticipant(role="debater", model_id="b"),
    ]
    return debate


def test_like_rules() -> None:
    owner, viewer = _user(), _user()
    assert like_blocker(_debate(owner), viewer) is None
    assert like_blocker(_debate(owner), None) == "sign_in"
    assert like_blocker(_debate(owner), owner) == "owner"
    assert like_blocker(_debate(owner, public=False), viewer) == "not_public"


def test_vote_rules() -> None:
    owner, viewer = _user(), _user()
    assert vote_blocker(_debate(owner), viewer) is None
    assert vote_blocker(_debate(owner, status="stopped"), viewer) == "not_finished"
    assert vote_blocker(_debate(owner, status="running"), viewer) == "not_finished"
    assert vote_blocker(_debate(owner), owner) == "owner"
    assert vote_blocker(_debate(owner, public=False), viewer) == "not_public"
    solo = _debate(owner)
    solo.participants = solo.participants[:2]
    assert vote_blocker(solo, viewer) == "not_finished"


def test_new_accounts_like_and_vote_once_their_email_is_confirmed() -> None:
    owner, fresh = _user(), _user(required=True)
    assert like_blocker(_debate(owner), fresh) == "confirm_email"
    assert vote_blocker(_debate(owner), fresh) == "confirm_email"
    confirmed = _user(required=True, confirmed=True)
    assert like_blocker(_debate(owner), confirmed) is None
    assert vote_blocker(_debate(owner), confirmed) is None
    older = _user()  # from before confirmations: only asked to confirm
    assert vote_blocker(_debate(owner), older) is None
    # A like or vote given before can still be taken back; a new one cannot be given.
    routes_reactions._raise_if_blocked("confirm_email", retract=True)
    with pytest.raises(HTTPException) as refused:
        routes_reactions._raise_if_blocked("confirm_email")
    assert refused.value.status_code == 403 and "Confirm your email" in refused.value.detail
    with pytest.raises(HTTPException):
        routes_reactions._raise_if_blocked("owner", retract=True)
