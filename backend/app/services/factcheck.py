"""Web fact-check of what the studio puts on screen: figures, dates and attributed quotes.

During a debate (when `DebateConfig.fact_check` is on) every checkable scene a speaker gets is
sent to a search-enabled model (`FACT_CHECK_MODEL`, default `perplexity/sonar`), which answers
verified / disputed / unverified with sources. Results are shown on the scene, given to the
next speakers and to the judge, and summed per model for the leaderboard. Everything except
the model call is pure and unit-tested.
"""

import json
import logging
import re
from typing import Any
from urllib.parse import urlparse

from pydantic import ValidationError

from app.schemas.visuals import SceneCheck
from app.services.media.highlights import locate_quote
from app.services.media.llm import complete_message, extract_json
from app.services.media.visuals import scene_summary

logger = logging.getLogger(__name__)

MAX_SOURCES = 3
_SENTENCE_RE = re.compile(r"(?<=[.!?…])\s+")
_VERDICTS = {
    "verified": "verified",
    "true": "verified",
    "accurate": "verified",
    "correct": "verified",
    "mostly true": "verified",
    "disputed": "disputed",
    "false": "disputed",
    "inaccurate": "disputed",
    "incorrect": "disputed",
    "misleading": "disputed",
    "unverified": "unverified",
    "unclear": "unverified",
    "unknown": "unverified",
}


def claim_sentence(speech: str, anchor: str, limit: int = 420) -> str:
    """The sentence of the speech where the scene's anchor is said (plus the next one when it
    is short), so the checker sees the claim in the speaker's own words."""
    sentences = [s for s in _SENTENCE_RE.split(" ".join(speech.split())) if s]
    if not sentences:
        return ""
    index = 0
    if anchor.strip():
        words: list[tuple[str, int, int]] = []
        owner: list[int] = []
        for i, sentence in enumerate(sentences):
            for word in sentence.split():
                words.append((word, 0, 0))
                owner.append(i)
        at = locate_quote(words, anchor)
        if at is not None:
            index = owner[at]
    text = sentences[index]
    if len(text) < 120 and index + 1 < len(sentences):
        text = f"{text} {sentences[index + 1]}"
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def build_check_messages(
    *, topic: str, language: str, speaker: str, sentence: str, summary: str
) -> list[dict[str, str]]:
    system = (
        "You are a meticulous fact-checker for a live debate show. Search the web and judge the "
        "claim against reliable sources (official statistics, research, reputable media). "
        "Reply with one JSON object only."
    )
    user = (
        f"Debate topic: {topic}\n"
        f"Speaker: {speaker}\n"
        f'What the speaker said: "{sentence}"\n'
        f"Shown on screen: {summary}\n\n"
        "Check the figures, dates or quote shown on screen. Rounded or approximate figures that "
        "match the sources (within about 10%) are accurate; a quote must be by that author. "
        "Forecasts, opinions or figures you cannot find are unverified.\n"
        'Return {"verdict": "verified" | "disputed" | "unverified", "note": "<one short '
        f"sentence in {language}: what reliable sources say, with the correct figure if it "
        'differs>", "sources": ["<url>", ...]}'
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _domain(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def _citations(annotations: list[dict[str, Any]]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for item in annotations:
        cite = item.get("url_citation") if item.get("type") == "url_citation" else None
        if isinstance(cite, dict) and isinstance(cite.get("url"), str):
            out.append((cite["url"], str(cite.get("title") or "")))
    return out


def parse_check(text: str, annotations: list[dict[str, Any]] | None = None) -> SceneCheck | None:
    """The checker's verdict with up to MAX_SOURCES sources (its own list first, then the
    search citations). None when the reply has no usable verdict."""
    try:
        payload = extract_json(text)
    except (ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    raw = str(payload.get("verdict") or "").strip().lower()
    verdict = _VERDICTS.get(raw)
    if verdict is None:
        return None
    cited = _citations(annotations or [])
    titles = {url: title for url, title in cited}
    urls: list[str] = []
    for item in payload.get("sources") or []:
        url = item.get("url") if isinstance(item, dict) else item
        if isinstance(url, str) and url.startswith(("http://", "https://")):
            urls.append(url.strip())
    urls += [url for url, _title in cited]
    sources: list[dict[str, str]] = []
    for url in dict.fromkeys(urls):
        if len(sources) >= MAX_SOURCES:
            break
        sources.append({"url": url, "title": titles.get(url) or _domain(url)})
    try:
        return SceneCheck.model_validate(
            {"verdict": verdict, "note": str(payload.get("note") or ""), "sources": sources}
        )
    except ValidationError:
        try:  # a malformed source url should not lose the verdict
            return SceneCheck.model_validate(
                {"verdict": verdict, "note": str(payload.get("note") or "")}
            )
        except ValidationError:
            return None


def check_scene(
    scene: Any,
    *,
    speech: str,
    topic: str,
    language: str,
    speaker: str,
    model: str,
    api_key: str | None = None,
) -> tuple[SceneCheck | None, float]:
    """Fact-check one scene. Returns (result or None, usd spent)."""
    messages = build_check_messages(
        topic=topic,
        language=language,
        speaker=speaker,
        sentence=claim_sentence(speech, scene.anchor),
        summary=scene_summary(scene),
    )
    text, annotations, usage = complete_message(
        model, messages, purpose="factcheck", api_key=api_key, max_tokens=500
    )
    result = parse_check(text, annotations)
    if result is None:
        logger.info("Unusable fact-check reply for %s: %s", getattr(scene, "key", ""), text[:200])
    return result, float((usage or {}).get("cost") or 0.0)
