"""The admin console's System page: RQ queues, workers and the cron scheduler, runs in flight,
limits, providers and health (database, Redis, MEDIA_ROOT, version, config, backups).

RQ and the file system are read with blocking calls (`*_sync`, run in a thread pool by the
routes); the media scan is cached in Redis because walking MEDIA_ROOT takes a while on a big
disk. The pure parts (job summaries, run steps, orphan rules, config flags) are tested on their
own.
"""

import contextlib
import json
import os
import shutil
import time
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from redis import Redis
from redis.asyncio import Redis as AsyncRedis
from redis.exceptions import RedisError
from rq import Queue, Worker, cron_job_registry
from rq.cron import CronScheduler, get_cron_job_ids
from rq.job import Job
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.core.redis import debate_beat_key, free_models_window_key, media_beat_key, recovery_key
from app.models.models import Debate, ProviderUsage, Turn, User
from app.services.fair_share import REFUSALS_KEY, REFUSALS_SECONDS
from app.services.queue_manager import (
    BACKGROUND_QUEUE_NAME,
    MEDIA_QUEUE_NAME,
    QUEUE_NAME,
    waiting_debates,
)
from app.services.scheduler import build_schedule

QUEUES = (QUEUE_NAME, BACKGROUND_QUEUE_NAME, MEDIA_QUEUE_NAME)
ACTIVE = ("queued", "running")
FAILED_SHOWN = 50
ERROR_CHARS = 1500
STUCK_AFTER = timedelta(minutes=5)
ORPHAN_MIN_AGE = timedelta(hours=1)
MEDIA_CACHE_KEY = "admin:media_scan"
MEDIA_CACHE_SECONDS = 300
HEAVIEST = 12
# OpenRouter's daily `:free` request cap: 1000 once $10 of credits were bought, else 50.
FREE_DAILY_CAP_PAID = 1000
FREE_DAILY_CAP_FREE = 50


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


# --- queues, workers, scheduler (blocking) ----------------------------------------------------


def tail(text_value: str | None, limit: int = ERROR_CHARS) -> str | None:
    """The end of a traceback (where the error is), at most `limit` characters."""
    value = (text_value or "").strip()
    if not value:
        return None
    return value if len(value) <= limit else "…" + value[-limit:]


def enum_text(value: Any) -> str | None:
    """ "finished" for JobStatus.FINISHED (RQ's statuses are enums, plain strings in old jobs)."""
    if value is None:
        return None
    return str(getattr(value, "value", value)) or None


def job_summary(job: Job) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    try:
        kwargs = dict(job.kwargs or {})
    except Exception:
        kwargs = {}
    error = None
    try:
        result = job.latest_result()
        error = result.exc_string if result is not None else None
    except Exception:
        error = None
    func_name = (job.func_name or "").rsplit(".", 1)[-1] or "?"
    try:
        status = enum_text(job.get_status(refresh=False))
    except Exception:
        status = None
    return {
        "id": job.id,
        "queue": job.origin or "",
        "func": func_name,
        "debate_id": str(kwargs["debate_id"]) if kwargs.get("debate_id") else None,
        "status": status or None,
        "enqueued_at": _aware(job.enqueued_at),
        "started_at": _aware(job.started_at),
        "ended_at": _aware(job.ended_at),
        "error": tail(error or (job.exc_info if isinstance(job.exc_info, str) else None)),
    }


def _jobs(conn: Redis, ids: Iterable[str]) -> list[dict[str, Any]]:
    wanted = list(ids)
    if not wanted:
        return []
    return [job_summary(job) for job in Job.fetch_many(wanted, connection=conn) if job]


