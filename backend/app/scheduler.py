"""Periodic jobs: `python -m app.scheduler` (one process; the `scheduler` service in Docker).

RQ's cron scheduler only enqueues: the workers run the jobs, from the background queue, after
any waiting turn. The trending-topics refresh is enqueued every hour and decides itself whether
a new batch is due (TRENDING_REFRESH_HOURS), so a restart never builds an extra batch. The
recovery check (services/recovery) runs every minute and queues again the runs whose worker
died. The alerts check (services/alerts) runs every five minutes, the IndexNow flush
(services/indexnow, production only) every minute. `--refresh-trending` builds a batch right now,
in-process.
"""

import argparse
import logging

from redis import Redis
from rq.cron import CronScheduler

from app.core.config import settings
from app.core.logging import setup_logging
from app.core.redis import get_sync_redis
from app.services import alerts, indexnow, recovery
from app.services.queue_manager import BACKGROUND_QUEUE_NAME
from app.services.trending import JOB_TIMEOUT, refresh_trending_job

logger = logging.getLogger(__name__)

TRENDING_TICK_SECONDS = 3600
RECOVERY_TICK_SECONDS = 60


def build_scheduler(conn: Redis) -> CronScheduler:
    cron = CronScheduler(connection=conn, logging_level=settings.LOG_LEVEL)
    cron.register(
        refresh_trending_job,
        queue_name=BACKGROUND_QUEUE_NAME,
        interval=TRENDING_TICK_SECONDS,
        job_timeout=JOB_TIMEOUT,
        result_ttl=300,
    )
    cron.register(
        recovery.recover_runs_job,
        queue_name=BACKGROUND_QUEUE_NAME,
        interval=RECOVERY_TICK_SECONDS,
        job_timeout=recovery.JOB_TIMEOUT,
        result_ttl=60,
    )
    cron.register(
        alerts.check_alerts_job,
        queue_name=BACKGROUND_QUEUE_NAME,
        interval=alerts.CHECK_SECONDS,
        job_timeout=alerts.JOB_TIMEOUT,
        result_ttl=60,
    )
    if indexnow.enabled():
        cron.register(
            indexnow.flush_job,
            queue_name=BACKGROUND_QUEUE_NAME,
            interval=indexnow.FLUSH_SECONDS,
            job_timeout=indexnow.JOB_TIMEOUT,
            result_ttl=60,
        )
    return cron


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="AI Debates periodic jobs")
    parser.add_argument(
        "--refresh-trending", action="store_true", help="build a trending batch now and exit"
    )
    args = parser.parse_args(argv)

    setup_logging()
    if args.refresh_trending:
        refresh_trending_job(force=True)
        return
    conn = get_sync_redis()
    conn.ping()
    logger.info(
        "Starting the scheduler (trending check every %d s, recovery every %d s, alerts every %d s)",
        TRENDING_TICK_SECONDS,
        RECOVERY_TICK_SECONDS,
        alerts.CHECK_SECONDS,
    )
    build_scheduler(conn).start()


if __name__ == "__main__":
    main()
