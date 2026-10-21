"""RQ worker entrypoint: `python -m app.worker [--queues default,media] [--simple]`.

By default one worker serves both queues (fine for local dev). In Docker the
`worker` container listens to `default` and `media-worker` to `media`, so a long
TTS build never blocks debate turns.
"""

import argparse
import logging

from rq import Queue, SimpleWorker, Worker

from app.core.config import settings
from app.core.logging import setup_logging
from app.core.redis import get_sync_redis

logger = logging.getLogger(__name__)


def parse_queue_names(raw: str | None) -> list[str]:
    names = [q.strip() for q in (raw or "").split(",") if q.strip()]
    return names or list(settings.rq_queue_names)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Debatr RQ worker")
    parser.add_argument("--queues", default=None, help="comma-separated queue names")
    parser.add_argument("--simple", action="store_true", help="run jobs in-process (no fork)")
    args = parser.parse_args(argv)

    setup_logging()
    conn = get_sync_redis()
    conn.ping()
    names = parse_queue_names(args.queues)
    queues = [Queue(name, connection=conn) for name in names]
    # SimpleWorker runs jobs in-process (no fork). Handy on macOS for local dev.
    worker_cls = SimpleWorker if (args.simple or settings.RQ_SIMPLE_WORKER) else Worker
    worker = worker_cls(queues, connection=conn)
    logger.info("Starting %s on queues %s", worker_cls.__name__, ", ".join(names))
    worker.work(with_scheduler=False)


if __name__ == "__main__":
    main()
