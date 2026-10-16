import uuid

from app.models.models import Debate, DebateParticipant, User
from app.services.engagement import like_blocker, vote_blocker


def _user() -> User:
    return User(id=uuid.uuid4(), email="u@example.com", password_hash="x", display_name="U")


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
