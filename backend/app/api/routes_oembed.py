"""oEmbed (https://oembed.com): a link to a public debate or topic pasted into a blog, a forum or
a notes app becomes the debate's player. Pages name the endpoint in a
`<link rel="alternate" type="application/json+oembed">` (frontend lib/seo.ts); services/embed
builds the answer.

Anyone may ask from any origin (CORS `*` here only). Private, unpublished or unknown pages are
a 404 alike, so the endpoint tells nothing about debates that are not public.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.serializers import topic_of
from app.core.config import settings
from app.core.db import get_db
from app.models.models import Debate
from app.services import embed, motions

router = APIRouter()

HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Cache-Control": f"public, max-age={embed.CACHE_AGE}",
}


def _answer(status: int, body: dict[str, Any]) -> JSONResponse:
    headers = HEADERS if status == 200 else {"Access-Control-Allow-Origin": "*"}
    return JSONResponse(body, status_code=status, headers=headers)


async def _public_debate(db: AsyncSession, slug: str) -> Debate | None:
    return await db.scalar(
        select(Debate)
        .options(selectinload(Debate.participants), selectinload(Debate.user))
        .where(Debate.slug == slug, *motions.public_clause())
    )


async def _best_version(db: AsyncSession, slug: str) -> Debate | None:
    """A topic's most liked public version that has a video (else its most liked one)."""
    motion = await motions.motion_by_slug(db, slug)
    if motion is None:
        return None
    versions = await motions.public_versions(db, motion.id, limit=50)
    return next(
        (v for v in versions if v.media_status == "ready"), versions[0] if versions else None
    )


@router.get("/oembed")
async def oembed(
    url: Annotated[str, Query(max_length=2048)],
    maxwidth: Annotated[int | None, Query(ge=1, le=10_000)] = None,
    maxheight: Annotated[int | None, Query(ge=1, le=10_000)] = None,
    format: Annotated[str, Query(max_length=8)] = "json",
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """The player of the public debate (or the best version of the topic) a link names."""
    if format != "json":
        return _answer(501, {"detail": "Only format=json is supported"})
    target = embed.parse_url(url, settings.SITE_URL, settings.site_aliases)
    if target is None:
        return _answer(404, {"detail": "Not a link to a debate or a topic of this site"})
    debate = await (_public_debate if target.kind == "debate" else _best_version)(db, target.slug)
    if debate is None or debate.slug is None:
        return _answer(404, {"detail": "This debate is not public"})
    debaters = [p.persona_name or "" for p in debate.participants if p.role == "debater"]
    payload = embed.oembed_payload(
        site_url=settings.SITE_URL,
        slug=debate.slug,
        title=embed.embed_title(topic_of(debate), debaters),
        author=debate.user.display_name if debate.user is not None else None,
        playable=debate.media_status == "ready",
        fmt=target.format,
        start=target.start,
        maxwidth=maxwidth,
        maxheight=maxheight,
    )
    return _answer(200, payload)
