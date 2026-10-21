"""A person, a bot or an AI agent: the verdict of a visit (pure; the console's Audience page shows
it with its reasons).

Crawlers that say what they are never get here (views.is_bot drops them, and most never run the
page's scripts). What is left are browsers: people, headless browsers driven by scripts, and AI
agents that click through a real browser (ChatGPT agent, browser-use, Claude in Chrome…). No
single sign proves anything, so every signal adds points to one side: automation (the browser
itself — no GPU, a headless brand, a User-Agent that disagrees with the platform —, a data-centre
network, a crawler's pace, and input no hand makes: clicks with no mouse move before them, clicks
at the exact centre of buttons, typing faster than fingers, text that appears without keys) or a
person (mouse paths, touches, typing at a human pace, wheel scrolls, tab switches, a returning
browser, an account). The page counts its input (frontend lib/presence.ts) and never sends what
was typed or where; the server adds what the request says (`RequestFacts`) and the network.

Verdicts: `agent` (automation that interacts, or one that signs as an agent), `bot` (automation
that does not), `suspect`, `likely_human`, `human`, `unclear` (too little to tell, e.g. a visit
that has just begun). `bot` and `agent` are left out of the statistics unless asked for.
"""

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, ValidationError

Verdict = Literal["human", "likely_human", "unclear", "suspect", "bot", "agent"]
VERDICTS: tuple[Verdict, ...] = ("human", "likely_human", "unclear", "suspect", "bot", "agent")
#: Left out of the console's statistics unless "Include bots" is on.
AUTOMATED: tuple[Verdict, ...] = ("bot", "agent")

Count = Annotated[int, Field(ge=0, le=1_000_000)]


class ClientSignals(BaseModel):
    """What the page counted since its previous beacon: how much input and how machine-like it
    was, never what was typed or where."""

    mv: Count = 0  # mouse moves
    jmp: Count = 0  # mouse moves that jumped more than 300 px at once
    ck: Count = 0  # mouse presses
    ckb: Count = 0  # presses with (almost) no mouse move before them, away from the last press
    cc: Count = 0  # presses (mouse or touch) at the exact centre of a button, link or field
    tp: Count = 0  # touches
    ky: Count = 0  # key presses (auto-repeat left out)
    kf: Count = 0  # key presses less than 12 ms after the one before
    fill: Count = 0  # text typed into a field without a key press (desktop)
    wh: Count = 0  # wheel / trackpad scrolls
    hid: Count = 0  # the page went to the background (another tab or app)
    syn: Count = 0  # pointer or key events made by a script (not trusted)


class ClientEnv(BaseModel):
    """What the browser says about itself, once per page load."""

    gl: Literal["hw", "soft", "none"] | None = None  # WebGL on a GPU, in software, or none
    plat: str | None = Field(default=None, max_length=32)  # userAgentData.platform / platform
    pl: int | None = Field(default=None, ge=0, le=1000)  # navigator.plugins.length
    ln: int | None = Field(default=None, ge=0, le=1000)  # navigator.languages.length
    chr: bool | None = None  # window.chrome exists
    ow: bool | None = None  # the window reports no outer size
    hl: bool | None = None  # a "HeadlessChrome" brand in navigator.userAgentData


@dataclass(frozen=True)
class RequestFacts:
    """What a beacon's request headers say."""

    signed_agent: bool = False  # Signature-Agent: ChatGPT agent signs its requests (RFC 9421)
    headless_brand: bool = False  # Sec-CH-UA names HeadlessChrome
    ch_platform: str | None = None  # Sec-CH-UA-Platform
    accept_language: bool = True


def request_facts(headers: Any) -> RequestFacts:
    """From a request's headers (anything with `.get`)."""
    brands = str(headers.get("sec-ch-ua") or "")
    platform = str(headers.get("sec-ch-ua-platform") or "").strip().strip('"')[:32]
    return RequestFacts(
        signed_agent=bool(headers.get("signature-agent")),
        headless_brand="headless" in brands.lower(),
        ch_platform=platform or None,
        accept_language=bool(headers.get("accept-language")),
    )


