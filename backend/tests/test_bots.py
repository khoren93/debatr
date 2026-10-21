"""A person, a bot or an AI agent per visit (services/audience/bots.py): the signals, the
networks and the verdict. Pure."""

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.services.audience import bots
from app.services.audience.bots import (
    ClientEnv,
    ClientSignals,
    Facts,
    RequestFacts,
    classify,
    merge,
    network_kind,
    platform_family,
    platform_mismatch,
    request_facts,
)

NOW = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)
FRONTEND = Path(__file__).resolve().parents[2] / "frontend"

WINDOWS_CHROME = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/153.0.0.0 Safari/537.36"
)
ANDROID_PHONE = (
    "Mozilla/5.0 (Linux; Android 16; Pixel 10) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/153.0.0.0 Mobile Safari/537.36"
)


def _facts(**changes: Any) -> Facts:
    base: dict[str, Any] = {
        "user_agent": WINDOWS_CHROME,
        "browser": "Chrome",
        "os": "Windows",
        "device": "desktop",
        "screen": "1920x1080",
        "timezone": "Europe/Berlin",
        "pageviews": 2,
        "engaged_ms": 45_000,
        "duration_ms": 60_000,
        "returning": False,
        "signed_in": False,
        "now": NOW,
    }
    return Facts(**(base | changes))


def _signals(
    env: dict[str, Any] | None = None, platform: str = "Windows", **counts: int
) -> dict[str, Any]:
    return merge(
        None,
        ClientSignals(**counts),
        ClientEnv(**({"gl": "hw", "plat": "Win32", "pl": 5, "ln": 2, "chr": True} | (env or {}))),
        RequestFacts(ch_platform=platform),
    )


def _codes(facts: Facts) -> set[str]:
    return {r.code for r in classify(facts).reasons}


def test_a_person_at_a_desk() -> None:
    result = classify(
        _facts(signals=_signals(mv=240, jmp=1, ck=6, ckb=1, wh=40, ky=12, kf=1), returning=True)
    )
    assert result.verdict == "human" and result.score < 0
    assert {"mouse_paths", "wheel", "human_typing", "returning"} <= {r.code for r in result.reasons}
    assert not [r for r in result.reasons if r.points > 0]
    # The strongest reason first.
    assert result.reasons[0].code == "mouse_paths"


def test_a_person_on_a_phone() -> None:
    signals = _signals({"plat": "Linux armv81", "pl": 0}, platform="Android", tp=9)
    facts = _facts(user_agent=ANDROID_PHONE, os="Android", device="mobile", signals=signals)
    assert classify(facts).verdict == "human"
    # Android's platform names the kernel; a phone has no plugins: neither counts.
    assert not {"platform_mismatch", "no_plugins"} & _codes(facts)


def test_a_short_visit_is_unclear() -> None:
    assert classify(_facts(signals=_signals(), engaged_ms=3000)).verdict == "unclear"
    assert classify(_facts(signals=_signals(mv=8), engaged_ms=3000)).verdict == "likely_human"
    # A visit from before the page counted its input.
    assert classify(_facts()).verdict == "unclear"


def test_a_headless_crawler_in_a_data_centre() -> None:
    signals = _signals({"gl": "soft", "plat": "Linux x86_64", "chr": False})
    facts = _facts(
        signals=signals,
        network="Amazon.com, Inc.",
        network_kind="hosting",
        pageviews=9,
        duration_ms=14_000,
        timezone="UTC",
    )
    result = classify(facts)
    assert result.verdict == "bot" and result.score == 100
    assert {
        "software_graphics",
        "no_chrome_object",
        "platform_mismatch",
        "hosting",
        "crawl_pace",
        "utc_clock",
    } <= {r.code for r in result.reasons}
    mismatch = next(r for r in result.reasons if r.code == "platform_mismatch")
    assert mismatch.detail == "User-Agent: Windows · browser: Linux x86_64"
    # Sitting still is not a crawler's pace.
    idle = _facts(signals=_signals(), engaged_ms=40_000)
    assert "no_input" in _codes(idle) and "crawl_pace" not in _codes(idle)


