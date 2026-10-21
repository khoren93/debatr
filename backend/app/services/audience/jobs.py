"""The visits' upkeep (scheduler, hourly on the background queue): forget IPs and User-Agents
older than the `analytics_ip_days` lever, fetch the monthly GeoIP release when one is due, and
place visits that arrived while there was no database."""

import logging
from datetime import timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.core.redis import get_sync_redis
from app.core.sync_db import get_sync_session
from app.models.models import Visit, utcnow
from app.services import runtime_settings
from app.services.audience import geo

logger = logging.getLogger(__name__)

TICK_SECONDS = 3600
JOB_TIMEOUT = 900
LOCK_KEY = "audience:maintenance:lock"
BACKFILL_LIMIT = 5000


def forget_old_addresses(db: Session, days: int) -> int:
    """Clear the IP and User-Agent of visits that started more than `days` ago (0: keep)."""
    if days <= 0:
        return 0
    cutoff = utcnow() - timedelta(days=days)
    result = db.execute(
        update(Visit)
        .where(
            Visit.started_at < cutoff,
            or_(Visit.ip.is_not(None), Visit.user_agent.is_not(None)),
        )
        .values(ip=None, user_agent=None)
    )
    db.commit()
    return int(getattr(result, "rowcount", 0) or 0)


def backfill(db: Session) -> int:
    """Places of visits saved without one (no database then), while they still have their IP."""
    rows = db.execute(
        select(Visit.id, Visit.ip)
        .where(Visit.country.is_(None), Visit.region.is_(None), Visit.ip.is_not(None))
        .order_by(Visit.started_at.desc())
        .limit(BACKFILL_LIMIT)
    ).all()
    placed = 0
    for visit_id, ip in rows:
        place = geo.lookup(ip)
        if place is None:
            continue
        db.execute(
            update(Visit)
            .where(Visit.id == visit_id)
            .values(country=place.country, region=place.region, city=place.city)
        )
        placed += 1
    db.commit()
    return placed


def maintenance_job() -> None:
    redis = get_sync_redis()
    if not redis.set(LOCK_KEY, "1", nx=True, ex=JOB_TIMEOUT):
        return
    try:
        levers = runtime_settings.current_sync()
        with get_sync_session() as db:
            forgotten = forget_old_addresses(db, levers.analytics_ip_days)
        if forgotten:
            logger.info("Cleared the IP of %d visits", forgotten)
        if geo.update_due():
            geo.update()
        if geo.database_path().exists():
            with get_sync_session() as db:
                placed = backfill(db)
            if placed:
                logger.info("Placed %d visits on the map", placed)
    finally:
        redis.delete(LOCK_KEY)