def merge(
    stored: dict[str, Any] | None,
    counts: ClientSignals | None,
    env: ClientEnv | None,
    request: RequestFacts | None,
) -> dict[str, Any]:
    """The visit's `signals` with a beacon added: counts summed, the newest browser facts, and
    request facts that once seen stay (an agent may sign some requests only)."""
    out: dict[str, Any] = {k: v for k, v in (stored or {}).items() if k in ("c", "env", "srv")}
    # A page that sends either counts its input: no counts then means no input, not unknown.
    if counts is None and env is not None:
        counts = ClientSignals()
    if counts is not None:
        total = dict(out.get("c") or {})
        for key, value in counts.model_dump().items():
            if value:
                total[key] = min(int(total.get(key) or 0) + value, 1_000_000)
        out["c"] = total
    if env is not None:
        out["env"] = env.model_dump(exclude_none=True)
    if request is not None:
        srv = dict(out.get("srv") or {})
        srv["sig"] = bool(srv.get("sig")) or request.signed_agent
        srv["hl"] = bool(srv.get("hl")) or request.headless_brand
        if request.ch_platform:
            srv["chp"] = request.ch_platform
        srv["al"] = bool(srv.get("al", True)) and request.accept_language
        out["srv"] = srv
    return out


# --- networks -------------------------------------------------------------------------------------

# Cloud and hosting networks (by AS number, then by the operator's words): people rarely browse
# from them, except through a VPN, so a data centre only adds points.
HOSTING_ASNS = frozenset(
    {
        16509, 14618, 8987,  # Amazon
        15169, 396982, 19527,  # Google
        8075, 8068, 8069,  # Microsoft / Azure
        14061,  # DigitalOcean
        24940, 213230,  # Hetzner
        16276,  # OVH
        63949,  # Akamai Connected Cloud (Linode)
        20473,  # Vultr
        51167,  # Contabo
        12876,  # Scaleway
        60781, 28753, 16265,  # Leaseweb
        31898,  # Oracle
        45102, 37963,  # Alibaba
        132203, 45090,  # Tencent
        136907,  # Huawei Cloud
        47583,  # Hostinger
        8560,  # IONOS
        9009,  # M247
        60068,  # Datacamp / CDN77
        36352,  # ColoCrossing
        53667,  # FranTech / BuyVM
        49505,  # Selectel
        9123,  # Timeweb
        198610,  # Beget
    }
)  # fmt: skip
_HOSTING_WORDS = re.compile(
    r"amazon|\baws\b|google cloud|microsoft|azure|digitalocean|hetzner|\bovh|linode|"
    r"connected cloud|vultr|constant company|choopa|contabo|scaleway|online s\.a\.s|leaseweb|"
    r"oracle|alibaba|aliyun|tencent|huawei cloud|hostinger|ionos|\bm247\b|datacamp|cdn77|"
    r"colocrossing|frantech|buyvm|clouvider|worldstream|nforce|netcup|selectel|timeweb|beget|"
    r"aeza|interserver|hivelocity|liquid web|rackspace|softlayer|ibm cloud|upcloud|kamatera|"
    r"ramnode|psychz|quadranet|zenlayer|g-?core|servers\.com|cherry servers|hostkey|hostwinds|"
    r"hosting|data ?cent(er|re)|dedicated|\bvps\b|colocation|server",
    re.IGNORECASE,
)
# Relays and VPN operators: iCloud Private Relay, WARP and the like carry people too.
RELAY_ASNS = frozenset({13335, 36183, 20940, 16625, 54113})  # Cloudflare, Akamai, Fastly
_RELAY_WORDS = re.compile(
    r"cloudflare|akamai|fastly|private relay|zscaler|netskope|\bproton|nordvpn|mullvad|"
    r"expressvpn|surfshark|windscribe|ipvanish|cyberghost|tunnelbear|purevpn|privado",
    re.IGNORECASE,
)

NetworkKind = Literal["hosting", "relay"]


def network_kind(asn: int | None, org: str | None) -> NetworkKind | None:
    if asn in HOSTING_ASNS:
        return "hosting"
    if asn in RELAY_ASNS:
        return "relay"
    name = org or ""
    if _HOSTING_WORDS.search(name):
        return "hosting"
    if _RELAY_WORDS.search(name):
        return "relay"
    return None


# --- the browser ----------------------------------------------------------------------------------

_CHROME = re.compile(r"(?:Chrome|CriOS)/(\d{2,3})\.")
# Chrome 141 came out on 2025-09-30; a release every four weeks since.
_CHROME_BASE = (141, datetime(2025, 9, 30, tzinfo=UTC))
CHROME_BEHIND = 10  # releases (about nine months): older than this is out of date
_UTC_ZONES = frozenset(
    {"utc", "etc/utc", "etc/gmt", "gmt", "etc/universal", "universal", "zulu", "etc/zulu", "uct"}
)
_ODD_SCREENS = frozenset({"800x600", "0x0", "1x1"})
# Chrome-family browsers that have `window.chrome` on desktop systems.
_CHROME_BROWSERS = frozenset({"Chrome", "Edge", "Opera", "Vivaldi", "Yandex"})


