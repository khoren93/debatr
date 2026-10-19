"""Show formats (services/formats): what the wizard, the CLI and agents can run."""

from fastapi import APIRouter

from app.schemas.schemas import FormatOut
from app.services.formats import FORMATS

router = APIRouter()


@router.get("", response_model=list[FormatOut])
async def list_formats() -> list[FormatOut]:
    return [FormatOut.model_validate(f.catalogue()) for f in FORMATS.values()]
