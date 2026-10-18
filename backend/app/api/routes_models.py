import asyncio
import time

from fastapi import APIRouter, Header

from app.schemas.schemas import (
    CreditsResponse,
    ModelsResponse,
    ValidateModelsRequest,
    ValidateModelsResponse,
    ValidationResult,
)
from app.services import runtime_settings
from app.services.openrouter_client import openrouter_client

router = APIRouter()


@router.get("/credits", response_model=CreditsResponse)
async def get_credits(
    x_openrouter_key: str | None = Header(default=None, alias="X-OpenRouter-Key"),
) -> CreditsResponse:
    """Remaining credits for the system key, or for a user key passed via header."""
    credits, error = await openrouter_client.get_credits(api_key=x_openrouter_key)
    return CreditsResponse(credits=credits, error=error)


@router.get("", response_model=ModelsResponse)
async def get_models() -> ModelsResponse:
    """Available OpenRouter models (cached), without the ones the admin console turned off."""
    models = await openrouter_client.get_models()
    off = set((await runtime_settings.current()).disabled_models)
    if off:
        models = [m for m in models if m.get("id") not in off]
    return ModelsResponse.model_validate({"data": models, "timestamp": time.time()})


@router.post("/validate", response_model=ValidateModelsResponse)
async def validate_models(request: ValidateModelsRequest) -> ValidateModelsResponse:
    """Send a tiny prompt to each model to confirm it responds."""

    async def check_one(model_id: str) -> ValidationResult:
        ok, error = await openrouter_client.validate_model(model_id, api_key=request.api_key)
        return ValidationResult(model_id=model_id, status="ok" if ok else "error", error=error)

    results = await asyncio.gather(*(check_one(mid) for mid in dict.fromkeys(request.model_ids)))
    return ValidateModelsResponse(results=list(results))
