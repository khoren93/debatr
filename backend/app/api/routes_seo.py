"""Files for search engines, outside /api (frontend/Caddyfile sends these paths to the API):
robots.txt, the sitemap index with its parts and the IndexNow key file (services/seo builds
the text, services/indexnow announces changes).

Only what the gallery shows is listed (`motions.public_clause`), at its canonical address;
topics need TOPIC_INDEX_MIN_VERSIONS public versions (a single one is that debate's page again).
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_db
from app.models.models import Debate, Motion
from app.services import indexnow, motions, seo
from app.services.seo import SitemapUrl

router = APIRouter(include_in_schema=False)

XML = "application/xml; charset=utf-8"
CACHED = {"Cache-Control": f"public, max-age={seo.SITEMAP_CACHE_SECONDS}"}
TOPICS_LIMIT = 50_000  # one file; split like the debates when topics get that many


def _site() -> str:
    return settings.SITE_URL.rstrip("/")


def _published() -> ColumnElement[Any]:
    return func.coalesce(Debate.published_at, Debate.created_at)


def _changed() -> ColumnElement[Any]:
    """When the page last changed: published, or finished later (GREATEST skips NULLs)."""
    return func.greatest(Debate.published_at, Debate.ended_at, Debate.created_at)


def topic_sql() -> ColumnElement[str]:
    """SQL twin of `serializers.topic_of`."""
    return func.coalesce(func.nullif(Debate.config_json["topic"].as_string(), ""), Debate.title, "")


def _xml(text: str) -> Response:
    return Response(text, media_type=XML, headers=CACHED)


@router.api_route("/robots.txt", methods=["GET", "HEAD"])
async def robots() -> PlainTextResponse:
    text = seo.robots_txt(
        site_url=_site(),
        production=settings.is_production,
        allow_ai=settings.SEO_ALLOW_AI_CRAWLERS,
    )
    return PlainTextResponse(text, headers=CACHED)


def _topics_query() -> Any:
    """(slug, title, last change) of every topic worth a search result."""
    public = motions.public_clause()
    versions = (
        select(
            Debate.motion_id.label("motion_id"),
            topic_sql().label("title"),
            func.row_number()
            .over(partition_by=Debate.motion_id, order_by=(_published(), Debate.created_at))
            .label("rn"),
            func.count().over(partition_by=Debate.motion_id).label("versions"),
            func.max(_changed()).over(partition_by=Debate.motion_id).label("changed"),
        )
        .where(*public, Debate.motion_id.is_not(None))
        .subquery()
    )
    return (
        select(Motion.slug, versions.c.title, versions.c.changed)
        .join(Motion, Motion.id == versions.c.motion_id)
        .where(versions.c.rn == 1, versions.c.versions >= seo.TOPIC_INDEX_MIN_VERSIONS)
        .order_by(versions.c.changed.desc(), Motion.slug)
        .limit(TOPICS_LIMIT)
    )


@router.api_route("/sitemap.xml", methods=["GET", "HEAD"])
async def sitemap(db: AsyncSession = Depends(get_db)) -> Response:
    public = motions.public_clause()
    site = _site()
    newest = await db.scalar(select(func.max(_changed())).where(*public))
    files = [SitemapUrl(f"{site}/sitemaps/pages.xml", newest)]
    topics = (await db.execute(_topics_query().limit(1))).first()
    if topics is not None:
        files.append(SitemapUrl(f"{site}/sitemaps/topics.xml", topics.changed))
    ranked = (
        select(
            _changed().label("changed"),
            func.row_number().over(order_by=(_published(), Debate.id)).label("rn"),
        )
        .where(*public)
        .subquery()
    )
    chunk = ((ranked.c.rn - 1) // seo.SITEMAP_PAGE_SIZE).label("chunk")
    rows = await db.execute(
        select(chunk, func.max(ranked.c.changed)).group_by(chunk).order_by(chunk)
    )
    files += [
        SitemapUrl(f"{site}/sitemaps/debates-{int(n) + 1}.xml", last) for n, last in rows.all()
    ]
    return _xml(seo.sitemap_index(files))


@router.api_route("/sitemaps/pages.xml", methods=["GET", "HEAD"])
async def sitemap_pages(db: AsyncSession = Depends(get_db)) -> Response:
    newest = await db.scalar(select(func.max(_changed())).where(*motions.public_clause()))
    site = _site()
    return _xml(seo.urlset(SitemapUrl(f"{site}{p}", newest) for p in seo.LISTING_PATHS))


@router.api_route("/sitemaps/topics.xml", methods=["GET", "HEAD"])
async def sitemap_topics(db: AsyncSession = Depends(get_db)) -> Response:
    rows = (await db.execute(_topics_query())).all()
    site = _site()
    return _xml(
        seo.urlset(
            SitemapUrl(seo.absolute(site, seo.topic_path(row.slug, row.title)), row.changed)
            for row in rows
        )
    )


@router.api_route("/sitemaps/debates-{page:int}.xml", methods=["GET", "HEAD"])
async def sitemap_debates(page: int, db: AsyncSession = Depends(get_db)) -> Response:
    if page < 1:
        raise HTTPException(status_code=404, detail="Not Found")
    rows = (
        await db.execute(
            select(Debate.slug, topic_sql().label("topic"), _changed().label("changed"))
            .where(*motions.public_clause())
            .order_by(_published(), Debate.id)
            .offset((page - 1) * seo.SITEMAP_PAGE_SIZE)
            .limit(seo.SITEMAP_PAGE_SIZE)
        )
    ).all()
    if not rows:
        raise HTTPException(status_code=404, detail="Not Found")
    site = _site()
    return _xml(
        seo.urlset(
            SitemapUrl(seo.absolute(site, seo.debate_path(row.slug or "", row.topic)), row.changed)
            for row in rows
        )
    )


@router.api_route("/{key}.txt", methods=["GET", "HEAD"])
async def indexnow_key(key: str) -> PlainTextResponse:
    """IndexNow's proof that the key belongs to this host."""
    if not indexnow.key_valid() or key != settings.INDEXNOW_KEY:
        raise HTTPException(status_code=404, detail="Not Found")
    return PlainTextResponse(key, headers=CACHED)
