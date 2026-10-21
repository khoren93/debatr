"""Numbers of the console's Audience page: visits of the site (services/audience) in a period,
where they came from, where they are, what they looked at and did; one visit with its pages and
actions; an account's visits and the addresses it shares with other accounts.

Read-only queries. Visits of console staff are left out unless asked for. A visit belongs to the
period it started in; pages and actions to the moment they happened.
"""

import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Integer, String, and_, case, cast, distinct, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.models.models import Debate, User, Visit, VisitEvent
from app.schemas.admin import (
    AddressRow,
    AudienceCampaign,
    AudiencePage,
    AudiencePoint,
    AudienceRow,
    AudienceVideo,
    FunnelStep,
    SharedAddress,
    VisitCard,
    VisitDetail,
    VisitEventOut,
    VisitList,
    VisitListQuery,
    VisitorSummary,
    VisitRow,
    VisitUser,
)
from app.services import seo
from app.services.admin.stats import Window, _aware, _bucket, bucket_starts, tile
from app.services.audience.collect import ACTIONS
from app.services.views import SOURCES

ONLINE = timedelta(minutes=5)
BOUNCE_MS = 10_000  # one page, looked at for less than this
ENGAGED_MS = 30_000  # the funnel's "stayed": this long, or a second page
TOP = 15

# Parts of the site by path (the console's "Sections" table).
SECTIONS: tuple[tuple[str, str], ...] = (
    ("/d/", "debate"),
    ("/t/", "topic"),
    ("/gallery", "gallery"),
    ("/leaderboard", "ranking"),
    ("/create", "create"),
    ("/library", "library"),
    ("/debate/", "own debate"),
    ("/account", "account"),
    ("/login", "sign-in"),
    ("/register", "sign-in"),
    ("/device", "CLI login"),
    ("/privacy", "privacy"),
)

FUNNEL: tuple[tuple[str, str], ...] = (
    ("visitors", "Visited"),
    ("stayed", "Stayed 30 s or opened a second page"),
    ("watched", "Played a video"),
    ("signup", "Created an account"),
    ("debate_start", "Started a debate"),
    ("topup", "Topped up"),
)


def bounced() -> ColumnElement[bool]:
    return and_(Visit.pageviews <= 1, Visit.engaged_ms < BOUNCE_MS)


def did(name: str) -> ColumnElement[bool]:
    """The visit had this action."""
    return exists().where(VisitEvent.visit_id == Visit.id, VisitEvent.name == name)


def scope(start: datetime | None, end: datetime, staff: bool = False) -> list[ColumnElement[bool]]:
    where: list[ColumnElement[bool]] = [Visit.started_at < end]
    if start is not None:
        where.append(Visit.started_at >= start)
    if not staff:
        where.append(Visit.staff.is_(False))
    return where


def section_of() -> ColumnElement[str]:
    path = VisitEvent.path
    return case(
        (path == "/", "home"),
        *[(path.startswith(prefix), name) for prefix, name in SECTIONS],
        else_="other",
    )


async def first_visit(db: AsyncSession) -> datetime | None:
    value = await db.scalar(select(func.min(Visit.started_at)))
    return _aware(value) if value else None


# --- the page -----------------------------------------------------------------------------------


async def tiles(db: AsyncSession, window: Window, now: datetime, staff: bool) -> dict[str, Any]:
    async def measure(start: datetime | None, end: datetime) -> dict[str, float]:
        row = (
            await db.execute(
                select(
                    func.count(distinct(Visit.visitor_id)),
                    func.count(),
                    func.coalesce(func.sum(Visit.pageviews), 0),
                    func.avg(Visit.engaged_ms),
                    func.avg(case((bounced(), 1.0), else_=0.0)),
                    func.count(distinct(case((Visit.new_visitor, Visit.visitor_id)))),
                    func.coalesce(func.sum(case((did("signup"), 1), else_=0)), 0),
                ).where(*scope(start, end, staff))
            )
        ).one()
        keys = ("visitors", "visits", "pageviews", "engaged_ms", "bounce_rate", "new", "signups")
        return {k: float(v or 0) for k, v in zip(keys, row, strict=True)}

    current = await measure(window.start, window.end)
    previous = await measure(window.previous_start, window.start) if window.previous_start else None

    def pair(key: str) -> dict[str, float | None]:
        # An average over no visits is no number to compare with.
        empty = previous is not None and not previous["visits"]
        averaged = key in ("engaged_ms", "bounce_rate")
        return tile(
            current[key], None if previous is None or (empty and averaged) else previous[key]
        )

    online = await db.scalar(
        select(func.count()).where(
            Visit.last_at >= now - ONLINE, *([] if staff else [Visit.staff.is_(False)])
        )
    )
    return {
        "visitors": pair("visitors"),
        "visits": pair("visits"),
        "pageviews": pair("pageviews"),
        "engaged_ms": pair("engaged_ms"),
        "bounce_rate": pair("bounce_rate"),
        "new_visitors": pair("new"),
        "signups": pair("signups"),
        "online": int(online or 0),
    }


