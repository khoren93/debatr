"""Runs whose worker died, found and queued again (the scheduler enqueues `recover_runs_job`
every minute on the background queue).

A debate that is queued or running, or an audio build that is queued or running, is orphaned
when no job holds its heartbeat (services/heartbeat) and none waits for it in its queue: its
worker was killed (a deploy that could not wait, a crash, out of memory) or Redis lost the job.
It has to look orphaned on two checks in a row, a minute apart, so a run that is between two
jobs is never touched. Then it is queued again from where it stopped: turns are saved one by one,
so a debate goes on from its first missing turn (`resume.resume_point`), and an audio build
reuses the turns it already voiced. After RECOVERY_ATTEMPTS, for runs older than MAX_AGE, or
when the debate's own OpenRouter key has expired meanwhile, the debate fails with a message and
waits for Resume; an audio build fails and can be generated again.
"""

import logging
import uuid
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from typing import Any, Literal

from redis import Redis
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.redis import (
    debate_beat_key,
    get_sync_redis,
    media_beat_key,
    provider_key_key,
    recovery_key,
)
from app.core.sync_db import get_sync_session
from app.models.models import Debate, Turn, utcnow
from app.services import queue_manager
from app.services.heartbeat import alive
from app.services.media.state import set_media_state
from app.services.orchestrator import fail_debate
from app.services.resume import discarded, resume_point
from app.services.scheduler import build_schedule

logger = logging.getLogger(__name__)

ACTIVE = ("queued", "running")
SEEN_TTL = 300  # an orphan seen once is acted on if it is still one at the next check
ATTEMPTS_TTL = 86400
MAX_AGE = timedelta(hours=6)  # older runs are not run again on their own (they may cost)
LOCK_KEY = "recovery:lock"
LOCK_TTL = 50
JOB_TIMEOUT = 120

Step = Literal["start", "turn", "verdict", "finish"]


# --- decisions (pure) ------------------------------------------------------------------------


def next_step(status: str, turns: Sequence[Turn], schedule_length: int) -> tuple[Step, int]:
    """Where an orphaned debate goes on: its start job, the first missing turn, the verdict
    (index `schedule_length`) or the final job."""
    from_seq = resume_point(turns)
    if status == "queued":
        return "start", from_seq
    if from_seq < schedule_length:
        return "turn", from_seq
    if from_seq == schedule_length:
        return "verdict", from_seq
    return "finish", from_seq


def give_up_reason(
    attempts: int, started_at: datetime | None, *, key_lost: bool, now: datetime
) -> str | None:
    """Why an orphaned run is failed instead of queued again (None: queue it again)."""
    if attempts > settings.RECOVERY_ATTEMPTS:
        return "it was interrupted again"
    if started_at is not None and now - started_at > MAX_AGE:
        return "it was interrupted long ago"
    if key_lost:
        return "your OpenRouter key expired meanwhile: resume it with the key"
    return None


