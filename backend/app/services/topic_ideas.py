"""AI topic ideas for the wizard: the user's own words turned into topics for the chosen show.

The search field of the wizard's first step is also where a user writes a topic of their own;
its AI button sends the text here (`POST /api/topics/ideas`). One short call on the system key to
the topic writer (lever `topic_model`, the one that writes the trending lists) writes `IDEAS`
topics by the format's `topic_style` (a debate wants a motion, a rap battle a rivalry), in the
language of the text. It is booked in `provider_usage`
as `topic_ideas` on the account, never billed; the route limits it per account and hour. An idea
is only a suggestion: a debate made from it goes through the usual gallery check.
"""

import re
from typing import Any

from app.schemas.schemas import TOPIC_MAX_LENGTH
from app.services import usage
from app.services.formats import DEFAULT_FORMAT, FORMATS
from app.services.media import llm

IDEAS = 3
MIN_LENGTH = 8  # shorter is no topic ("Why?"); the shortest real ones: "AI or us?"
# The answer is ~40 tokens, but the model thinks first (400-600 hidden tokens): 600 cut some.
MAX_TOKENS = 2000
READ_TIMEOUT = 30.0

SYSTEM = (
    "You write topics for Debatr, a site where {site}. Reply with a single JSON object and "
    "nothing else."
)

# What the ideas never help with (the gallery check's rules, as a refusal).
REFUSE = (
    "hatred or harassment of people for who they are, sexual content, encouraging violence, "
    "terrorism or self-harm, instructions for weapons, drugs or other serious harm, attacks on a "
    "real private person, or accusing a real public figure of crimes as fact"
)

JSON_SPEC = '{"topics": ["...", "...", "..."]}'

_NUMBERING = re.compile(r"^(?:[-*•]+|\d{1,2}[.)])\s+")
_QUOTES = re.compile(r'^["“”«»„\'`*]+|["“”«»\'`*]+$')


def build_messages(text: str, format_id: str, language: str) -> list[dict[str, str]]:
    style = (FORMATS.get(format_id) or FORMATS[DEFAULT_FORMAT]).topic_style
    user = (
        f"A user wants a {style.noun} and wrote this (their own words: maybe rough, a phrase or "
        f'a question):\n"""{text.strip()}"""\n\n'
        f"Write {IDEAS} different {style.noun}s on it, best first:\n"
        "1. the user's idea in its sharpest form, close to their words;\n"
        "2. a bolder, more provocative take on it;\n"
        "3. another angle on the same subject.\n"
        f"Every topic: {style.question}. Keep the user's subject and meaning; never invent "
        "facts, names, dates or numbers. Write in the language of the user's text "
        f"({language} when that is unclear) and keep names as the user wrote them. No quotes "
        "around the topic, no emoji, no hashtags.\n"
        f'If the text asks for {REFUSE}, reply {{"topics": []}}.\n\n'
        f"Reply with JSON only: {JSON_SPEC}"
    )
    system = SYSTEM.format(site=style.site)
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def parse_ideas(text: str) -> list[str]:
    """The topics of a reply: one line each, without quotes or numbering, within the topic
    limit (a longer one is dropped, not cut), no repeats. Raises ValueError without JSON."""
    data: Any = llm.extract_json(text)
    raw = data.get("topics") if isinstance(data, dict) else data
    if not isinstance(raw, list):
        raise ValueError("The reply has no topics list")
    ideas: list[str] = []
    seen: set[str] = set()
    for item in raw:
        topic = _NUMBERING.sub("", " ".join(str(item or "").split()))
        topic = _QUOTES.sub("", topic).strip()
        key = topic.casefold()
        if MIN_LENGTH <= len(topic) <= TOPIC_MAX_LENGTH and key not in seen:
            seen.add(key)
            ideas.append(topic)
    return ideas[:IDEAS]


def suggest(model: str, text: str, format_id: str, language: str, user_id: str | None) -> list[str]:
    """Blocking: ask the model for topic ideas (empty: it refused the text)."""
    with usage.on_behalf_of(user_id):
        reply, _, _ = llm.complete_message(
            model,
            build_messages(text, format_id, language),
            purpose="topic_ideas",
            max_tokens=MAX_TOKENS,
            read_timeout=READ_TIMEOUT,
        )
    return parse_ideas(reply)
