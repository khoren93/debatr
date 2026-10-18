import pytest

from app.api.serializers import has_premium_voices
from app.models.models import Debate
from app.services.ranking import (
    RATING_BASE,
    DebateRecord,
    build_leaderboard,
    trending_score,
)


def test_trending_prefers_fresh_and_liked() -> None:
    assert trending_score(5, 0, 10, age_hours=1) > trending_score(5, 0, 10, age_hours=48)
    assert trending_score(5, 0, 10, age_hours=24) > trending_score(0, 0, 10, age_hours=24)
    # Views are log-damped: 10x the views is far less than one extra like.
    assert trending_score(1, 0, 0, 24) > trending_score(0, 0, 9, 24)


def test_trending_clamps_negative_age() -> None:
    assert trending_score(0, 0, 0, age_hours=-5) == trending_score(0, 0, 0, age_hours=0)


def test_premium_voices_count_like_two_likes() -> None:
    assert trending_score(0, 0, 9, 12, premium_voices=True) == pytest.approx(
        trending_score(2, 0, 9, 12)
    )
    # A new debate with free voices overtakes an unliked premium one only after ~5 hours.
    assert trending_score(0, 0, 0, 5, premium_voices=True) > trending_score(0, 0, 0, 0)
    assert trending_score(0, 0, 0, 6, premium_voices=True) < trending_score(0, 0, 0, 0)
    # Likes still decide: a liked debate with free voices beats an unliked premium one.
    assert trending_score(3, 0, 20, 12) > trending_score(0, 0, 20, 12, premium_voices=True)


def test_premium_voices_need_ready_elevenlabs_audio() -> None:
    def debate(status: str, provider: str | None) -> Debate:
        options = {"provider": provider} if provider else {}
        return Debate(media_status=status, media_json={"options": options} if options else {})

    assert has_premium_voices(debate("ready", "elevenlabs"))
    assert not has_premium_voices(debate("ready", "edge"))
    assert not has_premium_voices(debate("running", "elevenlabs"))  # rebuilt, not ready yet
    assert not has_premium_voices(debate("none", None))


def _rec(models: dict[str, str], votes: dict[str, int] | None = None, judge: str | None = None):
    return DebateRecord(models=models, votes=votes or {}, judge_winner=judge)


def test_models_without_votes_sit_at_base_rating() -> None:
    board = build_leaderboard([_rec({"participant_1": "a", "participant_2": "b"})])
    assert {s.model_id for s in board} == {"a", "b"}
    assert all(s.rating == pytest.approx(RATING_BASE) for s in board)
    assert all(s.debates == 1 and s.votes == 0 and s.vote_share is None for s in board)
    assert not any(s.rated for s in board)


def test_unrated_models_come_after_rated_ones() -> None:
    records = [
        _rec({"participant_1": "a", "participant_2": "b"}, {"participant_1": 2}),
        _rec({"participant_1": "c", "participant_2": "d"}, judge="participant_1"),
    ]
    board = build_leaderboard(records)
    assert [s.model_id for s in board][:2] == ["a", "b"]  # b lost, yet it is rated
    assert board[1].rating < RATING_BASE and board[1].rated
    assert {s.model_id for s in board[2:]} == {"c", "d"}
    assert not any(s.rated for s in board[2:])


def test_votes_rank_models_and_count_wins() -> None:
    records = [
        _rec(
            {"participant_1": "a", "participant_2": "b"}, {"participant_1": 3, "participant_2": 1}
        ),
        _rec(
            {"participant_1": "b", "participant_2": "c"},
            {"participant_1": 2},
            judge="participant_2",
        ),
        _rec(
            {"participant_1": "a", "participant_2": "c"}, {"participant_1": 1, "participant_2": 1}
        ),
    ]
    board = build_leaderboard(records)
    by_id = {s.model_id: s for s in board}
    assert board[0].model_id == "a"
    assert by_id["a"].rating > by_id["b"].rating > by_id["c"].rating
    assert by_id["a"].audience_wins == 1 and by_id["a"].audience_contests == 2  # one tie
    assert by_id["b"].votes == 3 and by_id["b"].votes_in_debates == 6
    assert by_id["b"].vote_share == pytest.approx(0.5)
    assert by_id["c"].judge_wins == 1 and by_id["c"].judge_contests == 1
    assert by_id["b"].judge_contests == 1 and by_id["a"].judge_contests == 0


def test_single_vote_does_not_explode_the_rating() -> None:
    board = build_leaderboard(
        [_rec({"participant_1": "a", "participant_2": "b"}, {"participant_1": 1})]
    )
    by_id = {s.model_id: s for s in board}
    assert RATING_BASE < by_id["a"].rating < RATING_BASE + 60
    assert by_id["b"].rating == pytest.approx(2 * RATING_BASE - by_id["a"].rating)


def test_mirror_match_counts_debate_but_not_contest() -> None:
    board = build_leaderboard(
        [_rec({"participant_1": "a", "participant_2": "a"}, {"participant_1": 4})]
    )
    (only,) = board
    assert only.debates == 1 and only.votes == 4
    assert only.audience_contests == 0 and only.rating == pytest.approx(RATING_BASE)
    assert not only.rated


def test_more_votes_beat_a_lucky_streak() -> None:
    records = [
        _rec({"participant_1": "lucky", "participant_2": "x"}, {"participant_1": 1}),
        *[
            _rec(
                {"participant_1": "steady", "participant_2": "y"},
                {"participant_1": 3, "participant_2": 1},
            )
            for _ in range(5)
        ],
    ]
    by_id = {s.model_id: s for s in build_leaderboard(records)}
    assert by_id["steady"].rating > by_id["lucky"].rating


def test_fact_checks_add_up_per_model() -> None:
    claims = {
        "participant_1": {"checked": 3, "verified": 2, "disputed": 1, "unverified": 0},
        "participant_2": {"checked": 1, "verified": 0, "disputed": 1, "unverified": 0},
        "participant_9": {"checked": 5, "verified": 5},  # not a debater of this record
    }
    records = [
        DebateRecord(models={"participant_1": "a", "participant_2": "b"}, claims=claims),
        DebateRecord(
            models={"participant_1": "a", "participant_2": "a"},
            claims={"participant_2": {"checked": 2, "verified": 2}},
        ),
    ]
    board = {s.model_id: s for s in build_leaderboard(records)}
    assert (board["a"].claims_checked, board["a"].claims_verified) == (5, 4)
    assert board["a"].claims_disputed == 1
    assert (board["b"].claims_checked, board["b"].claims_disputed) == (1, 1)