def expected_chrome(now: datetime) -> int:
    version, released = _CHROME_BASE
    return version + max(0, (now - released).days) // 28


def chrome_version(user_agent: str | None) -> int | None:
    match = _CHROME.search(user_agent or "")
    return int(match.group(1)) if match else None


def platform_family(text: str | None) -> str | None:
    """A platform's family from navigator.platform, userAgentData.platform or Sec-CH-UA-Platform
    ("Win32", "macOS", "Linux armv8l", "iPhone", "Chrome OS"…)."""
    value = (text or "").strip().strip('"').lower()
    if not value:
        return None
    if value.startswith("win"):
        return "windows"
    if value.startswith("mac"):
        return "mac"
    if value.startswith(("iphone", "ipad", "ipod", "ios")):
        return "ios"
    if value.startswith("android"):
        return "android"
    if "cros" in value or value.startswith("chrome"):
        return "chromeos"
    if value.startswith("linux"):
        return "linux"
    return None


_UA_FAMILIES = {
    "Windows": "windows",
    "macOS": "mac",
    "iOS": "ios",
    "Android": "android",
    "ChromeOS": "chromeos",
    "Linux": "linux",
}
# The platform may name the kernel below the system (Android, ChromeOS) or the desktop an iPad
# asks for.
_COMPATIBLE = {("android", "linux"), ("chromeos", "linux"), ("ios", "mac"), ("mac", "ios")}


def platform_mismatch(ua_os: str | None, platform: str | None) -> bool:
    said, runs = _UA_FAMILIES.get(ua_os or ""), platform_family(platform)
    return bool(said and runs and said != runs and (said, runs) not in _COMPATIBLE)


# Time zones stray from the sun's time by up to about three and a half hours (western China);
# further than this the browser's clock belongs to another part of the world than its IP.
CLOCK_GAP_HOURS = 4.5


def clock_gap(zone: str | None, longitude: float | None, at: datetime) -> float | None:
    """Hours between the browser's UTC offset and the sun's time at the IP's longitude."""
    if not zone or longitude is None:
        return None
    try:
        offset = at.astimezone(ZoneInfo(zone)).utcoffset()
    except (ZoneInfoNotFoundError, ValueError):
        return None
    if offset is None:
        return None
    gap = abs(offset.total_seconds() / 3600 - longitude / 15) % 24
    return min(gap, 24 - gap)


# --- the verdict ----------------------------------------------------------------------------------

#: The console's words for each reason; `points` > 0 count towards automation, < 0 a person.
REASONS: dict[str, str] = {
    "signed_agent": "Signs its requests as an AI agent (ChatGPT agent)",
    "headless": "Headless browser",
    "platform_mismatch": "The User-Agent names another system than the browser runs on",
    "software_graphics": "No GPU: software graphics, as in headless and cloud browsers",
    "no_webgl": "No WebGL",
    "no_chrome_object": "Chrome without its window.chrome object",
    "no_plugins": "No browser plugins (desktop)",
    "no_languages": "The browser lists no languages",
    "no_window": "The window has no outer size",
    "no_accept_language": "Requests without Accept-Language",
    "hosting": "Data-centre network",
    "relay": "Relay or VPN network",
    "old_browser": "Chrome many versions out of date",
    "utc_clock": "Browser clock on UTC",
    "distant_clock": "Browser clock set for another part of the world than its IP",
    "odd_screen": "Default screen of headless browsers",
    "crowd": "Many new browsers from this IP in a day",
    "crawl_pace": "Pages at a crawler's pace with no input",
    "no_input": "No mouse, touch, key or wheel input at all",
    "teleport_clicks": "Clicks with no mouse movement towards them",
    "jumping_pointer": "The pointer jumps across the screen",
    "centred_clicks": "Clicks at the exact centre of buttons",
    "fast_typing": "Keys pressed faster than fingers can",
    "filled_fields": "Text appeared in fields without key presses",
    "synthetic_input": "Input events made by a script",
    "mouse_paths": "Mouse moved like a hand does",
    "touches": "Touch input",
    "human_typing": "Typed at a human pace",
    "wheel": "Scrolled with a wheel or trackpad",
    "tab_switches": "Switched to other tabs or apps",
    "returning": "A browser seen on an earlier visit",
    "signed_in": "Signed in to an account",
}
#: Signs of input made by software: automation with them interacts, i.e. an agent.
MACHINE_INPUT = frozenset(
    {
        "teleport_clicks",
        "jumping_pointer",
        "centred_clicks",
        "fast_typing",
        "filled_fields",
        "synthetic_input",
    }
)


