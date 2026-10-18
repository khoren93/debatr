"""Admin console System page: pure rules (run steps, orphan folders, refusals, config flags,
job summaries), fair-share refusals in Redis, and the routes' roles, sudo and checks.

Pure: Redis, the database and RQ are small fakes; folders live in pytest's tmp_path.
"""

import os
import time
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar

import httpx
import pytest
from fastapi import FastAPI

from app.admin.access import SUDO_HEADER, AdminContext, current_admin, read_only_db
from app.api.admin import routes_system
from app.core.config import settings
from app.core.db import get_db
from app.models.models import AdminAuditLog, User
from app.services import fair_share
from app.services.admin import system
from app.services.admin.sessions import AdminSession

# --- pure rules -------------------------------------------------------------------------------


def test_tail_keeps_the_end_of_a_traceback() -> None:
    assert system.tail(None) is None and system.tail("  ") is None
    long = "Traceback\n" + "x" * 3000 + "\nValueError: boom"
    out = system.tail(long, 100)
    assert out is not None and out.startswith("…") and out.endswith("ValueError: boom")
    assert len(out) == 101


def test_debate_and_media_steps() -> None:
    config = {
        "participants": [
            {"role": "moderator"},
            {"role": "debater"},
            {"role": "debater"},
        ],
        "num_rounds": 2,
    }
    assert system.debate_step(config, 0, "queued") == "waiting to start"
    assert system.debate_step(config, 3, "queued") == "waiting, 3 turns saved"
    first = system.debate_step(config, 0, "running")
    assert first.startswith("turn 1 of ")
    total = int(first.rsplit(" ", 1)[-1])
    assert system.debate_step(config, total - 1, "running") == "verdict"
    assert system.media_step({"message": "Voicing turns", "current": 3, "total": 9}) == (
        "Voicing turns (3/9)"
    )
    assert system.media_step({}) == "queued"


def test_stuck_runs() -> None:
    five = timedelta(minutes=5)
    assert system.is_stuck(five, heartbeat=False, waiting=False)
    assert not system.is_stuck(five, heartbeat=True, waiting=False)
    assert not system.is_stuck(five, heartbeat=False, waiting=True)
    assert not system.is_stuck(timedelta(minutes=4), heartbeat=False, waiting=False)


def test_refusals_are_grouped_per_user_and_kind() -> None:
    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    grouped = system.parse_refusals(
        [
            (f"debate:{a}:1".encode(), 10.0),
            (f"debate:{a}:2", 30.0),
            (f"media:{a}:3", 20.0),
            (f"debate:{b}:4", 5.0),
            ("junk", 1.0),
        ]
    )
    assert grouped == {("debate", a): (2, 30.0), ("media", a): (1, 20.0), ("debate", b): (1, 5.0)}


def test_free_daily_cap() -> None:
    assert system.free_daily_cap(None) == 50 and system.free_daily_cap(9.99) == 50
    assert system.free_daily_cap(10) == 1000


def test_orphans_are_old_folders_of_missing_debates() -> None:
    now = time.time()
    kept, gone, fresh = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    folders = [
        system.Folder(kept, 10, 1, now - 7200),
        system.Folder(gone, 20, 2, now - 7200),
        system.Folder(fresh, 30, 3, now - 60),  # a debate being created right now
        system.Folder("demo", 40, 4, now - 7200),  # not a debate folder
    ]
    assert [f.name for f in system.orphans(folders, {kept}, now)] == [gone]


def test_media_scan_and_delete(tmp_path: Path) -> None:
    alive, lost = tmp_path / str(uuid.uuid4()), tmp_path / str(uuid.uuid4())
    for folder, size in ((alive, 5), (lost, 7)):
        (folder / "turns").mkdir(parents=True)
        (folder / "turns" / "000.wav").write_bytes(b"x" * size)
    (tmp_path / "loose.txt").write_text("not a folder")
    folders, disk = system.scan_media_sync(tmp_path)
    assert {f.name: (f.bytes, f.files) for f in folders} == {
        alive.name: (5, 1),
        lost.name: (7, 1),
    }
    assert disk["total"] and disk["free"] is not None
    assert system.delete_folders_sync(tmp_path, [lost.name]) == 7
    assert not lost.exists() and alive.exists()
    with pytest.raises(ValueError):
        system.delete_folders_sync(tmp_path, ["../etc"])  # never a path from the request


