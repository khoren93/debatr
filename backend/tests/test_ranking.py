import pytest

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


def _rec(models: dict[str, str], votes: dict[str, int] | None = None, judge: str | None = None):
    return DebateRecord(models=models, votes=votes or {}, judge_winner=judge)


def test_models_without_votes_sit_at_base_rating() -> None:
    board = build_leaderboard([_rec({"participant_1": "a", "participant_2": "b"})])
    assert {s.model_id for s in board} == {"a", "b"}
    assert all(s.rating == pytest.approx(RATING_BASE) for s in board)
    assert all(s.debates == 1 and s.votes == 0 and s.vote_share is None for s in board)


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