@dataclass(frozen=True)
class Reason:
    code: str
    points: int  # > 0 automation, < 0 a person
    detail: str | None = None


@dataclass(frozen=True)
class Facts:
    """A visit as the verdict sees it (visits row + its `signals` + the network)."""

    user_agent: str | None
    browser: str | None
    os: str | None
    device: str
    screen: str | None
    timezone: str | None
    pageviews: int
    engaged_ms: int
    duration_ms: int  # first to last beacon
    returning: bool
    signed_in: bool
    place: str | None = None  # the IP's place, for the reasons' words
    network: str | None = None  # the operator's name
    network_kind: str | None = None  # NetworkKind
    crowd: int = 0  # other new browsers on this IP in the day before
    signals: dict[str, Any] = field(default_factory=dict)
    now: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class Assessment:
    verdict: Verdict
    score: int  # automation points minus person points, within ±100
    reasons: tuple[Reason, ...]

    def stored_reasons(self) -> list[dict[str, Any]]:
        return [
            {"code": r.code, "points": r.points, **({"detail": r.detail} if r.detail else {})}
            for r in self.reasons
        ]


def _parsed[T: BaseModel](model: type[T], raw: Any) -> T | None:
    if not isinstance(raw, dict):
        return None
    try:
        return model.model_validate(raw)
    except ValidationError:
        return None


def _seconds(ms: int) -> str:
    return f"{max(ms, 0) / 1000:.0f} s"


def _browser_reasons(facts: Facts, env: ClientEnv | None, srv: dict[str, Any]) -> list[Reason]:
    out: list[Reason] = []
    desktop = facts.device == "desktop" and facts.os in ("Windows", "macOS", "Linux", "ChromeOS")
    if (env and env.hl) or srv.get("hl"):
        out.append(Reason("headless", 80))
    platforms = [p for p in ((env.plat if env else None), srv.get("chp")) if p]
    wrong = next((p for p in platforms if platform_mismatch(facts.os, p)), None)
    if wrong:
        out.append(Reason("platform_mismatch", 45, f"User-Agent: {facts.os} · browser: {wrong}"))
    if env is not None:
        if env.gl == "soft":
            out.append(Reason("software_graphics", 25))
        elif env.gl == "none" and desktop:
            out.append(Reason("no_webgl", 10))
        chrome_like = facts.browser in _CHROME_BROWSERS and "; wv)" not in (facts.user_agent or "")
        if chrome_like and desktop and env.chr is False:
            out.append(Reason("no_chrome_object", 35))
        if desktop and env.pl == 0 and facts.browser in (*_CHROME_BROWSERS, "Firefox"):
            out.append(Reason("no_plugins", 15))
        if env.ln == 0:
            out.append(Reason("no_languages", 30))
        if desktop and env.ow:
            out.append(Reason("no_window", 30))
    if srv and srv.get("al") is False:
        out.append(Reason("no_accept_language", 20))
    version = chrome_version(facts.user_agent)
    expected = expected_chrome(facts.now)
    if version is not None and version < expected - CHROME_BEHIND:
        out.append(Reason("old_browser", 15, f"Chrome {version}, current ≈ {expected}"))
    if (facts.timezone or "").lower() in _UTC_ZONES:
        out.append(Reason("utc_clock", 10, facts.timezone))
    else:
        longitude = srv.get("lon")
        gap = clock_gap(
            facts.timezone,
            float(longitude) if isinstance(longitude, int | float) else None,
            facts.now,
        )
        if gap is not None and gap > CLOCK_GAP_HOURS:
            where = f" · IP in {facts.place}" if facts.place else ""
            out.append(Reason("distant_clock", 15, f"{facts.timezone}{where}"))
    if facts.screen in _ODD_SCREENS:
        out.append(Reason("odd_screen", 10, facts.screen))
    return out