def test_config_flags_never_show_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "sk-or-very-secret")
    monkeypatch.setattr(settings, "ELEVENLABS_API_KEY", "")
    flags = {f["name"]: f["value"] for f in system.config_flags()}
    assert flags["OPENROUTER_API_KEY"] == "set" and flags["ELEVENLABS_API_KEY"] == "not set"
    assert "sk-or-very-secret" not in str(flags) and "SECRET_KEY" not in flags


class StubJob:
    id = "job-1"
    origin = "default"
    func_name = "app.services.orchestrator.process_turn_job"
    kwargs: ClassVar[dict[str, Any]] = {"debate_id": "d-1", "seq_index": 3}
    enqueued_at = datetime(2026, 10, 18, 11, 0)
    started_at = None
    ended_at = datetime(2026, 10, 18, 11, 1, tzinfo=UTC)
    exc_info = None

    def latest_result(self) -> Any:
        return type("Result", (), {"exc_string": "Traceback…\nRuntimeError: provider down"})()

    def get_status(self, refresh: bool = True) -> str:
        return "failed"


def test_enum_text() -> None:
    from rq.job import JobStatus

    assert system.enum_text(JobStatus.FINISHED) == "finished"
    assert system.enum_text("idle") == "idle" and system.enum_text(None) is None


def test_job_summary() -> None:
    out = system.job_summary(StubJob())  # type: ignore[arg-type]
    assert (out["func"], out["debate_id"], out["status"]) == ("process_turn_job", "d-1", "failed")
    assert out["enqueued_at"].tzinfo is UTC and out["error"].endswith("provider down")


# --- fair-share refusals ----------------------------------------------------------------------


class FakeRedis:
    def __init__(self) -> None:
        self.zsets: dict[str, dict[str, float]] = {}
        self.data: dict[str, str] = {}

    async def zadd(self, key: str, mapping: dict[str, float]) -> int:
        self.zsets.setdefault(key, {}).update(mapping)
        return len(mapping)

    async def zremrangebyscore(self, key: str, low: float, high: float) -> int:
        zset = self.zsets.get(key, {})
        gone = [m for m, s in zset.items() if low <= s <= high]
        for member in gone:
            del zset[member]
        return len(gone)

    async def zremrangebyrank(self, key: str, start: int, stop: int) -> int:
        return 0

    async def delete(self, *keys: str) -> int:
        return sum(self.data.pop(k, None) is not None for k in keys)

    async def get(self, key: str) -> str | None:
        return self.data.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self.data[key] = value
        return True


