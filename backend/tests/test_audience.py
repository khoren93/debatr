"""Visits of the site (services/audience) and the console's Audience page: the beacon's checks,
where a visit came from, devices, places, the GeoIP download, the upkeep job and who may read
the page. Pure: queries are compiled, not run; the database and Redis are fakes.
"""

import fcntl
import gzip
import re
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.dialects import postgresql

from app.admin.access import current_admin, read_only_db
from app.api import routes_presence
from app.api.admin import routes_audience
from app.core.auth import get_current_user
from app.core.config import settings
from app.core.db import get_db
from app.schemas.admin import VisitListQuery
from app.services.admin import audience, stats
from app.services.audience import collect, geo, jobs
from app.services.audience.agent import parse_agent
from app.services.audience.collect import (
    ACTIONS,
    campaign,
    clean_path,
    clean_referrer,
    page_debate_id,
    page_slug,
    parse_beacon,
    utm_class,
    visit_source,
)
from tests.test_admin_levers import _ctx

NOW = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)
FRONTEND = Path(__file__).resolve().parents[2] / "frontend"

IPHONE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 19_0 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/19.0 Mobile/15E148 Safari/604.1"
)
MAC_SAFARI = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/19.0 Safari/605.1.15"
)
WINDOWS_CHROME = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/141.0.0.0 Safari/537.36"
)
ANDROID_PHONE = (
    "Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/141.0.0.0 Mobile Safari/537.36"
)
ANDROID_TABLET = (
    "Mozilla/5.0 (Linux; Android 15; SM-X910) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/141.0.0.0 Safari/537.36"
)


def _sql(statement: Any) -> str:
    return str(
        statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )


# --- devices -------------------------------------------------------------------------------------


def test_devices_browsers_and_systems() -> None:
    assert parse_agent(IPHONE) == parse_agent(IPHONE, touch=True)
    assert (parse_agent(IPHONE).device, parse_agent(IPHONE).browser) == ("mobile", "Safari")
    assert parse_agent(IPHONE).os == "iOS"
    assert parse_agent(MAC_SAFARI).device == "desktop" and parse_agent(MAC_SAFARI).os == "macOS"
    # iPadOS Safari says "Macintosh"; the page reports the touch screen.
    assert parse_agent(MAC_SAFARI, touch=True).device == "tablet"
    assert parse_agent(MAC_SAFARI, touch=True).os == "iOS"
    assert parse_agent(WINDOWS_CHROME) == parse_agent(WINDOWS_CHROME)
    assert (parse_agent(WINDOWS_CHROME).browser, parse_agent(WINDOWS_CHROME).os) == (
        "Chrome",
        "Windows",
    )
    assert parse_agent(ANDROID_PHONE).device == "mobile"
    assert parse_agent(ANDROID_TABLET).device == "tablet"
    assert parse_agent(WINDOWS_CHROME + " Edg/141.0").browser == "Edge"
    assert parse_agent(WINDOWS_CHROME + " YaBrowser/25.8").browser == "Yandex"
    assert parse_agent(IPHONE + " Instagram 380.0").browser == "Instagram"
    assert parse_agent(ANDROID_PHONE + " Telegram-Android/11.0").browser == "Telegram"
    firefox = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
    assert (parse_agent(firefox).browser, parse_agent(firefox).os) == ("Firefox", "Linux")
    assert parse_agent(None) == parse_agent("")
    assert parse_agent(None).device == "desktop" and parse_agent(None).browser is None


# --- the beacon ---------------------------------------------------------------------------------


def _beacon(**fields: Any) -> bytes:
    body = {"visitor": str(uuid.uuid4()), "visit": str(uuid.uuid4()), "events": []} | fields
    return httpx.Request("POST", "http://t", json=body).content


def test_beacons_are_checked_and_trimmed() -> None:
    page_id = str(uuid.uuid4())
    beacon = parse_beacon(
        _beacon(
            events=[
                {"type": "page", "id": page_id, "path": "/gallery", "query": "?utm_source=x"},
                {"type": "time", "id": page_id, "ms": 5000},
                {
                    "type": "action",
                    "name": "video_play",
                    "props": {f"k{i}": "v" * 300 for i in range(12)},
                },
            ],
            screen="1440x900",
        )
    )
    assert beacon is not None and [e.type for e in beacon.events] == ["page", "time", "action"]
    props = beacon.events[2].props
    assert len(props) == 8 and all(len(str(v)) == 100 for v in props.values())
    assert parse_beacon(b"") is None
    assert parse_beacon(b"not json") is None
    assert parse_beacon(_beacon(visitor="nope")) is None
    assert parse_beacon(_beacon(events=[{"type": "time", "ms": 99_999_999}])) is None
    assert parse_beacon(_beacon(events=[{"type": "page"}] * 41)) is None
    assert parse_beacon(b"{" + b" " * collect.MAX_BODY + b"}") is None
    # The page's input counts and the browser's facts.
    counted = parse_beacon(
        _beacon(signals={"mv": 40, "ck": 2}, env={"gl": "soft", "plat": "Win32"})
    )
    assert counted is not None and counted.signals is not None and counted.env is not None
    assert (counted.signals.mv, counted.signals.ck, counted.env.gl) == (40, 2, "soft")
    assert parse_beacon(_beacon(signals={"mv": -1})) is None
    assert parse_beacon(_beacon(env={"gl": "quantum"})) is None