def test_an_agent_clicking_through_a_real_browser() -> None:
    # A residential network and a GPU, but clicks with no way there, at the centre of buttons,
    # and text that appears without keys.
    result = classify(_facts(signals=_signals(mv=4, jmp=3, ck=5, ckb=5, cc=4, fill=2)))
    assert result.verdict == "agent"
    assert {"teleport_clicks", "centred_clicks", "filled_fields", "jumping_pointer"} <= {
        r.code for r in result.reasons
    }
    # Fast typing and script-made events are an agent's too.
    typed = classify(_facts(signals=_signals(ky=40, kf=38, syn=3), network_kind="hosting"))
    assert typed.verdict == "agent"


def test_a_person_and_an_agent_in_one_visit_is_suspect() -> None:
    # A hand moves the mouse, yet half the presses land on the exact centre of buttons.
    signals = _signals(mv=300, jmp=4, ck=6, ckb=1, cc=3, wh=12)
    result = classify(_facts(signals=signals, returning=True))
    assert result.verdict == "suspect" and result.score < 0


def test_an_agent_that_signs_its_requests() -> None:
    signals = merge(None, None, None, RequestFacts(signed_agent=True))
    result = classify(_facts(signals=signals))
    assert result.verdict == "agent" and result.reasons[0].code == "signed_agent"


def test_a_person_on_a_vpn_stays_a_person() -> None:
    facts = _facts(
        signals=_signals(mv=120, ck=3, wh=15), network="M247 Europe SRL", network_kind="hosting"
    )
    assert classify(facts).verdict == "human"
    assert "hosting" in _codes(facts)


def test_old_browsers_and_odd_screens() -> None:
    old = WINDOWS_CHROME.replace("Chrome/153", "Chrome/120")
    reason = next(
        r
        for r in classify(_facts(user_agent=old, signals=_signals())).reasons
        if r.code == "old_browser"
    )
    assert reason.detail == "Chrome 120, current ≈ 154"
    assert bots.expected_chrome(NOW) == 154
    assert "old_browser" not in _codes(_facts(signals=_signals()))
    assert "odd_screen" in _codes(_facts(screen="800x600"))
    assert "crowd" in _codes(_facts(crowd=6)) and "crowd" not in _codes(_facts(crowd=2))


def test_a_clock_from_another_part_of_the_world() -> None:
    def gap(zone: str, longitude: float) -> float | None:
        return bots.clock_gap(zone, longitude, NOW)

    # Yerevan's clock on an IP near Washington; Berlin's on one near Berlin.
    assert (gap("Asia/Yerevan", -77.4) or 0) > bots.CLOCK_GAP_HOURS
    assert (gap("Europe/Berlin", 13.4) or 99) < 2  # summer time
    # Western China keeps Beijing's clock; Madrid lies west of its zone; the date line wraps.
    assert (gap("Asia/Shanghai", 76.0) or 99) < bots.CLOCK_GAP_HOURS
    assert (gap("Europe/Madrid", -3.7) or 99) < bots.CLOCK_GAP_HOURS
    assert (gap("Pacific/Auckland", -178.0) or 99) < 3
    assert gap("Mars/Olympus", 0) is None and bots.clock_gap(None, 10, NOW) is None
    signals = _signals(mv=40) | {"srv": {"lon": -77.4}}
    far = _facts(timezone="Asia/Yerevan", signals=signals, place="Dulles, US")
    reason = next(r for r in classify(far).reasons if r.code == "distant_clock")
    assert reason.detail == "Asia/Yerevan · IP in Dulles, US"
    assert "distant_clock" not in _codes(_facts(timezone="America/New_York", signals=signals))


