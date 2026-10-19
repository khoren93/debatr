"""Pre-run estimate of a debate: turns, tokens, provider cost, credits, spoken length.

Pure and deterministic so it can be unit-tested and shown in the create wizard.
"""

from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Any

from app.services.formats import format_of
from app.services.free_router import FREE_ROUTER_ID, FREE_SUFFIX
from app.services.media.languages import language_code
from app.services.prompt_builder import length_words

# Rough tokens per word for OpenRouter-style tokenizers, by language code.
TOKENS_PER_WORD: dict[str, float] = {
    "en": 1.35,
    "es": 1.6,
    "fr": 1.7,
    "de": 1.7,
    "it": 1.6,
    "pt": 1.6,
    "nl": 1.7,
    "pl": 2.4,
    "tr": 2.2,
    "ru": 2.6,
    "uk": 2.7,
    "zh": 1.8,
    "ja": 2.2,
    "ko": 2.2,
    "ar": 2.6,
    "hi": 2.8,
    "hy": 3.0,
}
DEFAULT_TOKENS_PER_WORD = 2.0
WORDS_PER_MINUTE = 150  # neural voices at a natural pace
CHARS_PER_WORD = 6.0  # incl. the space; what TTS providers bill for
SYSTEM_PROMPT_TOKENS = 260
MODERATOR_MAX_WORDS = 120  # mirrors prompt_builder.build_moderator_messages
COMPLETION_OVERHEAD = 1.1  # models overshoot the requested length a little
GAP_MS = 600  # silence between turns on the mixed track
INTRO_OUTRO_MS = 4000  # title and end cards in the video
RENDER_SPEED = 0.8  # browser render time as a fraction of the video length

Pricing = dict[str, tuple[float, float]]  # model id -> (usd per prompt token, per completion token)


@dataclass(frozen=True)
class Estimate:
    turns: int
    words: int
    tokens_in: int
    tokens_out: int
    llm_cost_usd: float
    tts_chars: int
    tts_cost_usd: float
    factcheck_cost_usd: float
    images_cost_usd: float
    credits_cost_usd: float
    duration_ms: int
    render_ms: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def pricing_from_models(models: list[dict[str, Any]]) -> Pricing:
    """Build the pricing map from the OpenRouter model catalogue (per-token USD strings)."""
    out: Pricing = {}
    for m in models:
        pricing = m.get("pricing") or {}
        try:
            out[str(m.get("id"))] = (
                float(pricing.get("prompt") or 0),
                float(pricing.get("completion") or 0),
            )
        except (TypeError, ValueError):
            continue
    return out


def unpriced_models(model_ids: Iterable[str], pricing: Pricing) -> list[str]:
    """Models a run on the system key has no price for: missing from the catalogue (a variant
    such as `:nitro`, a model OpenRouter dropped) or with a variable price (routers list -1).
    The estimate would put them at $0 or less, so they would pass any balance. Free models need
    no price: they pass while the catalogue is unavailable (empty)."""
    out: set[str] = set()
    for model_id in model_ids:
        price = pricing.get(model_id)
        if price is None:
            free = model_id == FREE_ROUTER_ID or model_id.endswith(FREE_SUFFIX)
            if pricing or not free:
                out.add(model_id)
        elif min(price) < 0:
            out.add(model_id)
    return sorted(out)


