"""Gallery ranking (trending score) and the model leaderboard built from audience votes.

Pure functions only: the routes load the rows and pass plain data in, so this is unit-tested
without a database. `trending_sql()` in routes_gallery mirrors `trending_score()`.
"""

import math
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field

# Trending = engagement / (age + offset) ^ gravity (Hacker News style). Likes weigh most;
# views are log-damped so a popular share link does not drown out what people actually liked.
LIKE_WEIGHT = 3.0
VOTE_WEIGHT = 1.0
TRENDING_OFFSET_HOURS = 2.0
TRENDING_GRAVITY = 1.5

# Leaderboard rating: Bradley-Terry strengths shown on an Elo-like scale.
RATING_BASE = 1000.0
RATING_SCALE = 400.0
# Virtual wins and losses (PRIOR_GAMES each) against an average opponent, so a model with a
# single lucky vote (+~45) does not jump above a steady winner and a model without votes sits
# exactly at RATING_BASE.
PRIOR_GAMES = 3.0
_ITERATIONS = 200
_TOLERANCE = 1e-9


def trending_score(likes: int, votes: int, views: int, age_hours: float) -> float:
    engagement = likes * LIKE_WEIGHT + votes * VOTE_WEIGHT + math.log(views + 1) + 1
    return engagement / math.pow(max(age_hours, 0.0) + TRENDING_OFFSET_HOURS, TRENDING_GRAVITY)


@dataclass
class DebateRecord:
    """One public debate: who argued (debaters only) and how the audience and judge saw it."""

    models: dict[str, str]  # participant_id -> model_id
    votes: dict[str, int] = field(default_factory=dict)  # participant_id -> audience votes
    judge_winner: str | None = None  # participant_id, None for a draw or no verdict
    # participant_id -> {checked, verified, disputed, unverified}: web fact-checks of the
    # figures and quotes the debater put on screen (totals_json["claims"]).
    claims: dict[str, dict[str, int]] = field(default_factory=dict)


@dataclass
class ModelStanding:
    model_id: str
    rating: float = RATING_BASE
    debates: int = 0
    votes: int = 0  # audience votes received
    votes_in_debates: int = 0  # all audience votes cast in this model's debates
    audience_wins: int = 0
    audience_contests: int = 0  # debates against another model that got at least one vote
    judge_wins: int = 0
    judge_contests: int = 0  # debates against another model that the judge decided
    claims_checked: int = 0
    claims_verified: int = 0
    claims_disputed: int = 0

    @property
    def vote_share(self) -> float | None:
        return self.votes / self.votes_in_debates if self.votes_in_debates else None


def _per_model(record: DebateRecord, values: dict[str, int]) -> dict[str, int]:
    """Sum participant values by model (the same model may argue on several sides)."""
    out: dict[str, int] = defaultdict(int)
    for pid, model in record.models.items():
        out[model] += values.get(pid, 0)
    return out


def _bradley_terry(wins: dict[tuple[str, str], float], models: Iterable[str]) -> dict[str, float]:
    """Strengths from pairwise wins[(winner, loser)] via the MM algorithm, with a fixed anchor
    of strength 1 that every model has PRIOR_GAMES wins and losses against."""
    names = sorted(set(models))
    games: dict[str, dict[str, float]] = {m: defaultdict(float) for m in names}
    won: dict[str, float] = {m: PRIOR_GAMES for m in names}
    for (winner, loser), count in wins.items():
        if winner == loser or count <= 0:
            continue
        games[winner][loser] += count
        games[loser][winner] += count
        won[winner] += count
    strength = {m: 1.0 for m in names}
    for _ in range(_ITERATIONS):
        delta = 0.0
        updated: dict[str, float] = {}
        for m in names:
            denominator = 2 * PRIOR_GAMES / (strength[m] + 1.0)
            for other, n in games[m].items():
                denominator += n / (strength[m] + strength[other])
            updated[m] = won[m] / denominator
            delta = max(delta, abs(updated[m] - strength[m]))
        strength = updated
        if delta < _TOLERANCE:
            break
    return strength


def build_leaderboard(records: Iterable[DebateRecord]) -> list[ModelStanding]:
    """Standings of every model that argued in at least one of the given debates, best first."""
    standings: dict[str, ModelStanding] = {}
    pairwise: dict[tuple[str, str], float] = defaultdict(float)

    for record in records:
        if not record.models:
            continue
        models = set(record.models.values())
        votes = _per_model(record, record.votes)
        total = sum(votes.values())
        for model in models:
            s = standings.setdefault(model, ModelStanding(model_id=model))
            s.debates += 1
            s.votes += votes.get(model, 0)
            s.votes_in_debates += total
        for pid, counts in record.claims.items():
            claimant = record.models.get(pid)
            if claimant is None or not isinstance(counts, dict):
                continue
            s = standings[claimant]
            s.claims_checked += int(counts.get("checked") or 0)
            s.claims_verified += int(counts.get("verified") or 0)
            s.claims_disputed += int(counts.get("disputed") or 0)
        if len(models) < 2:
            continue  # a mirror match says nothing about which model is better

        if total > 0:
            best = max(votes.values())
            leaders = [m for m, v in votes.items() if v == best]
            for model in models:
                standings[model].audience_contests += 1
            if len(leaders) == 1:
                standings[leaders[0]].audience_wins += 1
            # Each vote is a win of the chosen model over every other model in the debate.
            for winner, count in votes.items():
                for loser in models - {winner}:
                    pairwise[(winner, loser)] += count

        judge_model = record.models.get(record.judge_winner or "")
        if judge_model is not None:
            for model in models:
                standings[model].judge_contests += 1
            standings[judge_model].judge_wins += 1

    strength = _bradley_terry(pairwise, standings)
    for model, s in standings.items():
        s.rating = RATING_BASE + RATING_SCALE * math.log10(strength[model])
    return sorted(
        standings.values(),
        key=lambda s: (-round(s.rating, 6), -s.votes, -s.debates, s.model_id),
    )