def _input_reasons(facts: Facts, c: ClientSignals | None) -> list[Reason]:
    out: list[Reason] = []
    if c is None:
        # A visit from before the page counted its input: only its pace is known.
        if facts.pageviews >= 4 and facts.duration_ms < facts.pageviews * 3000:
            detail = f"{facts.pageviews} pages in {_seconds(facts.duration_ms)}"
            out.append(Reason("crawl_pace", 20, detail))
        return out
    inputs = c.mv + c.ck + c.tp + c.ky + c.wh
    if facts.pageviews >= 4 and facts.duration_ms < facts.pageviews * 3000 and inputs == 0:
        detail = f"{facts.pageviews} pages in {_seconds(facts.duration_ms)}"
        out.append(Reason("crawl_pace", 35, detail))
    elif inputs == 0 and facts.engaged_ms >= 20_000:
        points = 20 if facts.device == "desktop" else 15
        out.append(Reason("no_input", points, f"{_seconds(facts.engaged_ms)} on the site"))
    # Input made by software.
    if c.ck >= 2 and c.ckb >= max(2, 0.6 * c.ck):
        out.append(Reason("teleport_clicks", 40, f"{c.ckb} of {c.ck} clicks"))
    elif c.ck == 1 and c.ckb == 1 and c.mv <= 1:
        out.append(Reason("teleport_clicks", 20, "its only click"))
    if c.mv >= 3 and c.jmp >= max(2, 0.4 * c.mv):
        out.append(Reason("jumping_pointer", 25, f"{c.jmp} of {c.mv} moves"))
    presses = c.ck + c.tp
    if c.cc >= 2 and c.cc >= 0.5 * presses:
        out.append(Reason("centred_clicks", 40, f"{c.cc} of {presses} presses"))
    elif c.cc == 1 and presses <= 2:
        out.append(Reason("centred_clicks", 15, f"{c.cc} of {presses} presses"))
    if c.ky >= 8 and c.kf >= 0.5 * c.ky:
        out.append(Reason("fast_typing", 40, f"{c.kf} of {c.ky} keys"))
    if c.fill and not c.ky:
        out.append(Reason("filled_fields", 30, f"{c.fill} times"))
    if c.syn:
        out.append(Reason("synthetic_input", 25, f"{c.syn} events"))
    # A hand.
    if c.mv >= 30 and c.jmp <= 0.1 * c.mv:
        out.append(Reason("mouse_paths", -30, f"{c.mv} moves"))
    elif c.mv >= 5 and c.jmp <= 0.2 * c.mv:
        out.append(Reason("mouse_paths", -10, f"{c.mv} moves"))
    if c.tp >= 2:
        out.append(Reason("touches", -30, f"{c.tp} touches"))
    elif c.tp == 1:
        out.append(Reason("touches", -12, "1 touch"))
    if c.ky >= 5 and c.kf < 0.3 * c.ky:
        out.append(Reason("human_typing", -15, f"{c.ky} keys"))
    if c.wh >= 10:
        out.append(Reason("wheel", -10, f"{c.wh} scrolls"))
    if c.hid:
        out.append(Reason("tab_switches", -5, f"{c.hid} times"))
    return out


def classify(facts: Facts) -> Assessment:
    signals = facts.signals or {}
    counts = _parsed(ClientSignals, signals.get("c"))
    env = _parsed(ClientEnv, signals.get("env"))
    raw_srv = signals.get("srv")
    srv: dict[str, Any] = raw_srv if isinstance(raw_srv, dict) else {}
    reasons: list[Reason] = []
    if srv.get("sig"):
        reasons.append(Reason("signed_agent", 100))
    reasons += _browser_reasons(facts, env, srv)
    if facts.network_kind == "hosting":
        reasons.append(Reason("hosting", 25, facts.network))
    elif facts.network_kind == "relay":
        reasons.append(Reason("relay", 5, facts.network))
    if facts.crowd >= 5:
        reasons.append(Reason("crowd", 20, f"{facts.crowd} others"))
    reasons += _input_reasons(facts, counts)
    if facts.returning:
        reasons.append(Reason("returning", -10))
    if facts.signed_in:
        reasons.append(Reason("signed_in", -10))

    bot = sum(r.points for r in reasons if r.points > 0)
    person = -sum(r.points for r in reasons if r.points < 0)
    machine = any(r.code in MACHINE_INPUT for r in reasons)
    verdict: Verdict
    if srv.get("sig"):
        verdict = "agent"
    elif bot >= 60 and bot - person >= 30:
        verdict = "agent" if machine else "bot"
    elif bot >= 30 and (bot > person or machine):
        # Input no hand makes, next to a hand's: someone shares the browser with an agent.
        verdict = "suspect"
    elif person >= 30 and bot < 30:
        verdict = "human"
    elif person >= 10:
        verdict = "likely_human"
    else:
        verdict = "unclear"
    ordered = tuple(sorted(reasons, key=lambda r: -abs(r.points)))
    return Assessment(verdict, max(-100, min(100, bot - person)), ordered)
