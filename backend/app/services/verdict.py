"""Turn the judge's free-text verdict into structured data (winner, headline, feedback)
for the UI and the video end card. The LLM step is optional; a regex fallback always works.
The same call answers the gallery moderation question (`services/moderation.py`); that answer
is kept apart from the verdict and never shown to viewers."""

import logging
import re
from typing import Any

from app.services.formats import format_of
from app.services.moderation import MODERATION_JSON_SPEC, MODERATION_RULES, parse_moderation

logger = logging.getLogger(__name__)

# Room for reasoning models (the free verdict model thinks before its ~300-token answer).
VERDICT_MAX_TOKENS = 4000
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
    rounds: int = 0,
    extra_rules: str = "",
    show: str = "debate",
) -> list[dict[str, str]]:
    """`rounds`: the judge scored that many rounds (formats with `verdict_scores`), so the scores
    are asked for too; `extra_rules`: what the format allows (`Format.moderation_note`)."""
    names = ", ".join(d["name"] for d in debaters)
    scores = (
        f', "rounds": [{{"round": <1 to {rounds}>, "scores": {{<debater name>: <the judge\'s '
        "score for that round, 1 to 10>}}}} for every round the judge scored]"
        if rounds
        else ""
    )
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
        f"is useful. {MODERATION_RULES}{f' {extra_rules}' if extra_rules else ''}\n\n"
        f"JOB 2 - verdict. Debaters: {names}\n\nVerdict:\n{verdict_text}\n\n"
        "Return JSON with exactly these keys:\n"
        f'{{"moderation": {MODERATION_JSON_SPEC}, '
        '"winner": <exact debater name, or null for a draw>, '
        f'"headline": <one short sentence in {language} announcing the result, '
        f"e.g. 'Alice wins the {show}.' or 'The {show} ends in a draw.'>, "
        '"feedback": [{"name": <debater name>, "text": <two sentences in '
        f"{language} about this debater's strongest and weakest points>}}]{scores}}}"
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


def parse_round_scores(
    raw: Any, debaters: list[dict[str, str]], rounds: int
) -> list[dict[str, Any]]:
    """[{"round": n, "scores": {participant_id: score}}] from the structuring answer: rounds
    1..`rounds` only, scores 0-10, a round needs a score for every debater."""
    out: dict[int, dict[str, int]] = {}
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        try:
            number = int(item.get("round"))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        scores = item.get("scores")
        if not 1 <= number <= rounds or not isinstance(scores, dict):
            continue
        parsed: dict[str, int] = {}
        for name, value in scores.items():
            debater = match_debater(str(name), debaters)
            try:
                score = round(float(value))
            except (TypeError, ValueError):
                continue
            if debater and 0 <= score <= 10:
                parsed[debater["id"]] = score
        if len(parsed) == len(debaters):
            out[number] = parsed
    return [{"round": n, "scores": out[n]} for n in sorted(out)]


def stored_round_scores(verdict_json: dict[str, Any] | None) -> list[dict[str, Any]]:
    """`verdict_json.rounds` as written by `structure_verdict`, read defensively (the API's
    verdict, the video's score sheet): entries that are not {round: int, scores: {id: int}} go."""
    out: list[dict[str, Any]] = []
    for item in (verdict_json or {}).get("rounds") or []:
        if not isinstance(item, dict) or not isinstance(item.get("scores"), dict):
            continue
        try:
            number = int(item["round"])
            scores = {str(k): int(v) for k, v in item["scores"].items()}
        except (KeyError, TypeError, ValueError):
            continue
        out.append({"round": number, "scores": scores})
    return out


_ROUND_LINE = re.compile(r"round\s*(\d+)\s*[:\-–—]?\s*([^\n.;!?]*)", re.I)  # noqa: RUF001


def fallback_round_scores(
    verdict_text: str, debaters: list[dict[str, str]], rounds: int
) -> list[dict[str, Any]]:
    """Scores from "Round 1: Claude 8, GPT 7" in the judge's own words (the prompt asks for
    exactly that), when the structuring call gave none."""
    found: list[dict[str, Any]] = []
    for match in _ROUND_LINE.finditer(verdict_text or ""):
        number, rest = int(match.group(1)), match.group(2)
        scores: dict[str, int] = {}
        for d in debaters:
            hit = re.search(rf"{re.escape(d['name'])}\W{{0,3}}(\d{{1,2}})\b", rest, re.I)
            if hit and int(hit.group(1)) <= 10:
                scores[d["id"]] = int(hit.group(1))
        fresh = all(f["round"] != number for f in found)
        if 1 <= number <= rounds and len(scores) == len(debaters) and fresh:
            found.append({"round": number, "scores": scores})
    return sorted(found, key=lambda f: f["round"])


def _first_sentence(text: str) -> str:
    cleaned = re.sub(r"[*#_`>]+", "", text).strip()
    cleaned = re.sub(r"\[[a-zA-Z][a-zA-Z ,'-]{0,40}\]\s*", "", cleaned)  # [emotion] tags
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
    fmt = format_of(conf)
    rounds = int(conf.get("num_rounds") or 1) if fmt.verdict_scores else 0
    # What the judge said out loud: a battle's score card has reasons that may read like a draw.
    fallback = fallback_verdict(fmt.spoken_text(conf, "verdict", verdict_text), debaters)
    if rounds:
        fallback["rounds"] = fallback_round_scores(verdict_text, debaters, rounds)
    if not verdict_text.strip() or not debaters:
        return fallback, None, {}
    try:
        messages = build_verdict_parse_messages(
            topic=str(conf.get("topic") or ""),
            language=str(conf.get("language") or "English"),
            verdict_text=verdict_text,
            debaters=debaters,
            description=conf.get("description"),
            rounds=rounds,
            extra_rules=fmt.moderation_note,
            show=fmt.show,
        )
        text, usage = complete(
            model,
            messages,
            purpose="verdict_structure",
            api_key=api_key,
            max_tokens=VERDICT_MAX_TOKENS,
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
        if rounds:
            raw = payload.get("rounds") if isinstance(payload, dict) else None
            parsed["rounds"] = parse_round_scores(raw, debaters, rounds) or fallback["rounds"]
        return parsed, moderation, usage or {}
    except Exception as e:
        logger.warning("Verdict structuring failed, using fallback: %s", e)
        return fallback, None, {}
