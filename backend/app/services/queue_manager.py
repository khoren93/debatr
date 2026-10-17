"""RQ job enqueueing. Job functions are referenced by dotted path so the API
never imports the worker-only orchestrator / media modules."""

from rq import Queue

from app.core.config import settings
from app.core.redis import get_sync_redis

QUEUE_NAME = "default"  # debate turns
# Trending topics and recovery checks: served by the turn workers only when no turn waits.
BACKGROUND_QUEUE_NAME = "background"
MEDIA_QUEUE_NAME = "media"  # TTS / timeline builds (long-running, separate worker)

_ORCHESTRATOR = "app.services.orchestrator"
_MEDIA_JOBS = "app.services.media.jobs"
_TRENDING = "app.services.trending"


def get_queue(name: str = QUEUE_NAME) -> Queue:
    return Queue(name, connection=get_sync_redis())


def _enqueue(func_path: str, *, queue_name: str, timeout: int, **kwargs: object) -> None:
    get_queue(queue_name).enqueue(
        func_path,
        job_timeout=timeout,
        result_ttl=300,
        failure_ttl=3600,
        **kwargs,
    )


def _enqueue_debate(func_name: str, **kwargs: object) -> None:
    _enqueue(
        f"{_ORCHESTRATOR}.{func_name}",
        queue_name=QUEUE_NAME,
        timeout=settings.TURN_JOB_TIMEOUT,
        **kwargs,
    )


def enqueue_debate_start(debate_id: str, from_seq: int = 0) -> None:
    """Queue a run; `from_seq` resumes a failed debate from that turn."""
    if from_seq:
        _enqueue_debate("start_debate_job", debate_id=debate_id, from_seq=from_seq)
    else:
        _enqueue_debate("start_debate_job", debate_id=debate_id)


def enqueue_turn(debate_id: str, seq_index: int) -> None:
    _enqueue_debate("process_turn_job", debate_id=debate_id, seq_index=seq_index)


def enqueue_verdict(debate_id: str, seq_index: int) -> None:
    _enqueue_debate("conduct_verdict_job", debate_id=debate_id, seq_index=seq_index)


def enqueue_finish(debate_id: str) -> None:
    _enqueue_debate("finish_debate_job", debate_id=debate_id)


def enqueue_media_build(debate_id: str) -> None:
    _enqueue(
        f"{_MEDIA_JOBS}.build_media_job",
        queue_name=MEDIA_QUEUE_NAME,
        timeout=settings.MEDIA_JOB_TIMEOUT,
        debate_id=debate_id,
    )


def enqueue_trending_refresh(force: bool = False) -> None:
    """Build a new trending-topics batch if one is due (`force`: now)."""
    _enqueue(
        f"{_TRENDING}.refresh_trending_job",
        queue_name=BACKGROUND_QUEUE_NAME,
        timeout=900,  # trending.JOB_TIMEOUT
        force=force,
    )