async def series(db: AsyncSession, window: Window, staff: bool) -> list[AudiencePoint]:
    bucket = _bucket(Visit.started_at, window.bucket).label("bucket")
    where = scope(window.start, window.end, staff)
    by_source: dict[datetime, dict[str, int]] = {}
    rows = await db.execute(
        select(bucket, Visit.source, func.count()).where(*where).group_by(bucket, Visit.source)
    )
    for t, source, n in rows.all():
        by_source.setdefault(_aware(t), {})[source] = int(n)
    people = await db.execute(
        select(bucket, func.count(distinct(Visit.visitor_id))).where(*where).group_by(bucket)
    )
    visitors = {_aware(t): int(n) for t, n in people.all()}
    points: list[AudiencePoint] = []
    for start in bucket_starts(window):
        sources = by_source.get(start, {})
        points.append(
            AudiencePoint(
                t=start,
                visitors=visitors.get(start, 0),
                visits=sum(sources.values()),
                sources={s: sources.get(s, 0) for s in SOURCES},
            )
        )
    return points


async def breakdown(
    db: AsyncSession,
    where: list[ColumnElement[bool]],
    key: Any,
    label: Any = None,
    *,
    limit: int = TOP,
) -> list[AudienceRow]:
    """Visits grouped by `key` (and `label`), most visits first."""
    k = key.label("k")
    columns: list[Any] = [k] if label is None else [k, label.label("l")]
    visits = func.count().label("n")
    rows = await db.execute(
        select(
            *columns,
            visits,
            func.count(distinct(Visit.visitor_id)),
            func.avg(Visit.engaged_ms),
            func.avg(case((bounced(), 1.0), else_=0.0)),
            func.coalesce(func.sum(case((did("signup"), 1), else_=0)), 0),
        )
        .where(*where)
        .group_by(*columns)
        .order_by(visits.desc(), k)
        .limit(limit)
    )
    out: list[AudienceRow] = []
    for row in rows.all():
        values = list(row)
        key_value = values.pop(0)
        label_value = values.pop(0) if label is not None else None
        n, people, engaged, bounce, signups = values
        out.append(
            AudienceRow(
                key=str(key_value or ""),
                label=str(label_value) if label_value is not None else None,
                visits=int(n),
                visitors=int(people or 0),
                engaged_ms=float(engaged) if engaged is not None else None,
                bounce_rate=float(bounce) if bounce is not None else None,
                signups=int(signups or 0),
            )
        )
    return out


def _event_scope(window: Window, staff: bool, *extra: ColumnElement[bool]) -> list[Any]:
    where: list[Any] = [VisitEvent.at >= window.start, VisitEvent.at < window.end, *extra]
    if not staff:
        where.append(Visit.staff.is_(False))
    return where


async def pages(db: AsyncSession, window: Window, staff: bool) -> list[AudiencePage]:
    views = func.count().label("views")
    rows = await db.execute(
        select(
            VisitEvent.path,
            views,
            func.count(distinct(Visit.visitor_id)),
            func.avg(VisitEvent.engaged_ms),
            func.min(cast(VisitEvent.debate_id, String)),
        )
        .join(Visit, Visit.id == VisitEvent.visit_id)
        .where(*_event_scope(window, staff, VisitEvent.kind == "page"))
        .group_by(VisitEvent.path)
        .order_by(views.desc(), VisitEvent.path)
        .limit(TOP + 5)
    )
    found = rows.all()
    titles = await _titles(db, [d for *_, d in found if d])
    return [
        AudiencePage(
            path=path,
            views=int(n),
            visitors=int(people or 0),
            engaged_ms=float(engaged) if engaged is not None else None,
            title=titles.get(debate_id) if debate_id else None,
        )
        for path, n, people, engaged, debate_id in found
    ]


