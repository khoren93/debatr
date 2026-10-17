"""Heartbeats of running jobs, so a run whose worker died can be told from a slow one.

A job holds `heartbeat(key)` while it runs: a daemon thread refreshes the Redis key every
`EVERY` seconds with a short TTL. It keeps beating while the job waits on a model, and stops
with the job, whether it ends, raises, is killed by RQ's timeout or dies with its process. So a
missing key means no job is working on that run right now (services/recovery).
"""

import functools
import logging
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from app.core.redis import get_sync_redis

logger = logging.getLogger(__name__)

EVERY = 20.0  # seconds between beats
TTL = 60  # seconds a beat lasts: three missed beats


@contextmanager
def heartbeat(key: str) -> Iterator[None]:
    stop = threading.Event()

    def beat() -> None:
        while True:
            try:
                get_sync_redis().set(key, "1", ex=TTL)
            except Exception:
                logger.warning("Heartbeat %s failed", key)
            if stop.wait(EVERY):
                return

    thread = threading.Thread(target=beat, name=f"heartbeat {key}", daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=2)


def beating[**P, R](key_of: Callable[[str], str]) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Decorate an RQ job whose first argument (or `debate_id`) is a debate id."""

    def wrap(job: Callable[P, R]) -> Callable[P, R]:
        @functools.wraps(job)
        def run(*args: P.args, **kwargs: P.kwargs) -> R:
            debate_id = str(kwargs.get("debate_id") or (args[0] if args else ""))
            with heartbeat(key_of(debate_id)):
                return job(*args, **kwargs)

        return run

    return wrap


def alive(key: str) -> bool:
    return bool(get_sync_redis().exists(key))