def test_paths_and_referrers_keep_no_query() -> None:
    assert clean_path("/device?code=WDJB-MJHT") == "/device"
    assert clean_path("/d/abc123/tabs-or-spaces#t=5") == "/d/abc123/tabs-or-spaces"
    assert clean_path("https://evil.example/x") == "/x"
    assert clean_path("") == "/" and clean_path("nope") == "/"
    assert len(clean_path("/" + "a" * 500)) == 300
    assert (
        clean_referrer("https://www.google.com/search?q=secret") == "https://www.google.com/search"
    )
    assert clean_referrer("android-app://org.telegram.messenger/") is None
    assert clean_referrer(None) is None


def test_the_landing_campaign() -> None:
    assert campaign(
        "?utm_source=Telegram&utm_medium=social&utm_campaign=launch<script>&ref=embed"
    ) == {
        "utm_source": "Telegram",
        "utm_medium": "social",
        "utm_campaign": "launchscript",
        "ref": "embed",
    }
    assert campaign(None) == {
        "utm_source": None,
        "utm_medium": None,
        "utm_campaign": None,
        "ref": None,
    }
    assert utm_class("telegram", None) == "social"
    assert utm_class("chatgpt.com", None) == "ai"
    assert utm_class("google", "cpc") == "search"
    assert utm_class("newsletter", "email") == "other"
    assert utm_class(None, None) is None


def test_where_a_visit_came_from() -> None:
    def source(referrer: str | None, query: str | None = None, resumed: bool = False) -> Any:
        return visit_source(
            referrer,
            campaign(query),
            site_host="debatr.tv",
            site_aliases=("ai-debates.net",),
            resumed=resumed,
        )

    assert source("https://www.google.com/") == ("search", "google.com")
    assert source("https://chatgpt.com/") == ("ai", "chatgpt.com")
    assert source("https://t.me/somechannel") == ("social", "t.me")
    assert source("https://blog.example.org/post") == ("other", "blog.example.org")
    assert source(None) == ("direct", None)
    assert source(None, "?utm_source=telegram") == ("social", None)
    assert source("https://news.example/", "?ref=embed") == ("embed", "news.example")
    # The site's own pages and its former domain are not referrers.
    assert source("https://debatr.tv/gallery") == ("internal", None)
    assert source("https://ai-debates.net/d/x") == ("internal", None)
    assert source("https://www.google.com/", resumed=True) == ("internal", None)


def test_debate_pages() -> None:
    assert page_slug("/d/abc123/tabs-or-spaces") == "abc123"
    assert page_slug("/d/abc123") == "abc123"
    assert page_slug("/t/abc123") is None and page_slug("/gallery") is None
    debate = uuid.uuid4()
    assert page_debate_id(f"/debate/{debate}") == debate
    assert page_debate_id("/debate/not-an-id") is None


def test_the_site_reports_only_known_actions() -> None:
    """lib/presence.ts names its actions in a union type; each one must be in ACTIONS."""
    source = (FRONTEND / "src/lib/presence.ts").read_text()
    union = re.search(r"export type PresenceAction =([^;]+);", source)
    assert union is not None
    names = re.findall(r"'([a-z0-9_]+)'", union.group(1))
    assert names and set(names) <= set(ACTIONS)
    # The console's words mirror ACTIONS (components/admin/audience/format.ts).
    console = (FRONTEND / "src/components/admin/audience/format.ts").read_text()
    labels = re.search(r"export const ACTION_LABELS[^=]*= \{([^}]+)\}", console)
    assert labels is not None
    assert dict(re.findall(r"(\w+): '([^']+)'", labels.group(1))) == ACTIONS


# --- the beacon route -----------------------------------------------------------------------------


