"""Stage-one worker safety: heartbeats, orphan recovery decisions and the free-model quota."""

import time
from datetime import timedelta
from typing import Any

import pytest

from app.core.config import settings
from app.models.models import Turn, utcnow
from app.services import free_quota, heartbeat, queue_manager, recovery


class FakeRedis:
    """The few commands these modules use, in memory (TTLs are recorded, not enforced)."""

    def __init__(self) -> None:
        self.data: dict[str, Any] = {}
        self.ttl: dict[str, int] = {}

    def set(self, key: str, value: Any, ex: int | None = None, nx: bool = False) -> bool:
        if nx and key in self.data:
            return False
        self.data[key] = value
        if ex is not None:
            self.ttl[key] = ex
        return True

    def delete(self, *keys: str) -> int:
        return sum(self.data.pop(k, None) is not None for k in keys)

    def exists(self, key: str) -> int:
        return int(key in self.data)

    def incr(self, key: str) -> int:
        self.data[key] = int(self.data.get(key, 0)) + 1
        return self.data[key]

    def expire(self, key: str, seconds: int) -> bool:
        self.ttl[key] = seconds
        return True


@pytest.fixture
def redis(monkeypatch: pytest.MonkeyPatch) -> FakeRedis:
    fake = FakeRedis()
    for module in (heartbeat, free_quota):
        monkeypatch.setattr(module, "get_sync_redis", lambda: fake)
    return fake


# --- heartbeats ------------------------------------------------------------------------------


def test_a_job_beats_while_it_runs(redis: Any):
    with heartbeat.heartbeat("debate:x:beat"):
        time.sleep(0.05)
        assert heartbeat.alive("debate:x:beat")
        assert redis.ttl["debate:x:beat"] == heartbeat.TTL
    assert not [t for t in heartbeat.threading.enumerate() if t.name.startswith("heartbeat")]


def test_the_beating_decorator_keys_by_debate_id(redis: Any):
    seen: list[bool] = []

    @heartbeat.beating(lambda debate_id: f"debate:{debate_id}:beat")
    def job(debate_id: str, seq_index: int) -> int:
        time.sleep(0.05)
        seen.append(heartbeat.alive(f"debate:{debate_id}:beat"))
        return seq_index

    assert job(debate_id="d1", seq_index=3) == 3 and job("d2", 4) == 4
    assert seen == [True, True]
    assert job.__name__ == "job"  # RQ finds jobs by dotted path


# --- recovery decisions ----------------------------------------------------------------------


def _turns(*ok: bool) -> list[Turn]:
    return [
        Turn(seq_index=i, text="Said." if good else "", error=None) for i, good in enumerate(ok)
    ]


def test_next_step_goes_on_from_the_first_missing_turn():
    assert recovery.next_step("queued", [], 6) == ("start", 0)
    assert recovery.next_step("queued", _turns(True, True), 6) == ("start", 2)  # a resume
    assert recovery.next_step("running", _turns(True, True, False), 6) == ("turn", 2)
    assert recovery.next_step("running", _turns(*[True] * 6), 6) == ("verdict", 6)
    assert recovery.next_step("running", _turns(*[True] * 7), 6) == ("finish", 7)


def test_give_up_reasons():
    now = utcnow()
    fresh = now - timedelta(minutes=5)
    assert recovery.give_up_reason(1, fresh, key_lost=False, now=now) is None
    assert recovery.give_up_reason(1, None, key_lost=False, now=now) is None
    over = settings.RECOVERY_ATTEMPTS + 1
    assert "again" in (recovery.give_up_reason(over, fresh, key_lost=False, now=now) or "")
    old = now - recovery.MAX_AGE - timedelta(minutes=1)
    assert "long ago" in (recovery.give_up_reason(1, old, key_lost=False, now=now) or "")
    assert "key expired" in (recovery.give_up_reason(1, fresh, key_lost=True, now=now) or "")


