"""Show formats (`DebateConfig.format`): the classic debate and the rap battle; court next.

`format_of(conf)` is how the worker, the estimate and the recovery find the rules of a stored
debate: a config without a format, or with one this server no longer knows, runs as a debate.
"""

from collections.abc import Mapping
from typing import Any

from app.services.formats.base import SIDES, Format, Seat, Side, TopicStyle
from app.services.formats.debate import DebateFormat
from app.services.formats.rap_battle import RapBattleFormat

DEFAULT_FORMAT = "debate"

FORMATS: dict[str, Format] = {f.id: f for f in (DebateFormat(), RapBattleFormat())}


def get_format(format_id: str) -> Format | None:
    return FORMATS.get(format_id)


def format_of(conf: Mapping[str, Any]) -> Format:
    return FORMATS.get(str(conf.get("format") or DEFAULT_FORMAT)) or FORMATS[DEFAULT_FORMAT]


def topic_list_of(format_id: str) -> str:
    """The format whose list of news topics this format shows: its own when it writes topics
    its own way, else the default format's (an unknown id too)."""
    fmt = FORMATS.get(format_id)
    default = FORMATS[DEFAULT_FORMAT]
    if fmt is None or fmt.topic_style is default.topic_style:
        return DEFAULT_FORMAT
    return fmt.id


def topic_styles() -> dict[str, TopicStyle]:
    """One style per list of news topics, the default format's first."""
    return {fid: FORMATS[fid].topic_style for fid in dict.fromkeys(map(topic_list_of, FORMATS))}


__all__ = [
    "DEFAULT_FORMAT",
    "FORMATS",
    "SIDES",
    "Format",
    "Seat",
    "Side",
    "TopicStyle",
    "format_of",
    "get_format",
    "topic_list_of",
    "topic_styles",
]