async def sections(db: AsyncSession, window: Window, staff: bool) -> list[AudienceRow]:
    section = section_of().label("section")
    views = func.count().label("views")
    rows = await db.execute(
        select(
            section,
            views,
            func.count(distinct(Visit.visitor_id)),
            func.avg(VisitEvent.engaged_ms),
        )
        .join(Visit, Visit.id == VisitEvent.visit_id)
        .where(*_event_scope(window, staff, VisitEvent.kind == "page"))
        .group_by(section)
        .order_by(views.desc())
    )
    return [
        AudienceRow(
            key=str(name),
            visits=int(n),
            visitors=int(people or 0),
            engaged_ms=float(engaged) if engaged is not None else None,
        )
        for name, n, people, engaged in rows.all()
    ]


async def _titles(db: AsyncSession, ids: list[str]) -> dict[str, str]:
    valid = []
    for raw in ids:
        try:
            valid.append(uuid.UUID(raw))
        except ValueError:
            continue
    if not valid:
        return {}
    rows = await db.execute(select(Debate.id, Debate.title).where(Debate.id.in_(valid)))
    return {str(i): title or "Untitled debate" for i, title in rows.all()}


async def videos(db: AsyncSession, window: Window, staff: bool) -> list[AudienceVideo]:
    play = VisitEvent.name == "video_play"
    finished = and_(
        VisitEvent.name == "video_progress", VisitEvent.props["pct"].as_string() == "100"
    )
    plays = func.sum(case((play, 1), else_=0)).label("plays")
    rows = await db.execute(
        select(
            VisitEvent.debate_id,
            plays,
            func.count(distinct(case((play, Visit.visitor_id)))),
            func.sum(case((finished, 1), else_=0)),
        )
        .join(Visit, Visit.id == VisitEvent.visit_id)
        .where(
            *_event_scope(
                window,
                staff,
                VisitEvent.debate_id.is_not(None),
                VisitEvent.name.in_(("video_play", "video_progress")),
            )
        )
        .group_by(VisitEvent.debate_id)
        .order_by(plays.desc())
        .limit(10)
    )
    found = [r for r in rows.all() if r[1]]
    debates = {
        d.id: d
        for d in (
            await db.scalars(select(Debate).where(Debate.id.in_([r[0] for r in found])))
        ).all()
    }
    out: list[AudienceVideo] = []
    for debate_id, n, people, done in found:
        debate = debates.get(debate_id) if debate_id else None
        if debate is None:
            continue
        topic = str((debate.config_json or {}).get("topic") or debate.title or "")
        public = debate.is_public and debate.slug
        out.append(
            AudienceVideo(
                debate_id=str(debate_id),
                title=debate.title or topic or "Untitled debate",
                path=seo.debate_path(debate.slug, topic) if public and debate.slug else None,
                plays=int(n or 0),
                visitors=int(people or 0),
                finished=int(done or 0),
            )
        )
    return out


async def campaigns(db: AsyncSession, window: Window, staff: bool) -> list[AudienceCampaign]:
    visits = func.count().label("n")
    rows = await db.execute(
        select(
            Visit.utm_source,
            Visit.utm_medium,
            Visit.utm_campaign,
            visits,
            func.count(distinct(Visit.visitor_id)),
            func.coalesce(func.sum(case((did("signup"), 1), else_=0)), 0),
        )
        .where(
            *scope(window.start, window.end, staff),
            or_(
                Visit.utm_source.is_not(None),
                Visit.utm_medium.is_not(None),
                Visit.utm_campaign.is_not(None),
            ),
        )
        .group_by(Visit.utm_source, Visit.utm_medium, Visit.utm_campaign)
        .order_by(visits.desc())
        .limit(TOP)
    )
    return [
        AudienceCampaign(
            utm_source=s, utm_medium=m, utm_campaign=c, visits=n, visitors=p, signups=int(u)
        )
        for s, m, c, n, p, u in rows.all()
    ]


async def hours(db: AsyncSession, window: Window, staff: bool, timezone: str) -> list[list[int]]:
    local = func.timezone(timezone, Visit.started_at)
    day = (cast(func.extract("isodow", local), Integer) - 1).label("day")
    hour = cast(func.extract("hour", local), Integer).label("hour")
    grid = [[0] * 24 for _ in range(7)]
    rows = await db.execute(
        select(day, hour, func.count())
        .where(*scope(window.start, window.end, staff))
        .group_by(day, hour)
    )
    for d, h, n in rows.all():
        if 0 <= int(d) < 7 and 0 <= int(h) < 24:
            grid[int(d)][int(h)] = int(n)
    return grid


