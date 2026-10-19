"""Show formats (`DebateConfig.format`): the classic debate today; rap battle and court next.

`format_of(conf)` is how the worker, the estimate and the recovery find the rules of a stored
debate: a config without a format, or with one this server no longer knows, runs as a debate.
"""

from collections.abc import Mapping
from typing import Any

from app.services.formats.base import SIDES, Format, Seat, Side
from app.services.formats.debate import DebateFormat

DEFAULT_FORMAT = "debate"

FORMATS: dict[str, Format] = {f.id: f for f in (DebateFormat(),)}


def get_format(format_id: str) -> Format | None:
    return FORMATS.get(format_id)


def format_of(conf: Mapping[str, Any]) -> Format:
    return FORMATS.get(str(conf.get("format") or DEFAULT_FORMAT)) or FORMATS[DEFAULT_FORMAT]


__all__ = [
    "DEFAULT_FORMAT",
    "FORMATS",
    "SIDES",
    "Format",
    "Seat",
    "Side",
    "format_of",
    "get_format",
]
