"""Device, browser and operating system from a User-Agent (pure): coarse families only, enough
for the console's breakdowns."""

import re
from dataclasses import dataclass

# First match wins: in-app browsers and Chromium forks before Chrome, Chrome before Safari
# (Chrome's agent names Safari too).
_BROWSERS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (name, re.compile(pattern, re.IGNORECASE))
    for name, pattern in (
        ("Instagram", r"Instagram"),
        ("Facebook", r"FBAN|FBAV|FB_IAB"),
        ("TikTok", r"musical_ly|BytedanceWebview|TikTok"),
        ("Telegram", r"Telegram"),
        ("Edge", r"Edg(e|A|iOS)?/"),
        ("Opera", r"OPR/|OPiOS/|Opera"),
        ("Yandex", r"YaBrowser/|YaSearchBrowser"),
        ("Samsung Internet", r"SamsungBrowser/"),
        ("Vivaldi", r"Vivaldi/"),
        ("DuckDuckGo", r"DuckDuckGo/|Ddg/"),
        ("Firefox", r"Firefox/|FxiOS/"),
        ("Chrome", r"Chrome/|CriOS/|Chromium/"),
        ("Safari", r"Safari/|AppleWebKit"),
    )
)
_SYSTEMS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (name, re.compile(pattern, re.IGNORECASE))
    for name, pattern in (
        ("iOS", r"iPhone|iPad|iPod"),
        ("Android", r"Android"),
        ("Windows", r"Windows"),
        ("ChromeOS", r"CrOS"),
        ("macOS", r"Macintosh|Mac OS X"),
        ("Linux", r"Linux|X11"),
    )
)
_TABLET = re.compile(r"iPad|Tablet|PlayBook|Silk|Kindle", re.IGNORECASE)
_MOBILE = re.compile(r"Mobi|iPhone|iPod|Windows Phone|Opera Mini", re.IGNORECASE)


@dataclass(frozen=True)
class Agent:
    device: str  # desktop | mobile | tablet
    browser: str | None
    os: str | None


def _first(table: tuple[tuple[str, re.Pattern[str]], ...], text: str) -> str | None:
    return next((name for name, pattern in table if pattern.search(text)), None)


def parse_agent(user_agent: str | None, *, touch: bool = False) -> Agent:
    """`touch`: the browser reported a touch screen (an iPad's Safari says "Macintosh")."""
    text = user_agent or ""
    system = _first(_SYSTEMS, text)
    if system == "macOS" and touch:
        return Agent("tablet", _first(_BROWSERS, text), "iOS")
    if _TABLET.search(text) or (system == "Android" and "Mobile" not in text):
        device = "tablet"
    elif _MOBILE.search(text) or system in ("iOS", "Android"):
        device = "mobile"
    else:
        device = "desktop"
    return Agent(device, _first(_BROWSERS, text), system)