async def funnel(db: AsyncSession, window: Window, staff: bool) -> list[FunnelStep]:
    def people(condition: ColumnElement[bool]) -> Any:
        return func.count(distinct(case((condition, Visit.visitor_id))))

    row = (
        await db.execute(
            select(
                func.count(distinct(Visit.visitor_id)),
                people(or_(Visit.engaged_ms >= ENGAGED_MS, Visit.pageviews >= 2)),
                people(did("video_play")),
                people(did("signup")),
                people(did("debate_start")),
                people(did("topup")),
            ).where(*scope(window.start, window.end, staff))
        )
    ).one()
    return [
        FunnelStep(key=key, label=label, visitors=int(n or 0))
        for (key, label), n in zip(FUNNEL, row, strict=True)
    ]


async def actions(db: AsyncSession, window: Window, staff: bool) -> list[AudienceRow]:
    times = func.count().label("n")
    rows = await db.execute(
        select(VisitEvent.name, times, func.count(distinct(Visit.visitor_id)))
        .join(Visit, Visit.id == VisitEvent.visit_id)
        .where(*_event_scope(window, staff, VisitEvent.kind == "action"))
        .group_by(VisitEvent.name)
        .order_by(times.desc())
    )
    return [
        AudienceRow(key=name, label=ACTIONS.get(name, name), visits=int(n), visitors=int(p))
        for name, n, p in rows.all()
    ]


async def build(
    db: AsyncSession, window: Window, now: datetime, *, staff: bool, timezone: str
) -> dict[str, Any]:
    where = scope(window.start, window.end, staff)
    place = Visit.country.is_not(None)
    region = func.concat_ws(" · ", Visit.city, func.nullif(Visit.region, Visit.city))
    language = func.split_part(func.lower(Visit.language), "-", 1)
    return {
        "tiles": await tiles(db, window, now, staff),
        "series": await series(db, window, staff),
        "sources": await breakdown(db, where, Visit.source),
        "referrers": await breakdown(
            db, [*where, Visit.referrer_host.is_not(None)], Visit.referrer_host, Visit.source
        ),
        "campaigns": await campaigns(db, window, staff),
        "countries": await breakdown(db, where, func.coalesce(Visit.country, ""), limit=30),
        "regions": await breakdown(
            db, [*where, place, Visit.region.is_not(None)], Visit.country, Visit.region, limit=20
        ),
        "cities": await breakdown(
            db, [*where, place, Visit.city.is_not(None)], Visit.country, region, limit=20
        ),
        "landing": await breakdown(db, where, Visit.landing),
        "exits": await breakdown(db, where, Visit.exit_path),
        "pages": await pages(db, window, staff),
        "sections": await sections(db, window, staff),
        "videos": await videos(db, window, staff),
        "devices": await breakdown(db, where, Visit.device),
        "browsers": await breakdown(db, where, func.coalesce(Visit.browser, ""), limit=10),
        "systems": await breakdown(db, where, func.coalesce(Visit.os, ""), limit=10),
        "languages": await breakdown(db, where, func.coalesce(language, ""), limit=12),
        "screens": await breakdown(db, where, func.coalesce(Visit.screen, ""), limit=10),
        "hours": await hours(db, window, staff, timezone),
        "funnel": await funnel(db, window, staff),
        "actions": await actions(db, window, staff),
    }


# --- visits -------------------------------------------------------------------------------------


def visit_user(user: User | None) -> VisitUser | None:
    if user is None:
        return None
    return VisitUser(id=str(user.id), email=user.email, display_name=user.display_name)


def visit_row(visit: Visit, user: User | None) -> VisitRow:
    return VisitRow(
        id=str(visit.id),
        visitor_id=str(visit.visitor_id),
        started_at=visit.started_at,
        last_at=visit.last_at,
        ip=visit.ip,
        country=visit.country,
        region=visit.region,
        city=visit.city,
        source=visit.source,
        referrer_host=visit.referrer_host,
        utm_campaign=visit.utm_campaign,
        landing=visit.landing,
        exit_path=visit.exit_path,
        pageviews=visit.pageviews,
        actions=visit.actions,
        engaged_ms=visit.engaged_ms,
        device=visit.device,
        browser=visit.browser,
        os=visit.os,
        new_visitor=visit.new_visitor,
        staff=visit.staff,
        user=visit_user(user),
    )


