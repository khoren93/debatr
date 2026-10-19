"""Topics (services/motions): the topic page (`/t/{slug}`) and the wizard's suggestions.

Both show only topics with public versions: a topic made of private debates does not exist for
anyone but the debates' owners, who see them in their library.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.serializers import can_view, gallery_item_out, motion_ref_out
from app.core.auth import get_current_user
from app.core.db import get_db
from app.models.models import Debate, User
from app.schemas.schemas import STORED_TOPIC_MAX_LENGTH, MotionPage, MotionSuggestions
from app.services import motions

router = APIRouter()

TOPIC_PAGE_LIMIT = 100


@router.get("/suggest", response_model=MotionSuggestions)
async def suggest(
    topic: str = Query("", max_length=STORED_TOPIC_MAX_LENGTH),
    language: str = Query("English", max_length=50),
    remix_of: str | None = Query(None, max_length=64),
    viewer: User | None = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MotionSuggestions:
    """The topic a debate with this text would join (`match`) and similar topics whose wording
    the user may take, so their debate becomes another version of it."""
    parent: Debate | None = None
    if remix_of:
        try:
            parent = await db.get(Debate, uuid.UUID(remix_of))
        except ValueError:
            parent = None
        if parent is not None and not can_view(parent, viewer):
            parent = None
    found = await motions.suggest(db, topic, language, parent)
    return MotionSuggestions(
        match=motion_ref_out(found.match),
        similar=[ref for info in found.similar if (ref := motion_ref_out(info)) is not None],
    )


@router.get("/{slug}", response_model=MotionPage)
async def motion_page(slug: str, db: AsyncSession = Depends(get_db)) -> MotionPage:
    """A topic and its public versions, most liked first. A merged topic's slug answers with
    the topic it went into (the page then shows that slug)."""
    motion = await motions.motion_by_slug(db, slug)
    info = (await motions.motion_infos(db, [motion.id])).get(motion.id) if motion else None
    if motion is None or info is None:
        raise HTTPException(status_code=404, detail="No public debates on this topic")
    versions = await motions.public_versions(db, motion.id, limit=TOPIC_PAGE_LIMIT)
    return MotionPage(
        slug=info.slug,
        title=info.title,
        versions=info.versions,
        items=[gallery_item_out(v, info) for v in versions],
    )