def _parse_time(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


# --- Redis -------------------------------------------------------------------------------------


def _orphan_confirmed(redis: Redis, kind: str, debate_id: str, busy: bool) -> bool:
    """True on the second check in a row that finds the run without a job."""
    key = recovery_key(f"seen:{kind}", debate_id)
    if busy:
        redis.delete(key)
        return False
    if redis.set(key, "1", ex=SEEN_TTL, nx=True):
        return False  # first sighting: look again at the next check
    redis.delete(key)
    return True


def _attempt(redis: Redis, kind: str, debate_id: str) -> int:
    key = recovery_key(f"attempts:{kind}", debate_id)
    attempts = int(redis.incr(key))
    redis.expire(key, ATTEMPTS_TTL)
    return attempts


# --- recovery ----------------------------------------------------------------------------------


def _recover_debate(db: Session, redis: Redis, debate: Debate) -> None:
    debate_id = str(debate.id)
    conf: dict[str, Any] = debate.config_json or {}
    own_key = bool((conf.get("billing") or {}).get("own_key"))
    reason = give_up_reason(
        _attempt(redis, "debate", debate_id),
        debate.started_at or debate.created_at,
        key_lost=own_key and not redis.exists(provider_key_key(debate_id)),
        now=utcnow(),
    )
    if reason:
        logger.warning("Debate %s lost its worker; failing it: %s", debate_id, reason)
        fail_debate(db, debate, f"The server stopped while running this debate ({reason}).")
        return
    schedule = build_schedule(conf.get("participants", []), int(conf.get("num_rounds") or 1))
    step, from_seq = next_step(debate.status, debate.turns, len(schedule))
    if step in ("turn", "verdict"):
        # A turn the dead worker left half-saved (failed or empty) runs again.
        dropped, cost = discarded(debate.turns, from_seq)
        for turn in dropped:
            db.delete(turn)
        if cost:
            totals = dict(debate.totals_json or {})
            totals["discarded_cost"] = round(float(totals.get("discarded_cost") or 0) + cost, 6)
            debate.totals_json = totals
        db.commit()
    logger.warning(
        "Debate %s lost its worker; queuing its %s (%s) again", debate_id, step, from_seq
    )
    if step == "start":
        queue_manager.enqueue_debate_start(debate_id, from_seq)
    elif step == "turn":
        queue_manager.enqueue_turn(debate_id, from_seq)
    elif step == "verdict":
        queue_manager.enqueue_verdict(debate_id, from_seq)
    else:
        queue_manager.enqueue_finish(debate_id)


def _recover_media(db: Session, redis: Redis, debate: Debate) -> None:
    debate_id = str(debate.id)
    state = dict(debate.media_json or {})
    # A build that never started was asked for just now: no age limit for it.
    started = _parse_time(state.get("started_at"))
    reason = give_up_reason(
        _attempt(redis, "media", debate_id), started, key_lost=False, now=utcnow()
    )
    if reason:
        logger.warning("Audio build of %s lost its worker; failing it: %s", debate_id, reason)
        set_media_state(
            db,
            debate,
            status="error",
            step="error",
            message="The audio build was interrupted",
            error="The audio build was interrupted: generate it again",
        )
        return
    logger.warning("Audio build of %s lost its worker; queuing it again", debate_id)
    # Turns voiced before the interruption are cached, so the build picks up where it stopped.
    set_media_state(db, debate, status="queued", step="queued", message="Queued again")
    queue_manager.enqueue_media_build(debate_id)


def _sweep(
    db: Session,
    redis: Redis,
    kind: str,
    debates: Sequence[Debate],
    waiting: set[str],
    beat_key: Callable[[str], str],
    recover: Callable[[Session, Redis, Debate], None],
) -> None:
    for debate in debates:
        debate_id = str(debate.id)
        busy = debate_id in waiting or alive(beat_key(debate_id))
        if not _orphan_confirmed(redis, kind, debate_id, busy):
            continue
        try:
            recover(db, redis, debate)
        except Exception:
            logger.exception("Could not recover the %s of debate %s", kind, debate_id)
            db.rollback()


def recover_runs_job() -> None:
    redis = get_sync_redis()
    if not redis.set(LOCK_KEY, "1", ex=LOCK_TTL, nx=True):
        return  # another check is running
    turns_waiting = queue_manager.waiting_debates(redis, queue_manager.QUEUE_NAME)
    media_waiting = queue_manager.waiting_debates(redis, queue_manager.MEDIA_QUEUE_NAME)
    with get_sync_session() as db:
        running = db.scalars(select(Debate).where(Debate.status.in_(ACTIVE))).all()
        _sweep(db, redis, "debate", running, turns_waiting, debate_beat_key, _recover_debate)
        building = db.scalars(select(Debate).where(Debate.media_status.in_(ACTIVE))).all()
        _sweep(db, redis, "media", building, media_waiting, media_beat_key, _recover_media)


def recover_now(debate_id: str, kind: str) -> str:
    """For the admin console: queue a run whose worker is gone again at once, without waiting
    for the second check in a row. Raises LookupError for an unknown debate and ValueError when
    the run is not queued / running, still has a worker or a job waiting. Returns what happened
    (the run's status after it)."""
    redis = get_sync_redis()
    is_debate = kind == "debate"
    queue = queue_manager.QUEUE_NAME if is_debate else queue_manager.MEDIA_QUEUE_NAME
    beat_key = debate_beat_key if is_debate else media_beat_key
    with get_sync_session() as db:
        debate = db.get(Debate, uuid.UUID(debate_id))
        if debate is None:
            raise LookupError(debate_id)
        status = debate.status if is_debate else debate.media_status
        if status not in ACTIVE:
            raise ValueError(f"It is {status}, not queued or running")
        if alive(beat_key(debate_id)):
            raise ValueError("A worker is on it right now")
        if debate_id in queue_manager.waiting_debates(redis, queue):
            raise ValueError("Its job is waiting in the queue")
        redis.delete(recovery_key(f"seen:{kind}", debate_id))
        (_recover_debate if is_debate else _recover_media)(db, redis, debate)
        db.refresh(debate)
        return debate.status if is_debate else debate.media_status
