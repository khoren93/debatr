"""Files for search engines, outside /api (frontend/Caddyfile sends these paths to the API):
robots.txt, the sitemap index with its parts and the IndexNow key file (services/seo builds
the text, services/indexnow announces changes).

Only what the gallery shows is listed (`motions.public_clause`), at its canonical address;
topics need TOPIC_INDEX_MIN_VERSIONS public versions (a single one is that debate's page again).
"""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_db
from app.models.models import Debate
from app.services import indexnow, motions, seo
from app.services.motions import changed_sql, indexed_topics_query, published_sql, topic_sql
from app.services.seo import SitemapUrl

router = APIRouter(include_in_schema=False)

XML = "application/xml; charset=utf-8"
CACHED = {"Cache-Control": f"public, max-age={seo.SITEMAP_CACHE_SECONDS}"}


def _site() -> str:
    return settings.SITE_URL.rstrip("/")


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


@router.api_route("/sitemap.xml", methods=["GET", "HEAD"])
async def sitemap(db: AsyncSession = Depends(get_db)) -> Response:
    public = motions.public_clause()
    site = _site()
    newest = await db.scalar(select(func.max(changed_sql())).where(*public))
    files = [SitemapUrl(f"{site}/sitemaps/pages.xml", newest)]
    topics = (await db.execute(indexed_topics_query().limit(1))).first()
    if topics is not None:
        files.append(SitemapUrl(f"{site}/sitemaps/topics.xml", topics.changed))
    ranked = (
        select(
            changed_sql().label("changed"),
            func.row_number().over(order_by=(published_sql(), Debate.id)).label("rn"),
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
    newest = await db.scalar(select(func.max(changed_sql())).where(*motions.public_clause()))
    site = _site()
    return _xml(seo.urlset(SitemapUrl(f"{site}{p}", newest) for p in seo.LISTING_PATHS))


@router.api_route("/sitemaps/topics.xml", methods=["GET", "HEAD"])
async def sitemap_topics(db: AsyncSession = Depends(get_db)) -> Response:
    rows = (await db.execute(indexed_topics_query())).all()
    site = _site()
    return _xml(
        seo.urlset(
            SitemapUrl(
                seo.absolute(site, seo.topic_path(row.slug, row.title)),
                row.changed,
                images=(seo.absolute(site, seo.topic_image_path(row.slug)),),
            )
            for row in rows
        )
    )


@router.api_route("/sitemaps/debates-{page:int}.xml", methods=["GET", "HEAD"])
async def sitemap_debates(page: int, db: AsyncSession = Depends(get_db)) -> Response:
    if page < 1:
        raise HTTPException(status_code=404, detail="Not Found")
    rows = (
        await db.execute(
            select(Debate.slug, topic_sql().label("topic"), changed_sql().label("changed"))
            .where(*motions.public_clause())
            .order_by(published_sql(), Debate.id)
            .offset((page - 1) * seo.SITEMAP_PAGE_SIZE)
            .limit(seo.SITEMAP_PAGE_SIZE)
        )
    ).all()
    if not rows:
        raise HTTPException(status_code=404, detail="Not Found")
    site = _site()
    return _xml(
        seo.urlset(
            SitemapUrl(
                seo.absolute(site, seo.debate_path(row.slug or "", row.topic)),
                row.changed,
                images=(seo.absolute(site, seo.debate_image_path(row.slug or "")),),
            )
            for row in rows
        )
    )


@router.api_route("/{key}.txt", methods=["GET", "HEAD"])
async def indexnow_key(key: str) -> PlainTextResponse:
    """IndexNow's proof that the key belongs to this host."""
    if not indexnow.key_valid() or key != settings.INDEXNOW_KEY:
        raise HTTPException(status_code=404, detail="Not Found")
    return PlainTextResponse(key, headers=CACHED)
