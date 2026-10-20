"""Limits of free debates (services/free_limits): who they apply to, size, the day's allowance."""

import time
import uuid
from decimal import Decimal
from typing import Any

import pytest
from fastapi import HTTPException

from app.core.config import settings
from app.models.models import User
from app.schemas.schemas import DebateConfig
from app.services import free_limits, runtime_settings


class FakeRedis:
    """The sorted-set calls free_limits makes."""

    def __init__(self) -> None:
        self.sets: dict[str, dict[str, float]] = {}

    async def zremrangebyscore(self, key: str, low: float, high: float) -> None:
        members = self.sets.get(key, {})
        self.sets[key] = {m: s for m, s in members.items() if not low <= s <= high}

    async def zrange(self, key: str, _start: int, _end: int, withscores: bool) -> list[Any]:
        assert withscores
        return sorted(self.sets.get(key, {}).items(), key=lambda item: item[1])

    async def zadd(self, key: str, mapping: dict[str, float]) -> None:
        self.sets.setdefault(key, {}).update(mapping)

    async def expire(self, _key: str, _seconds: int) -> None: ...


class FakeDb:
    async def execute(self, _statement: Any) -> None: ...


DB: Any = FakeDb()


@pytest.fixture
def redis(monkeypatch: pytest.MonkeyPatch) -> FakeRedis:
    fake = FakeRedis()
    monkeypatch.setattr(free_limits, "get_async_redis", lambda: fake)
    return fake


def _config(*models: str, rounds: int = 2, length: str = "short") -> DebateConfig:
    return DebateConfig.model_validate(
        {
            "topic": "Tabs or spaces?",
            "num_rounds": rounds,
            "length_preset": length,
            "participants": [
                {"role": "moderator", "model_id": "openrouter/free", "display_name": "Host"},
                *(
                    {"role": "debater", "model_id": m, "display_name": f"D{i}"}
                    for i, m in enumerate(models)
                ),
            ],
        }
    )


def _user(balance: str = "0") -> User:
    return User(id=uuid.uuid4(), email="free@example.com", credits_usd=Decimal(balance))


FREE = ("openrouter/free", "vendor/model:free")


def test_only_free_runs_without_credits_or_an_own_key_are_limited() -> None:
    assert free_limits.is_free_run(_config(*FREE), own_key=False, balance=0)
    assert not free_limits.is_free_run(_config(*FREE), own_key=True, balance=0)
    assert not free_limits.is_free_run(_config(*FREE), own_key=False, balance=Decimal("0.5"))
    paid = _config("openrouter/free", "openai/gpt-5.5")
    assert not free_limits.is_free_run(paid, own_key=False, balance=0)


def test_size_rules_follow_the_levers(levers: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    current = runtime_settings.resolve({})
    assert free_limits.size_problem(_config(*FREE, rounds=3), current) is None
    too_big = _config(*FREE, *FREE, "a/b:free", rounds=4, length="medium")
    problem = free_limits.size_problem(too_big, current)
    assert problem is not None
    assert "up to 3 rounds and up to 4 debaters and short or medium replies" in problem
    monkeypatch.setattr(type(settings), "payments_mode", property(lambda _s: "disabled"))
    assert "add your own OpenRouter key" in str(free_limits.size_problem(too_big, current))
    off = runtime_settings.resolve(
        {"free_max_rounds": 0, "free_max_debaters": 0, "free_lengths": []}
    )
    assert free_limits.size_problem(too_big, off) is None


def test_the_daily_problem_says_when_the_next_run_is_free() -> None:
    now = time.time()
    runs = free_limits.FreeRuns(per_day=5, used=5, oldest=now - 3600)
    assert runs.left == 0 and runs.next_at() is not None
    assert "next one is free in 23 h 0 min" in str(free_limits.daily_problem(runs, now))
    assert free_limits.daily_problem(free_limits.FreeRuns(5, 4, now), now) is None
    assert free_limits.daily_problem(free_limits.FreeRuns(0, 9, now), now) is None


async def test_the_sixth_free_run_of_a_day_is_refused(redis: FakeRedis, levers: dict) -> None:
    user, config = _user(), _config(*FREE)
    for _ in range(5):
        await free_limits.take(DB, user, config, own_key=False)
    with pytest.raises(HTTPException) as caught:
        await free_limits.take(DB, user, config, own_key=False)
    assert caught.value.status_code == 429
    runs, problem = await free_limits.check(user, config, own_key=False)
    assert runs is not None and (runs.used, runs.left) == (5, 0) and problem
    # Runs older than a day leave the window.
    key = next(iter(redis.sets))
    redis.sets[key] = {m: s - 25 * 3600 for m, s in redis.sets[key].items()}
    await free_limits.take(DB, user, config, own_key=False)
    # Credits or an own key are never counted nor refused.
    await free_limits.take(DB, _user("3"), config, own_key=False)
    await free_limits.take(DB, user, config, own_key=True)
    assert len(redis.sets) == 1 and len(redis.sets[key]) == 1


async def test_a_too_big_free_run_is_refused_before_counting(
    redis: FakeRedis, levers: dict
) -> None:
    with pytest.raises(HTTPException) as caught:
        await free_limits.take(DB, _user(), _config(*FREE, rounds=5), own_key=False)
    assert caught.value.status_code == 402 and redis.sets == {}
    levers["free_debates_per_day"] = 0  # no daily limit: nothing is counted
    await free_limits.take(DB, _user(), _config(*FREE), own_key=False)
    assert redis.sets == {}


async def test_the_estimate_of_a_signed_out_visitor_names_size_problems_only(
    redis: FakeRedis, levers: dict
) -> None:
    runs, problem = await free_limits.check(None, _config(*FREE, length="long"), own_key=False)
    assert runs is None and problem and "replies" in problem
    assert await free_limits.check(None, _config(*FREE), own_key=False) == (None, None)
