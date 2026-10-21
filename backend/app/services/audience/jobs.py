"""The visits' upkeep (scheduler, hourly on the background queue): forget IPs and User-Agents
older than the `analytics_ip_days` lever, fetch the monthly GeoIP releases when they are due,
and place visits that arrived while there was no database (their network too, weighing their
verdict again). `classify` weighs stored visits again (`python -m app.manage audience classify`:
visits from before the verdicts, or after the rules changed)."""

import logging
from datetime import datetime, timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.core.redis import get_sync_redis
from app.core.sync_db import get_sync_session
from app.models.models import Visit, utcnow
from app.services import runtime_settings
from app.services.audience import bots, geo
from app.services.audience.collect import crowd_query, visit_facts

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


def assess(db: Session, visit: Visit) -> bots.Assessment:
    """The stored visit's verdict as of its last beacon (its network looked up again while the
    IP is kept)."""
    if visit.ip and visit.network is None:
        net = geo.network(visit.ip)
        if net is not None:
            visit.network = net.org
            visit.network_kind = bots.network_kind(net.asn, net.org)
    srv = (visit.signals or {}).get("srv") or {}
    if visit.ip and "lon" not in srv:
        place = geo.lookup(visit.ip)
        if place is not None and place.longitude is not None:
            srv = {**srv, "lon": round(place.longitude, 1)}
            visit.signals = {**(visit.signals or {}), "srv": srv}
    at = visit.last_at
    crowd = int(db.scalar(crowd_query(visit, at)) or 0) if visit.ip else 0
    return bots.classify(visit_facts(visit, at=at, crowd=crowd))


def classify(db: Session, *, since: datetime | None = None, batch: int = 500) -> int:
    """Weigh every visit (that started after `since`) again; the number of visits."""
    done = 0
    last: tuple[datetime, object] | None = None
    while True:
        query = select(Visit).order_by(Visit.started_at, Visit.id).limit(batch)
        if since is not None:
            query = query.where(Visit.started_at >= since)
        if last is not None:
            query = query.where(
                or_(
                    Visit.started_at > last[0],
                    (Visit.started_at == last[0]) & (Visit.id > last[1]),
                )
            )
        visits = db.scalars(query).all()
        if not visits:
            return done
        for visit in visits:
            result = assess(db, visit)
            visit.verdict = result.verdict
            visit.bot_score = result.score
            visit.bot_reasons = result.stored_reasons()
        db.commit()
        done += len(visits)
        last = (visits[-1].started_at, visits[-1].id)


def backfill_networks(db: Session) -> int:
    """Networks of visits saved without one (no database then), while they still have their IP;
    their verdicts are weighed again with it."""
    visits = db.scalars(
        select(Visit)
        .where(Visit.network.is_(None), Visit.ip.is_not(None))
        .order_by(Visit.started_at.desc())
        .limit(BACKFILL_LIMIT)
    ).all()
    found = 0
    for visit in visits:
        result = assess(db, visit)
        if visit.network is None:
            continue
        visit.verdict = result.verdict
        visit.bot_score = result.score
        visit.bot_reasons = result.stored_reasons()
        found += 1
    db.commit()
    return found


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
        for database in geo.DATABASES:
            if geo.update_due(db=database):
                geo.update(db=database)
        if geo.database_path(geo.CITY).exists():
            with get_sync_session() as db:
                placed = backfill(db)
            if placed:
                logger.info("Placed %d visits on the map", placed)
        if geo.database_path(geo.ASN).exists():
            with get_sync_session() as db:
                found = backfill_networks(db)
            if found:
                logger.info("Found the network of %d visits", found)
    finally:
        redis.delete(LOCK_KEY)