def estimate_debate(
    conf: dict[str, Any],
    pricing: Pricing,
    *,
    own_key: bool,
    tts_provider: str | None,
    own_tts_key: bool = False,
    tts_price_per_1k: float,
    markup: float,
    min_charge: float = 0.0,
    default_model: str = "",
    fact_check_price: float = 0.0,
    image_price: float = 0.0,
    max_images: int = 0,
    from_turn: int = 0,
) -> Estimate:
    """Provider costs and credits of a run. Fact-checks (one per debater turn on average) run
    on the debate's key; AI pictures always on the system key, so they are charged even with an
    own OpenRouter key. A paid run costs at least `min_charge` (services/credits). `from_turn`:
    a resumed run pays only the turns from that index on (the prompts still carry the earlier
    turns; the minimum was quoted with the first run); the media build comes after the run, so
    it stays."""
    participants: list[dict[str, Any]] = list(conf.get("participants") or [])
    words_per_turn = length_words(str(conf.get("length_preset") or "medium"))
    factor = TOKENS_PER_WORD.get(language_code(conf.get("language")), DEFAULT_TOKENS_PER_WORD)
    context_text = f"{conf.get('topic') or ''} {conf.get('description') or ''}"
    context_text += (conf.get("news") or {}).get("brief") or ""
    context_tokens = SYSTEM_PROMPT_TOKENS + len(context_text) / 4 + 12 * len(participants)

    moderator = next((p for p in participants if p.get("role") == "moderator"), None)
    judge_model = str((moderator or {}).get("model_id") or default_model)

    plan: dict[str, Any] = conf.get("media_plan") or {}
    visuals = bool(plan) and bool(plan.get("visuals", True))
    debater_turns = 0
    checked_turns = 0  # debater turns still to run (fact-checks)
    planned: list[tuple[str, int]] = []  # (model id, words)
    fmt = format_of(conf)
    for index, turn in enumerate(fmt.schedule(conf)):
        debater_turns += 0 if turn.is_moderator else 1
        checked_turns += 0 if turn.is_moderator or index < from_turn else 1
        speaker = participants[turn.speaker_index]
        words = min(words_per_turn, MODERATOR_MAX_WORDS) if turn.is_moderator else words_per_turn
        planned.append((str(speaker.get("model_id") or default_model), words))
    planned.append((judge_model, fmt.verdict_words(conf)))

    history_tokens = 0.0
    tokens_in = 0.0
    tokens_out = 0.0
    cost = 0.0
    total_words = 0
    for index, (model_id, words) in enumerate(planned):
        prompt = context_tokens + history_tokens
        completion = words * factor * COMPLETION_OVERHEAD
        history_tokens += words * factor
        total_words += words
        if index < from_turn:
            continue  # already paid by the earlier run
        prompt_price, completion_price = pricing.get(model_id, (0.0, 0.0))
        cost += prompt * prompt_price + completion * completion_price
        tokens_in += prompt
        tokens_out += completion

    duration_ms = int(
        total_words / WORDS_PER_MINUTE * 60_000 + GAP_MS * (len(planned) - 1) + INTRO_OUTRO_MS
    )
    tts_chars = int(total_words * CHARS_PER_WORD)
    tts_cost = tts_chars / 1000 * tts_price_per_1k if tts_provider == "elevenlabs" else 0.0
    checks = checked_turns if visuals and conf.get("fact_check") else 0
    factcheck_cost = checks * fact_check_price
    wants_images = visuals and plan.get("images") == "ai" and "audio" in (plan.get("outputs") or [])
    images_cost = min(max_images, debater_turns) * image_price if wants_images else 0.0
    llm_credits = (cost + factcheck_cost) * markup
    if llm_credits > 0 and from_turn == 0:
        llm_credits = max(llm_credits, min_charge)
    credits = (
        (0.0 if own_key else llm_credits)
        + (0.0 if own_tts_key else tts_cost)
        + images_cost * markup
    )
    return Estimate(
        turns=len(planned),
        words=total_words,
        tokens_in=int(tokens_in),
        tokens_out=int(tokens_out),
        llm_cost_usd=round(cost, 6),
        tts_chars=tts_chars,
        tts_cost_usd=round(tts_cost, 6),
        factcheck_cost_usd=round(factcheck_cost, 6),
        images_cost_usd=round(images_cost, 6),
        credits_cost_usd=round(credits, 6),
        duration_ms=duration_ms,
        render_ms=int(duration_ms * RENDER_SPEED),
    )