def queues_sync(conn: Redis) -> dict[str, Any]:
    queues = []
    failed: list[dict[str, Any]] = []
    for name in QUEUES:
        queue = Queue(name, connection=conn)
        queues.append(
            {
                "name": name,
                "waiting": queue.count,
                "started": queue.started_job_registry.count,
                "failed": queue.failed_job_registry.count,
                "scheduled": queue.scheduled_job_registry.count,
                "deferred": queue.deferred_job_registry.count,
                "finished": queue.finished_job_registry.count,
            }
        )
        failed += _jobs(conn, queue.failed_job_registry.get_job_ids(0, FAILED_SHOWN - 1))
    failed.sort(key=lambda j: j["ended_at"] or datetime.min.replace(tzinfo=UTC), reverse=True)
    workers = []
    for worker in Worker.all(connection=conn):
        job = worker.get_current_job()
        workers.append(
            {
                "name": worker.name,
                "hostname": worker.hostname,
                "pid": worker.pid,
                "queues": worker.queue_names(),
                "state": enum_text(worker.get_state()) or "unknown",
                "current_job": job_summary(job) if job else None,
                "last_heartbeat": _aware(worker.last_heartbeat),
                "birth": _aware(worker.birth_date),
                "successful": int(worker.successful_job_count or 0),
                "failed": int(worker.failed_job_count or 0),
                "working_seconds": float(worker.total_working_time or 0),
            }
        )
    workers.sort(key=lambda w: (",".join(w["queues"]), w["name"]))
    schedulers = []
    intervals: dict[str, int | None] = {}
    for scheduler in CronScheduler.all(conn):
        schedulers.append(
            {
                "name": scheduler.name,
                "hostname": scheduler.hostname or None,
                "pid": scheduler.pid or None,
                "started_at": _aware(scheduler.created_at),
                "last_heartbeat": scheduler.last_heartbeat,
            }
        )
        for cron_job in scheduler.get_jobs():
            intervals[cron_job.name] = cron_job.interval
    scored: Any = conn.zrange(cron_job_registry.get_registry_key(), 0, -1, withscores=True)
    last = {(k.decode() if isinstance(k, bytes) else str(k)): float(v) for k, v in scored}
    cron_jobs = []
    for name in cron_job_registry.get_names(conn):
        score = last.get(name)
        cron_jobs.append(
            {
                "name": name.rsplit(".", 1)[-1],
                "interval_seconds": intervals.get(name),
                "last_enqueued_at": datetime.fromtimestamp(float(score), UTC) if score else None,
                "recent": _jobs(conn, get_cron_job_ids(name, conn, 0, 4)),
            }
        )
    return {
        "queues": queues,
        "workers": workers,
        "schedulers": schedulers,
        "cron_jobs": cron_jobs,
        "failed_jobs": failed[:FAILED_SHOWN],
    }


def failed_job_action_sync(conn: Redis, job_id: str, action: str) -> dict[str, Any]:
    """Requeue or delete a failed job. Raises LookupError when it is not a failed job."""
    try:
        job = Job.fetch(job_id, connection=conn)
    except Exception:
        raise LookupError(job_id) from None
    registry = Queue(job.origin, connection=conn).failed_job_registry
    if job.id not in registry.get_job_ids():
        raise LookupError(job_id)
    summary = job_summary(job)
    if action == "requeue":
        registry.requeue(job.id)
    else:
        registry.remove(job, delete_job=True)
    return summary


# --- runs in flight ---------------------------------------------------------------------------


def debate_step(config: dict[str, Any], turns_saved: int, status: str) -> str:
    if status == "queued":
        return "waiting to start" if turns_saved == 0 else f"waiting, {turns_saved} turns saved"
    schedule = build_schedule(config.get("participants") or [], int(config.get("num_rounds") or 1))
    total = len(schedule) + 1  # the verdict
    current = min(turns_saved + 1, total)
    return "verdict" if current == total else f"turn {current} of {total}"


def media_step(state: dict[str, Any]) -> str:
    message = str(state.get("message") or state.get("step") or "")
    current, total = state.get("current"), state.get("total")
    if isinstance(current, int) and isinstance(total, int) and total:
        return f"{message} ({current}/{total})".strip()
    return message or "queued"


def is_stuck(age: timedelta, heartbeat: bool, waiting: bool) -> bool:
    return not heartbeat and not waiting and age >= STUCK_AFTER