@pytest.fixture
def presence_app(monkeypatch: pytest.MonkeyPatch) -> tuple[FastAPI, list[Any]]:
    recorded: list[Any] = []

    async def fake_record(db: Any, beacon: Any, ctx: Any) -> bool:
        recorded.append((beacon, ctx))
        return True

    async def no_limit(*args: Any, **kwargs: Any) -> None:
        return None

    async def fake_db() -> AsyncIterator[Any]:
        yield None

    monkeypatch.setattr(routes_presence, "record", fake_record)
    monkeypatch.setattr(routes_presence, "enforce_limit", no_limit)
    app = FastAPI()
    app.include_router(routes_presence.router, prefix="/api")
    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_current_user] = lambda: None
    return app, recorded


async def test_the_beacon_route(presence_app: tuple[FastAPI, list[Any]], levers: dict) -> None:
    app, recorded = presence_app
    body = _beacon(events=[{"type": "page", "path": "/"}])
    browser = {"User-Agent": WINDOWS_CHROME, "Content-Type": "text/plain"}
    transport = httpx.ASGITransport(app=app, client=("203.0.113.9", 1234))
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        assert (
            await client.post("/api/presence", content=body, headers=browser)
        ).status_code == 204
        assert len(recorded) == 1 and recorded[0][1].ip == "203.0.113.9"
        assert recorded[0][1].user_agent == WINDOWS_CHROME
        # Its headers go to the verdict.
        assert recorded[0][1].request.signed_agent is False
        assert recorded[0][1].request.accept_language is False
        # Bots, unreadable beacons and a switched-off lever: the same 204, nothing written.
        bot = {"User-Agent": "Googlebot/2.1", "Content-Type": "text/plain"}
        assert (await client.post("/api/presence", content=body, headers=bot)).status_code == 204
        assert (
            await client.post("/api/presence", content=b"{}", headers=browser)
        ).status_code == 204
        levers["analytics_enabled"] = False
        assert (
            await client.post("/api/presence", content=body, headers=browser)
        ).status_code == 204
    assert len(recorded) == 1


# --- places ----------------------------------------------------------------------------------------


def test_places_from_a_city_record() -> None:
    record = {
        "country": {"iso_code": "am", "names": {"en": "Armenia"}},
        "subdivisions": [{"names": {"en": "Yerevan"}}],
        "city": {"names": {"en": "Yerevan"}},
    }
    assert geo.place_of(record) == geo.Place("AM", "Yerevan", "Yerevan")
    assert geo.place_of({"registered_country": {"iso_code": "DE"}}) == geo.Place("DE", None, None)
    located = geo.place_of(record | {"location": {"latitude": 40.2, "longitude": 44.5}})
    assert located is not None and located.longitude == 44.5
    assert geo.place_of({}) is None and geo.place_of(None) is None
    assert geo.is_public_ip("8.8.8.8") and geo.is_public_ip("2001:4860:4860::8888")
    for private in ("127.0.0.1", "10.0.0.5", "172.18.0.3", "192.168.1.1", "::1", "nope", ""):
        assert not geo.is_public_ip(private)
    assert geo.lookup("192.168.1.1") is None and geo.lookup(None) is None


def test_networks_from_an_asn_record() -> None:
    record = {"autonomous_system_number": 24940, "autonomous_system_organization": "Hetzner"}
    assert geo.network_of(record) == geo.Network(24940, "Hetzner")
    assert geo.network_of({"autonomous_system_number": 0}) is None
    assert geo.network_of({}) is None and geo.network_of("x") is None
    assert geo.network("10.0.0.5") is None and geo.network(None) is None


def test_monthly_releases() -> None:
    assert geo._months(date(2026, 10, 21)) == ["2026-10", "2026-09"]
    assert geo._months(date(2026, 1, 1)) == ["2026-01", "2025-12"]


def test_a_broken_download_never_replaces_the_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "GEOIP_DIR", str(tmp_path))
    asked: list[str] = []

    def answer(request: httpx.Request) -> httpx.Response:
        asked.append(str(request.url))
        if len(asked) == 1:
            return httpx.Response(404)
        return httpx.Response(200, content=gzip.compress(b"not a database"))

    assert geo.update_due()
    assert not geo.update(transport=httpx.MockTransport(answer))
    assert len(asked) == 2 and "dbip-city-lite-" in asked[0]
    assert not geo.database_path().exists()
    assert not list(tmp_path.glob("*.part"))
    # A failed try waits a day before the next one; the network database keeps its own clock.
    assert not geo.update_due()
    assert geo.update_due(datetime.now(UTC) + timedelta(days=2))
    assert geo.update_due(db=geo.ASN)
    assert not geo.update(transport=httpx.MockTransport(answer), db=geo.ASN)
    assert "dbip-asn-lite-" in asked[-1] and not geo.database_path(geo.ASN).exists()
    monkeypatch.setattr(settings, "GEOIP_URL", "")
    assert not geo.update_due() and not geo.update()