def _as_uuid(text: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(text)
    except ValueError:
        return None


def search(q: str) -> ColumnElement[bool] | None:
    """A visit, visitor or account id; else an IP prefix, an email, a place or a path."""
    text = q.strip()
    if not text:
        return None
    exact = _as_uuid(text)
    if exact is not None:
        return or_(Visit.id == exact, Visit.visitor_id == exact, Visit.user_id == exact)
    like = "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    return or_(
        Visit.ip.startswith(text, autoescape=True),
        Visit.city.ilike(like, escape="\\"),
        Visit.region.ilike(like, escape="\\"),
        Visit.landing.ilike(like, escape="\\"),
        Visit.exit_path.ilike(like, escape="\\"),
        Visit.referrer_host.ilike(like, escape="\\"),
        Visit.utm_campaign.ilike(like, escape="\\"),
        exists().where(User.id == Visit.user_id, User.email.ilike(like, escape="\\")),
    )


def list_conditions(query: VisitListQuery, window: Window) -> list[ColumnElement[bool]]:
    where = scope(window.start, window.end, query.staff)
    if query.source:
        where.append(Visit.source == query.source)
    if query.country:
        where.append(Visit.country == query.country.upper())
    if query.device:
        where.append(Visit.device == query.device)
    if query.signed_in is not None:
        where.append(Visit.user_id.is_not(None) if query.signed_in else Visit.user_id.is_(None))
    if query.new_visitor is not None:
        where.append(Visit.new_visitor.is_(query.new_visitor))
    if query.action:
        where.append(did(query.action))
    found = search(query.q)
    if found is not None:
        where.append(found)
    return where


SORTS: dict[str, Any] = {
    "started": Visit.started_at,
    "engaged": Visit.engaged_ms,
    "pageviews": Visit.pageviews,
    "actions": Visit.actions,
}


async def list_visits(db: AsyncSession, query: VisitListQuery, window: Window) -> VisitList:
    where = list_conditions(query, window)
    total = int(await db.scalar(select(func.count()).select_from(Visit).where(*where)) or 0)
    column = SORTS[query.sort]
    order = column.asc() if query.order == "asc" else column.desc()
    rows = await db.execute(
        select(Visit, User)
        .outerjoin(User, User.id == Visit.user_id)
        .where(*where)
        .order_by(order, Visit.started_at.desc())
        .limit(query.limit)
        .offset(query.offset)
    )
    return VisitList(items=[visit_row(v, u) for v, u in rows.all()], total=total)


async def live(db: AsyncSession, now: datetime) -> list[VisitRow]:
    rows = await db.execute(
        select(Visit, User)
        .outerjoin(User, User.id == Visit.user_id)
        .where(Visit.last_at >= now - ONLINE, Visit.staff.is_(False))
        .order_by(Visit.last_at.desc())
        .limit(100)
    )
    return [visit_row(v, u) for v, u in rows.all()]


async def _shared(
    db: AsyncSession, ips: list[str], *, besides: uuid.UUID | None = None
) -> list[SharedAddress]:
    """Accounts seen on these addresses (but `besides`)."""
    if not ips:
        return []
    last = func.max(Visit.last_at).label("last")
    where: list[ColumnElement[bool]] = [Visit.ip.in_(ips), Visit.user_id.is_not(None)]
    if besides is not None:
        where.append(Visit.user_id != besides)
    rows = await db.execute(
        select(Visit.ip, User, func.count(), last)
        .join(User, User.id == Visit.user_id)
        .where(*where)
        .group_by(Visit.ip, User.id)
        .order_by(last.desc())
        .limit(30)
    )
    return [
        SharedAddress(ip=str(ip), user=user_out, visits=int(n), last_at=at)
        for ip, user, n, at in rows.all()
        if (user_out := visit_user(user)) is not None
    ]