async def runs(db: AsyncSession, conn: Redis, redis: AsyncRedis, now: datetime) -> list[Any]:
    """Debates and audio builds queued or running, oldest first, with their worker state."""
    rows = (
        await db.execute(
            select(Debate, User.email)
            .outerjoin(User, User.id == Debate.user_id)
            .where((Debate.status.in_(ACTIVE)) | (Debate.media_status.in_(ACTIVE)))
            .order_by(Debate.created_at)
        )
    ).all()
    if not rows:
        return []
    ids = [d.id for d, _ in rows]
    saved = dict(
        (
            await db.execute(
                select(Turn.debate_id, func.count())
                .where(Turn.debate_id.in_(ids))
                .group_by(Turn.debate_id)
            )
        ).all()
    )
    turns_waiting = await run_in_threadpool(waiting_debates, conn, QUEUE_NAME)
    media_waiting = await run_in_threadpool(waiting_debates, conn, MEDIA_QUEUE_NAME)
    out: list[dict[str, Any]] = []
    for debate, email in rows:
        did = str(debate.id)
        if debate.status in ACTIVE:
            since = _aware(debate.started_at or debate.created_at) or now
            beat = bool(await redis.exists(debate_beat_key(did)))
            waiting = did in turns_waiting
            out.append(
                {
                    "debate_id": did,
                    "title": debate.title or "Untitled debate",
                    "owner_email": email,
                    "kind": "debate",
                    "status": debate.status,
                    "step": debate_step(
                        debate.config_json or {}, int(saved.get(debate.id, 0)), debate.status
                    ),
                    "age_seconds": (now - since).total_seconds(),
                    "heartbeat": beat,
                    "waiting": waiting,
                    "attempts": int(await redis.get(recovery_key("attempts:debate", did)) or 0),
                    "stuck": is_stuck(now - since, beat, waiting),
                }
            )
        if debate.media_status in ACTIVE:
            state = debate.media_json or {}
            started = state.get("started_at") or state.get("queued_at")
            try:
                since = _aware(datetime.fromisoformat(str(started))) if started else None
            except ValueError:
                since = None
            since = since or _aware(debate.ended_at) or now
            beat = bool(await redis.exists(media_beat_key(did)))
            waiting = did in media_waiting
            out.append(
                {
                    "debate_id": did,
                    "title": debate.title or "Untitled debate",
                    "owner_email": email,
                    "kind": "media",
                    "status": debate.media_status,
                    "step": media_step(state),
                    "age_seconds": (now - since).total_seconds(),
                    "heartbeat": beat,
                    "waiting": waiting,
                    "attempts": int(await redis.get(recovery_key("attempts:media", did)) or 0),
                    "stuck": is_stuck(now - since, beat, waiting),
                }
            )
    return out


# --- limits -----------------------------------------------------------------------------------


def free_model_filter() -> Any:
    return (ProviderUsage.model.like("%:free")) | (ProviderUsage.model == "openrouter/free")


def free_daily_cap(total_credits: float | None) -> int:
    return FREE_DAILY_CAP_PAID if (total_credits or 0) >= 10 else FREE_DAILY_CAP_FREE


def parse_refusals(
    members: Iterable[tuple[Any, float]],
) -> dict[tuple[str, str], tuple[int, float]]:
    """`kind:user:nonce` members -> {(kind, user id): (count, last time)}."""
    out: dict[tuple[str, str], tuple[int, float]] = {}
    for raw, score in members:
        member = raw.decode() if isinstance(raw, bytes) else str(raw)
        parts = member.split(":")
        if len(parts) < 2:
            continue
        key = (parts[0], parts[1])
        count, last = out.get(key, (0, 0.0))
        out[key] = (count + 1, max(last, float(score)))
    return out


