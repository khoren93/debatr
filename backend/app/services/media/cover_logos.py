"""Provider logos for the AI covers: the picture the image model copies and words for it.

The site's server renderer draws a model's logo (the same SVG and author mapping as the gallery
card, frontend src/lib/modelIcons.ts) as a 512 px PNG at `/og/logo.png?model=…`; the worker
fetches it from WEB_INTERNAL_URL and sends it as a reference picture, so a cover shows the logo
the site shows. The descriptions below go into the prompt next to it. A model without a logo, or
a renderer that does not answer, gets a glowing emblem in its colour instead.
"""

import logging
from dataclasses import dataclass

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

FETCH_TIMEOUT = 10.0

# What each logo looks like, for the prompt (the reference picture shows it; words help the model
# put it on the character). Keyed by the site's icon file; a test checks that every file of
# frontend/public/model-icons has a line (add one with a new logo).
DESCRIPTIONS: dict[str, str] = {
    "ai2-color": "four pink rounded L-shaped blocks forming a pinwheel cross",
    "ai21-brand-color": "the wordmark 'AI21 labs' in tall black and magenta letters",
    "alibaba-color": "an orange swoosh shaped like a smiling stylised 'e'",
    "antgroup-color": "a round blue ant-like creature with two antennae and one big round eye",
    "arcee-color": "teal diagonal stripes fanning out from a corner like rays",
    "baai": "a black outlined cube made of interlocking maze-like bands",
    "baidu-color": "a blue bear paw print with the letters 'du' on its palm",
    "bytedance-color": "four vertical bars in shades from blue to teal, like a rising chart",
    "claude-color": "an orange starburst of tapered rays",
    "cohere-color": "a dark green pill above a coral circle and a lilac blob",
    "deepseek-color": "a blue whale with a raised tail",
    "dotsstudio": "a black outlined triangular sail above a short line",
    "fireworks-color": "three purple chevrons spreading upward like a firework",
    "gemini-color": "a four-pointed star with a blue, red, yellow and green gradient",
    "gemma-color": "a light blue outlined four-pointed star inside thin geometric lines",
    "grok": "a black circle cut through by a diagonal slash, like a planet with a streak",
    "huggingface-color": "a yellow smiling emoji face with two hugging hands",
    "hunyuan-color": "a blue circle with swirling light-blue and white waves",
    "ibm": "the IBM wordmark in thick black horizontal stripes",
    "inception": "two black angular blocks interlocking into a stepped S",
    "inflection": "a bold black capital I with flared serifs",
    "kimi-color": "a bold white letter K with a small blue dot at its top right",
    "kwaipilot-color": "a pale blue circle with a slanted cut like the number 7",
    "liquid": "a black faceted droplet made of angular planes",
    "longcat-color": "a green cat face shaped like a letter M with two small eyes",
    "meta-color": "a blue infinity loop",
    "microsoft-color": "four squares in red, green, blue and yellow",
    "minimax-color": "a pink-to-red continuous wavy line like a sound wave",
    "mistral-color": "a pixel-art letter M in stacked yellow, orange and red blocks",
    "morph-color": "a lime green rounded M-shaped block",
    "nousresearch": "a black and white ink drawing of an anime girl with headphones",
    "nova-color": "a pink and purple star of zigzag arrows pointing outward",
    "nvidia-color": "the green NVIDIA eye: a green swirl wrapping around a white centre",
    "openai": "the OpenAI knot: a black rosette of six interlocking rounded strands",
    "openrouter-color": "a chunky lime-yellow ring with a squared notch on its right",
    "perceptron": "a black zigzag line like a heartbeat",
    "perplexity-color": "a teal geometric asterisk of crossing lines in an outline",
    "poolside-color": "a blue-violet circle with a beach umbrella silhouette",
    "qwen-color": "a purple hexagonal knot of three interlocking bands around a triangle",
    "reka": "the word 'reka' in heavy black blocky letters",
    "relace": "a black square frame with a looping ribbon inside",
    "sakana-color": "a red line drawing of a fish",
    "stepfun-color": "blue stairs stepping up with a small plus sign",
    "upstage-color": "stacked lilac horizontal speed lines in a slanted block",
    "xiaomimimo": "the black wordmark 'Xiaomi MiMo'",
    "zai": "a bold black letter Z with a diagonal cut",
}


@dataclass(frozen=True)
class Logo:
    name: str  # the site's icon file without extension ("claude-color")
    description: str
    png: bytes


def fetch_logo(model_id: str | None) -> Logo | None:
    """The logo of `model_id` from the site's renderer, None without one (or when it fails)."""
    if not model_id:
        return None
    url = f"{settings.WEB_INTERNAL_URL.rstrip('/')}/og/logo.png"
    try:
        response = httpx.get(url, params={"model": model_id}, timeout=FETCH_TIMEOUT)
    except httpx.HTTPError as e:
        logger.warning("Logo of %s unavailable: %s", model_id, e)
        return None
    if response.status_code != 200 or not response.content:
        if response.status_code != 404:
            logger.warning("Logo of %s unavailable: HTTP %s", model_id, response.status_code)
        return None
    name = response.headers.get("x-logo", "")
    return Logo(name=name, description=DESCRIPTIONS.get(name, "its logo"), png=response.content)