def test_one_download_at_a_time(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "GEOIP_DIR", str(tmp_path))
    asked: list[str] = []

    def answer(request: httpx.Request) -> httpx.Response:
        asked.append(str(request.url))
        return httpx.Response(404)

    with (tmp_path / geo.LOCK).open("w") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert not geo.update(transport=httpx.MockTransport(answer))
    assert not asked


def test_ips_are_kept_for_the_lever_days() -> None:
    class Fake:
        def __init__(self) -> None:
            self.statements: list[str] = []

        def execute(self, statement: Any) -> Any:
            self.statements.append(_sql(statement))
            return type("Result", (), {"rowcount": 3})()

        def commit(self) -> None:
            pass

    db = Fake()
    assert jobs.forget_old_addresses(db, 0) == 0 and not db.statements  # type: ignore[arg-type]
    assert jobs.forget_old_addresses(db, 90) == 3  # type: ignore[arg-type]
    (sql,) = db.statements
    assert "UPDATE visits SET ip=NULL, user_agent=NULL" in sql
    assert "visits.ip IS NOT NULL OR visits.user_agent IS NOT NULL" in sql


# --- the console ------------------------------------------------------------------------------------


def test_visit_search_and_filters() -> None:
    window = stats.window_for("7d", NOW)
    query = VisitListQuery(
        q="203.0.113", source="search", country="am", signed_in=False, action="signup"
    )
    sql = " AND ".join(_sql(c) for c in audience.list_conditions(query, window))
    assert "visits.staff IS false" in sql and "visits.source = 'search'" in sql
    assert "visits.country = 'AM'" in sql and "visits.user_id IS NULL" in sql
    assert "visit_events.name = 'signup'" in sql
    assert "visits.ip LIKE '203.0.113' || '%%'" in sql
    assert "users.email ILIKE '%%203.0.113%%'" in sql
    staff = audience.list_conditions(VisitListQuery(staff=True), window)
    assert "staff" not in " ".join(_sql(c) for c in staff)
    # The list shows bots with their verdict; a filter picks a verdict or a group.
    assert "verdict" not in sql
    people = audience.list_conditions(VisitListQuery(verdict="people"), window)
    assert "visits.verdict IN ('human', 'likely_human')" in " ".join(_sql(c) for c in people)
    agents = audience.list_conditions(VisitListQuery(verdict="agent"), window)
    assert "visits.verdict IN ('agent')" in " ".join(_sql(c) for c in agents)
    exact = uuid.uuid4()
    assert str(exact).replace("-", "") in _sql(audience.search(str(exact))).replace("-", "")
    assert audience.search("  ") is None


def test_the_numbers_leave_out_bots_unless_asked() -> None:
    def where(who: audience.Who) -> str:
        return " AND ".join(_sql(c) for c in audience.scope(None, NOW, who))

    assert "visits.verdict NOT IN ('bot', 'agent')" in where(audience.Who())
    assert "visits.staff IS false" in where(audience.Who())
    assert "verdict" not in where(audience.Who(bots=True))
    assert "staff" not in where(audience.Who(staff=True, bots=True))


def test_stored_reasons_get_the_consoles_words() -> None:
    reasons = audience.reasons_of(
        [{"code": "hosting", "points": 25, "detail": "Hetzner"}, {"code": 5}, "junk"]
    )
    assert [(r.code, r.points, r.detail) for r in reasons] == [("hosting", 25, "Hetzner")]
    assert reasons[0].label == "Data-centre network"
    assert audience.reasons_of(None) == []


def test_parts_of_the_site() -> None:
    sql = _sql(audience.section_of())
    assert "visit_events.path = '/'" in sql and "THEN 'home'" in sql
    assert "LIKE '/d/' || '%%'" in sql and "THEN 'debate'" in sql
    assert "ELSE 'other'" in sql


async def test_only_admins_see_the_audience() -> None:
    async def fake_db() -> AsyncIterator[Any]:
        yield None

    app = FastAPI()
    app.include_router(routes_audience.router, prefix="/api/admin")
    app.dependency_overrides[read_only_db] = fake_db
    app.dependency_overrides[current_admin] = lambda: _ctx("moderator")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        for path in (
            "audience",
            "audience/live",
            "audience/visits",
            f"audience/visits/{uuid.uuid4()}",
            f"users/{uuid.uuid4()}/visits",
        ):
            assert (await client.get(f"/api/admin/{path}")).status_code == 403, path