async def limits(
    db: AsyncSession, redis: AsyncRedis, now: datetime, total_credits: float | None
) -> dict[str, Any]:
    day_ago = now - timedelta(hours=24)
    used = await redis.get(free_models_window_key(int(now.timestamp() // 60)))
    calls = (
        await db.execute(
            select(
                func.count(), func.count().filter(ProviderUsage.error_kind == "rate_limited")
            ).where(
                ProviderUsage.created_at >= day_ago,
                ProviderUsage.key_owner == "system",
                ProviderUsage.provider == "openrouter",
                free_model_filter(),
            )
        )
    ).one()
    at_limit: list[dict[str, Any]] = []
    for kind, column, cap in (
        ("debate", Debate.status, settings.MAX_ACTIVE_DEBATES_PER_USER),
        ("media", Debate.media_status, settings.MAX_ACTIVE_MEDIA_PER_USER),
    ):
        if cap <= 0:
            continue
        rows = await db.execute(
            select(Debate.user_id, User.email, func.count())
            .join(User, User.id == Debate.user_id)
            .where(column.in_(ACTIVE))
            .group_by(Debate.user_id, User.email)
            .having(func.count() >= cap)
        )
        at_limit += [
            {
                "user_id": str(uid),
                "email": email,
                "kind": kind,
                "active": int(n),
                "refusals": 0,
                "last_refused_at": None,
            }
            for uid, email, n in rows.all()
        ]
    members: Any = await redis.zrangebyscore(
        REFUSALS_KEY, now.timestamp() - REFUSALS_SECONDS, "+inf", withscores=True
    )
    grouped = parse_refusals(members)
    emails: dict[str, str] = {}
    ids = []
    for _, uid in grouped:
        try:
            ids.append(uuid.UUID(uid))
        except ValueError:
            continue
    if ids:
        emails = {
            str(uid): email
            for uid, email in (
                await db.execute(select(User.id, User.email).where(User.id.in_(ids)))
            ).all()
        }
    refused = [
        {
            "user_id": uid,
            "email": emails.get(uid),
            "kind": kind,
            "active": None,
            "refusals": count,
            "last_refused_at": datetime.fromtimestamp(last, UTC),
        }
        for (kind, uid), (count, last) in sorted(grouped.items(), key=lambda i: -i[1][1])
    ]
    return {
        "free_per_minute": settings.FREE_MODELS_PER_MINUTE,
        "free_used_this_minute": int(used or 0),
        "free_requests_24h": int(calls[0] or 0),
        "free_rate_limited_24h": int(calls[1] or 0),
        "free_daily_cap": free_daily_cap(total_credits),
        "max_debates_per_user": settings.MAX_ACTIVE_DEBATES_PER_USER,
        "max_media_per_user": settings.MAX_ACTIVE_MEDIA_PER_USER,
        "debate_create_rate_limit": settings.DEBATE_CREATE_RATE_LIMIT,
        "login_rate_limit": settings.LOGIN_RATE_LIMIT,
        "at_limit_now": at_limit,
        "refused_24h": refused,
    }


# --- health -----------------------------------------------------------------------------------


async def database_health(db: AsyncSession) -> dict[str, Any]:
    try:
        started = time.perf_counter()
        await db.execute(text("SELECT 1"))
        latency = (time.perf_counter() - started) * 1000
        size = await db.scalar(text("SELECT pg_database_size(current_database())"))
        connections = await db.scalar(
            text("SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()")
        )
        tables = (
            await db.execute(
                text(
                    "SELECT relname, pg_total_relation_size(relid), n_live_tup "
                    "FROM pg_stat_user_tables ORDER BY 2 DESC LIMIT 12"
                )
            )
        ).all()
    except Exception as exc:
        return {
            "ok": False,
            "latency_ms": None,
            "bytes": None,
            "connections": None,
            "tables": [],
            "error": str(exc)[:300],
        }
    return {
        "ok": True,
        "latency_ms": round(latency, 2),
        "bytes": int(size or 0),
        "connections": int(connections or 0),
        "tables": [{"name": n, "bytes": int(b or 0), "rows": int(r or 0)} for n, b, r in tables],
    }


async def redis_health(redis: AsyncRedis) -> dict[str, Any]:
    try:
        started = time.perf_counter()
        await redis.ping()
        latency = (time.perf_counter() - started) * 1000
        memory = await redis.info("memory")
        server = await redis.info("server")
        keys = await redis.dbsize()
    except (RedisError, OSError) as exc:
        return {
            "ok": False,
            "latency_ms": None,
            "version": None,
            "uptime_seconds": None,
            "used_memory": None,
            "peak_memory": None,
            "max_memory": None,
            "keys": None,
            "error": str(exc)[:300],
        }
    return {
        "ok": True,
        "latency_ms": round(latency, 2),
        "version": str(server.get("redis_version") or ""),
        "uptime_seconds": int(server.get("uptime_in_seconds") or 0),
        "used_memory": int(memory.get("used_memory") or 0),
        "peak_memory": int(memory.get("used_memory_peak") or 0),
        "max_memory": int(memory.get("maxmemory") or 0) or None,
        "keys": int(keys or 0),
    }


@dataclass(frozen=True)
class Folder:
    name: str
    bytes: int
    files: int
    modified: float


def folder_size(path: Path) -> tuple[int, int]:
    total = files = 0
    for root, _dirs, names in os.walk(path):
        for name in names:
            try:
                total += (Path(root) / name).stat().st_size
                files += 1
            except OSError:
                continue
    return total, files


def scan_media_sync(root: Path) -> tuple[list[Folder], dict[str, int | None]]:
    """Top-level folders of MEDIA_ROOT (one per debate) with their size, and the disk."""
    folders: list[Folder] = []
    if root.exists():
        for entry in root.iterdir():
            if entry.is_dir():
                size, files = folder_size(entry)
                folders.append(Folder(entry.name, size, files, entry.stat().st_mtime))
    try:
        usage = shutil.disk_usage(root if root.exists() else root.parent)
        disk: dict[str, int | None] = {
            "total": usage.total,
            "used": usage.used,
            "free": usage.free,
        }
    except OSError:
        disk = {"total": None, "used": None, "free": None}
    return folders, disk


def debate_folder_id(name: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(name)
    except ValueError:
        return None


def orphans(folders: Iterable[Folder], existing: set[str], now: float) -> list[Folder]:
    """Debate-named folders whose debate is gone, untouched for an hour (a debate being created
    or deleted right now is never one)."""
    cutoff = now - ORPHAN_MIN_AGE.total_seconds()
    return [
        f
        for f in folders
        if debate_folder_id(f.name) is not None
        and str(debate_folder_id(f.name)) not in existing
        and f.modified < cutoff
    ]


async def existing_debates(db: AsyncSession, names: Iterable[str]) -> dict[str, str]:
    ids = [i for i in (debate_folder_id(n) for n in names) if i is not None]
    if not ids:
        return {}
    rows = await db.execute(select(Debate.id, Debate.title).where(Debate.id.in_(ids)))
    return {str(did): title or "Untitled debate" for did, title in rows.all()}


async def media_health(
    db: AsyncSession, redis: AsyncRedis, *, refresh: bool, now: datetime
) -> dict[str, Any]:
    root = settings.media_root_path
    if not refresh:
        try:
            cached = await redis.get(MEDIA_CACHE_KEY)
            if cached:
                return json.loads(cached)
        except (RedisError, ValueError):
            pass
    folders, disk = await run_in_threadpool(scan_media_sync, root)
    titles = await existing_debates(db, (f.name for f in folders))
    lost = orphans(folders, set(titles), now.timestamp())

    def out(f: Folder) -> dict[str, Any]:
        did = debate_folder_id(f.name)
        return {
            "name": f.name,
            "bytes": f.bytes,
            "files": f.files,
            "title": titles.get(str(did)) if did else None,
        }

    heaviest = sorted(folders, key=lambda f: f.bytes, reverse=True)[:HEAVIEST]
    result = {
        "root": str(root),
        "disk_total": disk["total"],
        "disk_used": disk["used"],
        "disk_free": disk["free"],
        "bytes": sum(f.bytes for f in folders),
        "dirs": len(folders),
        "heaviest": [out(f) for f in heaviest],
        "orphans": [out(f) for f in sorted(lost, key=lambda f: f.bytes, reverse=True)],
        "orphan_bytes": sum(f.bytes for f in lost),
        "scanned_at": now.isoformat(),
    }
    with contextlib.suppress(RedisError):
        await redis.set(MEDIA_CACHE_KEY, json.dumps(result), ex=MEDIA_CACHE_SECONDS)
    return result


def delete_folders_sync(root: Path, names: list[str]) -> int:
    """Remove the named debate folders (names already checked); returns the bytes freed."""
    freed = 0
    for name in names:
        path = root / str(uuid.UUID(name))  # never a path from the request itself
        if path.is_dir() and path.parent == root:
            size, _ = folder_size(path)
            shutil.rmtree(path, ignore_errors=True)
            freed += size
    return freed


def alembic_head() -> str | None:
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        ini = Path(__file__).resolve().parents[3] / "alembic.ini"
        config = Config(str(ini))
        config.set_main_option("script_location", str(ini.parent / "migrations"))
        return ScriptDirectory.from_config(config).get_current_head()
    except Exception:
        return None


async def alembic_current(db: AsyncSession) -> str | None:
    try:
        return await db.scalar(text("SELECT version_num FROM alembic_version"))
    except Exception:
        return None


def config_flags() -> list[dict[str, str]]:
    """Settings worth seeing on the page; secrets only as set / not set."""

    def present(value: str | None) -> str:
        return "set" if value else "not set"

    flags: list[tuple[str, Any]] = [
        ("ENVIRONMENT", settings.ENVIRONMENT),
        ("ADMIN_HOST", present(settings.ADMIN_HOST)),
        ("ADMIN_ALLOWED_IPS", present(settings.ADMIN_ALLOWED_IPS)),
        ("ADMIN_SUDO_USD", settings.ADMIN_SUDO_USD),
        ("OPENROUTER_API_KEY", present(settings.OPENROUTER_API_KEY)),
        ("ELEVENLABS_API_KEY", present(settings.ELEVENLABS_API_KEY)),
        ("STRIPE_SECRET_KEY", present(settings.STRIPE_SECRET_KEY)),
        ("MEDIA_API_TOKEN", present(settings.MEDIA_API_TOKEN)),
        ("DEV_FAKE_PAYMENTS", settings.DEV_FAKE_PAYMENTS),
        ("SIGNUP_BONUS_USD", settings.SIGNUP_BONUS_USD),
        ("CREDIT_MARKUP", settings.CREDIT_MARKUP),
        ("TTS_CREDIT_PRICE_PER_1K_CHARS", settings.TTS_CREDIT_PRICE_PER_1K_CHARS),
        ("FREE_MODELS_PER_MINUTE", settings.FREE_MODELS_PER_MINUTE),
        ("MAX_ACTIVE_DEBATES_PER_USER", settings.MAX_ACTIVE_DEBATES_PER_USER),
        ("MAX_ACTIVE_MEDIA_PER_USER", settings.MAX_ACTIVE_MEDIA_PER_USER),
        ("DEBATE_CREATE_RATE_LIMIT", settings.DEBATE_CREATE_RATE_LIMIT),
        ("LOGIN_RATE_LIMIT", settings.LOGIN_RATE_LIMIT),
        ("TRENDING_REFRESH_HOURS", settings.TRENDING_REFRESH_HOURS),
        ("RECOVERY_ATTEMPTS", settings.RECOVERY_ATTEMPTS),
        ("TURN_JOB_TIMEOUT", settings.TURN_JOB_TIMEOUT),
        ("MEDIA_JOB_TIMEOUT", settings.MEDIA_JOB_TIMEOUT),
        ("MEDIA_ROOT", settings.MEDIA_ROOT),
        ("SITE_URL", settings.SITE_URL),
    ]
    return [{"name": name, "value": str(value)} for name, value in flags]


async def last_backup(redis: AsyncRedis) -> dict[str, Any] | None:
    try:
        raw = await redis.get("backup:last")
        return json.loads(raw) if raw else None
    except (RedisError, ValueError):
        return None