def test_an_orphan_is_confirmed_on_the_second_check_only(redis: Any):
    confirm = recovery._orphan_confirmed
    assert not confirm(redis, "debate", "d", busy=False)  # first sighting
    assert confirm(redis, "debate", "d", busy=False)  # still no job a minute later
    assert not confirm(redis, "debate", "d", busy=False)  # counting starts over

    assert not confirm(redis, "debate", "e", busy=False)
    assert not confirm(redis, "debate", "e", busy=True)  # its next job showed up
    assert not confirm(redis, "debate", "e", busy=False)  # so this is a first sighting again


def test_attempts_are_counted_per_run(redis: Any):
    assert recovery._attempt(redis, "debate", "d") == 1
    assert recovery._attempt(redis, "debate", "d") == 2
    assert recovery._attempt(redis, "media", "d") == 1
    assert redis.ttl["recovery:attempts:debate:d"] == recovery.ATTEMPTS_TTL


# --- free-model quota ------------------------------------------------------------------------


def test_free_model_slots_fill_a_minute_then_wait(redis: Any, monkeypatch):
    monkeypatch.setattr(settings, "FREE_MODELS_PER_MINUTE", 2)
    clock = {"now": 600.0}  # wall clock, at the start of a minute
    waited: list[float] = []

    def sleep(seconds: float) -> None:
        waited.append(seconds)
        clock["now"] += seconds

    monkeypatch.setattr(free_quota.time, "time", lambda: clock["now"])
    monkeypatch.setattr(free_quota.time, "sleep", sleep)
    monkeypatch.setattr(free_quota.random, "uniform", lambda _a, _b: 0.0)
    far = time.monotonic() + 3600
    assert free_quota.wait_for_slot(far) and free_quota.wait_for_slot(far)
    assert waited == []
    assert free_quota.wait_for_slot(far)  # the third waits for the next minute
    assert waited == [60.0]
    assert redis.ttl["ratelimit:free-models:10"] == 120


def test_free_model_slot_gives_up_at_the_deadline(redis: Any, monkeypatch):
    monkeypatch.setattr(settings, "FREE_MODELS_PER_MINUTE", 1)
    monkeypatch.setattr(free_quota.time, "sleep", lambda _s: pytest.fail("must not wait"))
    soon = time.monotonic() + 1
    assert free_quota.wait_for_slot(soon)
    assert not free_quota.wait_for_slot(soon)


def test_free_models_are_recognised():
    assert free_quota.is_free_model("openrouter/free")
    assert free_quota.is_free_model("qwen/qwen3:free")
    assert not free_quota.is_free_model("openai/gpt-5")


def test_process_checks_name_queues_without_a_worker(monkeypatch):
    def workers(queue: Any = None, **_kw: Any) -> list[str]:
        return [] if queue.name == "media" else ["w"]

    monkeypatch.setattr(queue_manager.Worker, "all", workers)
    monkeypatch.setattr(queue_manager.CronScheduler, "all", lambda _redis, cleanup: [])
    assert queue_manager.process_checks(object()) == {  # type: ignore[arg-type]
        "default_workers": "ok",
        "background_workers": "ok",
        "media_workers": "none",
        "scheduler": "none",
    }


async def test_full_health_is_503_without_workers(monkeypatch):
    from app import main

    async def connectivity() -> dict[str, str]:
        return {"database": "ok", "redis": "ok"}

    checks = {"default_workers": "ok", "media_workers": "ok", "scheduler": "ok"}
    monkeypatch.setattr(main, "_connectivity", connectivity)
    monkeypatch.setattr(main, "get_sync_redis", lambda: None)
    monkeypatch.setattr(queue_manager, "process_checks", lambda _redis: dict(checks))
    assert (await main.full_health_check()).status_code == 200
    checks["media_workers"] = "none"
    assert (await main.full_health_check()).status_code == 503

    def broken(_redis: Any) -> dict[str, str]:
        raise ConnectionError("gone")

    monkeypatch.setattr(queue_manager, "process_checks", broken)
    response = await main.full_health_check()
    assert response.status_code == 503 and b"error: ConnectionError" in response.body