def test_android_webviews_and_ios_have_no_chrome_object() -> None:
    webview = ANDROID_PHONE.replace("Mobile Safari", "Mobile Safari; wv)")
    facts = _facts(
        user_agent=webview, os="Android", device="mobile", signals=_signals({"chr": False})
    )
    assert "no_chrome_object" not in _codes(facts)
    # A phone's window may report no outer size.
    assert "no_window" not in _codes(
        _facts(os="iOS", device="mobile", signals=_signals({"ow": True}))
    )
    assert "no_window" in _codes(_facts(signals=_signals({"ow": True})))


def test_signals_add_up() -> None:
    first = merge(None, ClientSignals(mv=3, ck=1), ClientEnv(gl="hw"), RequestFacts())
    second = merge(
        first,
        ClientSignals(mv=2, tp=1),
        None,
        RequestFacts(signed_agent=True, accept_language=False, ch_platform="macOS"),
    )
    assert second["c"] == {"mv": 5, "ck": 1, "tp": 1}
    assert second["env"] == {"gl": "hw"}
    assert second["srv"] == {"sig": True, "hl": False, "chp": "macOS", "al": False}
    # Once seen, a signature and a missing Accept-Language stay.
    third = merge(second, None, None, RequestFacts())
    assert third["srv"]["sig"] and third["srv"]["al"] is False
    assert merge({"junk": 1}, None, None, None) == {}
    # A page that describes its browser counts its input too, even when there was none.
    assert merge(None, None, ClientEnv(gl="hw"), None)["c"] == {}


def test_request_headers() -> None:
    headers = {
        "signature-agent": '"https://chatgpt.com"',
        "sec-ch-ua": '"Chromium";v="153", "HeadlessChrome";v="153"',
        "sec-ch-ua-platform": '"Linux"',
    }
    facts = request_facts(headers)
    assert facts == RequestFacts(
        signed_agent=True, headless_brand=True, ch_platform="Linux", accept_language=False
    )
    assert request_facts({"accept-language": "en-US"}) == RequestFacts()


def test_networks() -> None:
    assert network_kind(24940, "Hetzner Online GmbH") == "hosting"
    assert network_kind(None, "Akamai Connected Cloud") == "hosting"
    assert network_kind(None, "Example Hosting LLC") == "hosting"
    assert network_kind(13335, "Cloudflare, Inc.") == "relay"
    assert network_kind(None, "Akamai Technologies, Inc.") == "relay"
    assert network_kind(12297, "Telecom Armenia OJSC") is None
    assert network_kind(None, None) is None


def test_platforms() -> None:
    assert [platform_family(p) for p in ("Win32", '"macOS"', "iPhone", "Linux armv8l")] == [
        "windows",
        "mac",
        "ios",
        "linux",
    ]
    assert platform_family("Chrome OS") == "chromeos" and platform_family("") is None
    assert platform_mismatch("Windows", "Linux x86_64")
    assert platform_mismatch("macOS", "Win32")
    assert not platform_mismatch("Android", "Linux armv81")
    assert not platform_mismatch("ChromeOS", "Linux x86_64")
    assert not platform_mismatch("iOS", "MacIntel")  # an iPad asking for desktop sites
    assert not platform_mismatch(None, "Win32") and not platform_mismatch("Windows", "Plan 9")


def test_every_reason_has_words() -> None:
    codes = set(re.findall(r'Reason\("(\w+)"', Path(bots.__file__).read_text()))
    assert codes and codes <= set(bots.REASONS)
    assert all(code in bots.REASONS for code in bots.MACHINE_INPUT)


def test_the_page_counts_what_the_server_reads() -> None:
    """The page (lib/presence.ts) counts its input in api/presence.ts' Signals and describes the
    browser with its BrowserEnv: ClientSignals' and ClientEnv's fields."""
    source = (FRONTEND / "src/api/presence.ts").read_text()
    for name, model in (("Signals", ClientSignals), ("BrowserEnv", ClientEnv)):
        body = re.search(rf"interface {name} \{{([^}}]+)\}}", source)
        assert body is not None, name
        keys = set(re.findall(r"^\s*(\w+)\??:", body.group(1), re.MULTILINE))
        assert keys == set(model.model_fields), name