async def visit_card(db: AsyncSession, visit_id: uuid.UUID) -> VisitCard | None:
    found = (
        await db.execute(
            select(Visit, User)
            .outerjoin(User, User.id == Visit.user_id)
            .where(Visit.id == visit_id)
        )
    ).first()
    if found is None:
        return None
    visit, user = found
    events = (
        await db.scalars(
            select(VisitEvent)
            .where(VisitEvent.visit_id == visit.id)
            .order_by(VisitEvent.at)
            .limit(1000)
        )
    ).all()
    titles = await _titles(db, [str(e.debate_id) for e in events if e.debate_id])
    summary = (
        await db.execute(
            select(
                func.min(Visit.started_at),
                func.max(Visit.last_at),
                func.count(),
                func.coalesce(func.sum(Visit.pageviews), 0),
                func.coalesce(func.sum(Visit.engaged_ms), 0),
            ).where(Visit.visitor_id == visit.visitor_id)
        )
    ).one()
    accounts = (
        await db.scalars(
            select(User).where(
                User.id.in_(
                    select(Visit.user_id).where(
                        Visit.visitor_id == visit.visitor_id, Visit.user_id.is_not(None)
                    )
                )
            )
        )
    ).all()
    others = await db.execute(
        select(Visit, User)
        .outerjoin(User, User.id == Visit.user_id)
        .where(Visit.visitor_id == visit.visitor_id, Visit.id != visit.id)
        .order_by(Visit.started_at.desc())
        .limit(30)
    )
    row = visit_row(visit, user)
    return VisitCard(
        visit=VisitDetail(
            **row.model_dump(),
            user_agent=visit.user_agent,
            referrer=visit.referrer,
            utm_source=visit.utm_source,
            utm_medium=visit.utm_medium,
            ref=visit.ref,
            screen=visit.screen,
            language=visit.language,
            timezone=visit.timezone,
        ),
        events=[
            VisitEventOut(
                at=e.at,
                kind="page" if e.kind == "page" else "action",
                name=e.name,
                label="Opened a page" if e.kind == "page" else ACTIONS.get(e.name, e.name),
                path=e.path,
                engaged_ms=e.engaged_ms,
                debate_id=str(e.debate_id) if e.debate_id else None,
                debate_title=titles.get(str(e.debate_id)) if e.debate_id else None,
                props=e.props or {},
            )
            for e in events
        ],
        visitor=VisitorSummary(
            visitor_id=str(visit.visitor_id),
            first_seen=summary[0],
            last_seen=summary[1],
            visits=int(summary[2]),
            pageviews=int(summary[3]),
            engaged_ms=int(summary[4]),
            accounts=[u for a in accounts if (u := visit_user(a)) is not None],
        ),
        visitor_visits=[visit_row(v, u) for v, u in others.all()],
        same_ip=await _shared(db, [visit.ip] if visit.ip else []),
    )


async def user_visits(db: AsyncSession, user_id: uuid.UUID) -> dict[str, Any]:
    """The account's visits and those of its browsers before it signed in."""
    browsers = select(distinct(Visit.visitor_id)).where(Visit.user_id == user_id)
    mine = or_(Visit.user_id == user_id, Visit.visitor_id.in_(browsers))
    totals = (
        await db.execute(
            select(
                func.count(),
                func.coalesce(func.sum(Visit.engaged_ms), 0),
                func.coalesce(func.sum(Visit.pageviews), 0),
            ).where(mine)
        )
    ).one()
    rows = await db.execute(
        select(Visit, User)
        .outerjoin(User, User.id == Visit.user_id)
        .where(mine)
        .order_by(Visit.started_at.desc())
        .limit(30)
    )
    first = (
        await db.execute(
            select(Visit, User)
            .outerjoin(User, User.id == Visit.user_id)
            .where(mine)
            .order_by(Visit.started_at)
            .limit(1)
        )
    ).first()
    last = func.max(Visit.last_at).label("last")
    addresses = await db.execute(
        select(
            Visit.ip,
            func.max(Visit.country),
            func.max(Visit.region),
            func.max(Visit.city),
            func.count(),
            func.min(Visit.started_at),
            last,
        )
        .where(mine, Visit.ip.is_not(None))
        .group_by(Visit.ip)
        .order_by(last.desc())
        .limit(20)
    )
    address_rows = [
        AddressRow(
            ip=str(ip), country=c, region=r, city=city, visits=int(n), first_at=start, last_at=end
        )
        for ip, c, r, city, n, start, end in addresses.all()
    ]
    return {
        "visits": [visit_row(v, u) for v, u in rows.all()],
        "total": int(totals[0]),
        "engaged_ms": int(totals[1]),
        "pageviews": int(totals[2]),
        "first": visit_row(*first) if first else None,
        "addresses": address_rows,
        "shared": await _shared(db, [a.ip for a in address_rows], besides=user_id),
    }
