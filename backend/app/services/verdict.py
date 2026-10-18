"""Turn the judge's free-text verdict into structured data (winner, headline, feedback)
for the UI and the video end card. The LLM step is optional; a regex fallback always works.
The same call answers the gallery moderation question (`services/moderation.py`); that answer
is kept apart from the verdict and never shown to viewers."""

import logging
import re
from typing import Any

from app.services.moderation import MODERATION_JSON_SPEC, MODERATION_RULES, parse_moderation

logger = logging.getLogger(__name__)

DRAW_MARKERS = ("draw", "tie", "no clear winner", "no winner", "ничья", "ничьей", "вничью")


def debaters_from_config(conf: dict[str, Any]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for i, p in enumerate(conf.get("participants") or []):
        if p.get("role") == "debater":
            out.append(
                {"id": f"participant_{i}", "name": str(p.get("display_name") or f"Debater {i}")}
            )
    return out


def match_debater(name: str | None, debaters: list[dict[str, str]]) -> dict[str, str] | None:
    if not name:
        return None
    needle = name.strip().lower()
    if not needle:
        return None
    for d in debaters:
        candidate = d["name"].lower()
        if candidate == needle or candidate in needle or needle in candidate:
            return d
    return None


def build_verdict_parse_messages(
    *,
    topic: str,
    language: str,
    verdict_text: str,
    debaters: list[dict[str, str]],
    description: str | None = None,
) -> list[dict[str, str]]:
    names = ", ".join(d["name"] for d in debaters)
    # The content check comes first and is about the user's own text: asked as an afterthought
    # of the verdict task, small models wave obvious spam through.
    system = (
        "You do two jobs for a debate platform: a content check of the user's input for the "
        "public gallery, then structuring the judge's verdict. "
        "Reply with a single JSON object and nothing else."
    )
    about = f"\nDescription: {description}" if description else ""
    user = (
        f"JOB 1 - content check. The user wrote this topic:\nTopic: {topic}{about}\n"
        "Judge the user's text itself (and the verdict below), not whether a debate about it "
        f"is useful. {MODERATION_RULES}\n\n"
        f"JOB 2 - verdict. Debaters: {names}\n\nVerdict:\n{verdict_text}\n\n"
        "Return JSON with exactly these keys:\n"
        f'{{"moderation": {MODERATION_JSON_SPEC}, '
        '"winner": <exact debater name, or null for a draw>, '
        f'"headline": <one short sentence in {language} announcing the result, '
        "e.g. 'Alice wins the debate.' or 'The debate ends in a draw.'>, "
        '"feedback": [{"name": <debater name>, "text": <two sentences in '
        f"{language} about this debater's strongest and weakest points>}}]}}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def parse_verdict_payload(payload: Any, debaters: list[dict[str, str]]) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    winner = match_debater(
        str(payload.get("winner")) if payload.get("winner") is not None else None, debaters
    )
    headline = str(payload.get("headline") or "").strip()[:200]
    feedback: list[dict[str, str]] = []
    for item in payload.get("feedback") or []:
        if not isinstance(item, dict):
            continue
        debater = match_debater(str(item.get("name") or ""), debaters)
        text = str(item.get("text") or "").strip()
        if debater and text:
            feedback.append(
                {"speaker_id": debater["id"], "name": debater["name"], "text": text[:600]}
            )
    if not headline and not feedback:
        return None
    return {
        "winner_id": winner["id"] if winner else None,
        "winner_name": winner["name"] if winner else None,
        "is_draw": winner is None,
        "headline": headline,
        "feedback": feedback,
        "source": "llm",
    }


def _first_sentence(text: str) -> str:
    cleaned = re.sub(r"[*#_`>]+", "", text).strip()
    cleaned = re.sub(r"^\s*\[[^\]]{1,30}\]\s*", "", cleaned)  # leading [emotion] tag
    match = re.search(r"[^.!?\n]{8,}[.!?]", cleaned)
    return (match.group(0) if match else cleaned[:160]).strip()


def fallback_verdict(verdict_text: str, debaters: list[dict[str, str]]) -> dict[str, Any]:
    """Regex-only structuring: the debater named closest after 'winner', draw markers."""
    text = verdict_text or ""
    lowered = text.lower()
    head = lowered[:400]
    is_draw = any(marker in head for marker in DRAW_MARKERS)
    winner: dict[str, str] | None = None
    if not is_draw:
        match = re.search(
            r"(winner|wins|побед[а-яё]*|выигр[а-яё]*)[\s\S]{0,160}",  # noqa: RUF001 (Cyrillic)
            lowered,
        )
        window = match.group(0) if match else head
        best: tuple[int, dict[str, str]] | None = None
        for d in debaters:
            pos = window.find(d["name"].lower())
            if pos >= 0 and (best is None or pos < best[0]):
                best = (pos, d)
        winner = best[1] if best else None
    headline = _first_sentence(text)
    return {
        "winner_id": winner["id"] if winner else None,
        "winner_name": winner["name"] if winner else None,
        "is_draw": winner is None,
        "headline": headline,
        "feedback": [],
        "source": "fallback",
    }


def structure_verdict(
    conf: dict[str, Any],
    verdict_text: str,
    *,
    model: str,
    api_key: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None, dict[str, Any]]:
    """LLM structuring with fallback. Returns (verdict, moderation, usage); moderation is None
    when the model gave no usable answer (the caller then runs a stand-alone check).
    Never raises."""
    from app.services.media.llm import complete, extract_json  # worker-side import

    debaters = debaters_from_config(conf)
    fallback = fallback_verdict(verdict_text, debaters)
    if not verdict_text.strip() or not debaters:
        return fallback, None, {}
    try:
        messages = build_verdict_parse_messages(
            topic=str(conf.get("topic") or ""),
            language=str(conf.get("language") or "English"),
            verdict_text=verdict_text,
            debaters=debaters,
            description=conf.get("description"),
        )
        text, usage = complete(
            model, messages, purpose="verdict_structure", api_key=api_key, max_tokens=800
        )
        payload = extract_json(text)
        moderation = parse_moderation(
            payload.get("moderation") if isinstance(payload, dict) else None
        )
        if moderation is not None:
            moderation["source"] = "llm"
        parsed = parse_verdict_payload(payload, debaters)
        if parsed is None:
            return fallback, moderation, usage or {}
        if not parsed["headline"]:
            parsed["headline"] = fallback["headline"]
        return parsed, moderation, usage or {}
    except Exception as e:
        logger.warning("Verdict structuring failed, using fallback: %s", e)
        return fallback, None, {}