async def test_refusals_are_remembered(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeRedis()
    monkeypatch.setattr(fair_share, "get_async_redis", lambda: fake)
    uid = uuid.uuid4()
    await fair_share.note_refusal("debate", uid)
    await fair_share.note_refusal("media", uid)
    members = list(fake.zsets[fair_share.REFUSALS_KEY])
    assert sorted(m.split(":")[0] for m in members) == ["debate", "media"]
    assert all(m.split(":")[1] == str(uid) for m in members)


async def test_refusals_never_fail_the_request(monkeypatch: pytest.MonkeyPatch) -> None:
    class Broken:
        async def zadd(self, *args: Any, **kwargs: Any) -> int:
            raise ConnectionError("redis is down")

    monkeypatch.setattr(fair_share, "get_async_redis", lambda: Broken())
    await fair_share.note_refusal("debate", uuid.uuid4())


# --- routes -----------------------------------------------------------------------------------


def _ctx(role: str = "admin", sudo: bool = False) -> AdminContext:
    user = User(id=uuid.uuid4(), email=f"{role}@x.co", display_name=role, admin_role=role)
    session = AdminSession(
        user_id=str(user.id),
        csrf="c",
        created_at=time.time(),
        last_seen_at=time.time(),
        ip="",
        user_agent="",
        epoch=0,
        sudo_until=time.time() + 60 if sudo else 0.0,
    )
    return AdminContext(user=user, session=session, session_hash="h", ip=None, user_agent=None)


class FakeDB:
    def __init__(self) -> None:
        self.added: list[Any] = []

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        return None


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[FastAPI, FakeDB, Path]:
    db = FakeDB()

    async def fake_db() -> AsyncIterator[Any]:
        yield db

    async def existing(session: Any, names: Any) -> dict[str, str]:
        return {}  # no debate exists

    monkeypatch.setattr(settings, "MEDIA_ROOT", str(tmp_path))
    # media_root_path is cached on first use (importing app.main does that).
    monkeypatch.delitem(settings.__dict__, "media_root_path", raising=False)
    monkeypatch.setattr(system, "existing_debates", existing)
    monkeypatch.setattr(routes_system, "get_async_redis", lambda: FakeRedis())
    app = FastAPI()
    app.include_router(routes_system.router, prefix="/api/admin")
    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[read_only_db] = fake_db
    return app, db, tmp_path


async def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


async def test_moderators_cannot_see_the_system(api: tuple[FastAPI, FakeDB, Path]) -> None:
    app, _db, _root = api
    app.dependency_overrides[current_admin] = lambda: _ctx("moderator")
    async with await _client(app) as client:
        for path in ("queues", "runs", "limits", "providers", "health"):
            assert (await client.get(f"/api/admin/system/{path}")).status_code == 403, path


async def test_orphan_folders_need_sudo_and_are_checked_again(
    api: tuple[FastAPI, FakeDB, Path],
) -> None:
    app, db, root = api
    old, fresh = root / str(uuid.uuid4()), root / str(uuid.uuid4())
    for folder in (old, fresh):
        folder.mkdir()
        (folder / "a.mp3").write_bytes(b"x" * 9)
    hour_ago = time.time() - 7200
    os.utime(old, (hour_ago, hour_ago))
    body = {"reason": "clean the disk", "names": [old.name, fresh.name, "../../etc"]}
    app.dependency_overrides[current_admin] = lambda: _ctx("admin")
    async with await _client(app) as client:
        refused = await client.post("/api/admin/system/media/orphans/delete", json=body)
        assert refused.status_code == 403 and refused.headers.get(SUDO_HEADER) == "required"
        app.dependency_overrides[current_admin] = lambda: _ctx("admin", sudo=True)
        done = await client.post("/api/admin/system/media/orphans/delete", json=body)
    assert done.status_code == 200, done.text
    assert done.json() == {"deleted": 1, "bytes": 9, "skipped": [fresh.name, "../../etc"]}
    assert not old.exists() and fresh.exists()
    (entry,) = [row for row in db.added if isinstance(row, AdminAuditLog)]
    assert entry.action == "media.orphans_deleted" and entry.reason == "clean the disk"


async def test_recover_now_answers(
    api: tuple[FastAPI, FakeDB, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import recovery

    def busy(debate_id: str, kind: str) -> str:
        raise ValueError("A worker is on it right now")

    app, db, _root = api
    app.dependency_overrides[current_admin] = lambda: _ctx("admin")
    monkeypatch.setattr(recovery, "recover_now", busy)
    async with await _client(app) as client:
        bad = await client.post("/api/admin/system/runs/nope/recover", json={"reason": "stuck"})
        assert bad.status_code == 404
        r = await client.post(
            f"/api/admin/system/runs/{uuid.uuid4()}/recover", json={"reason": "stuck"}
        )
        assert r.status_code == 409 and "worker" in r.json()["detail"]
        monkeypatch.setattr(recovery, "recover_now", lambda debate_id, kind: "queued")
        ok = await client.post(
            f"/api/admin/system/runs/{uuid.uuid4()}/recover",
            json={"reason": "stuck", "kind": "media"},
        )
    assert ok.status_code == 200 and ok.json()["status"] == "queued"
    assert [row.action for row in db.added if isinstance(row, AdminAuditLog)] == ["run.recovered"]
