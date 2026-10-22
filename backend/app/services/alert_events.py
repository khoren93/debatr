"""The Telegram alerts an admin can mute (the console's Settings page, lever `muted_alerts`).

`kind` is `alerts.Alert.kind`; `at_once` alerts go out from the request or job that saw the
event, the others come from the periodic check (`alerts.check_alerts_job`). Not listed, so
never muted: the console's test message and changes to this list. Kept apart from
services/alerts so runtime_settings can check the lever without importing the sender.
"""

from dataclasses import dataclass
from typing import Literal

AlertGroup = Literal["security", "people", "debates", "system"]


@dataclass(frozen=True)
class AlertEvent:
    kind: str
    group: AlertGroup
    label: str
    hint: str
    at_once: bool = False


EVENTS: tuple[AlertEvent, ...] = (
    AlertEvent(
        "signin",
        "security",
        "Console sign-in",
        "Every sign-in to this console, with how the second factor was passed.",
        at_once=True,
    ),
    AlertEvent(
        "locked",
        "security",
        "Second factor locked",
        "Too many wrong codes for an admin account.",
        at_once=True,
    ),
    AlertEvent(
        "logins",
        "security",
        "Failed sign-in series",
        "5 or more failed console sign-ins in 15 minutes.",
    ),
    AlertEvent(
        "signup",
        "people",
        "New account",
        "Every sign-up: address, name, browser, welcome credits.",
        at_once=True,
    ),
    AlertEvent("topup", "people", "Top-ups", "Stripe payments credited to a balance."),
    AlertEvent(
        "debate",
        "debates",
        "New debate",
        "Every debate that starts (a new one or a draft; resumes are left out): owner, models, "
        "estimate.",
        at_once=True,
    ),
    AlertEvent(
        "flagged",
        "debates",
        "Flagged for moderation",
        "Debates the AI check kept out of the gallery.",
    ),
    AlertEvent(
        "errors",
        "debates",
        "Failure spike",
        "3 or more failed debates in an hour, at least 30 % of the finished ones.",
    ),
    AlertEvent(
        "stuck",
        "debates",
        "Runs without a worker",
        "Debates or audio builds with no heartbeat and no job waiting for 10+ minutes.",
    ),
    AlertEvent(
        "openrouter",
        "system",
        "OpenRouter balance low",
        "Under $5 on the system key, critical under $1.",
    ),
    AlertEvent(
        "elevenlabs",
        "system",
        "ElevenLabs key or characters",
        "The system key is rejected, or under 10 % of the characters are left.",
    ),
    AlertEvent("disk", "system", "Disk filling up", "85 % full, critical at 95 %."),
    AlertEvent(
        "mail",
        "system",
        "Mail not delivered",
        "A confirmation or reset letter the relay refused, that bounced or was marked as spam, "
        "or production without a relay.",
        at_once=True,
    ),
    AlertEvent(
        "trending",
        "system",
        "Trending batch failed",
        "The daily news topics could not be built; the site keeps the previous batch.",
        at_once=True,
    ),
)

KINDS: tuple[str, ...] = tuple(event.kind for event in EVENTS)
LABELS: dict[str, str] = {event.kind: event.label for event in EVENTS}
SECURITY: frozenset[str] = frozenset(e.kind for e in EVENTS if e.group == "security")
