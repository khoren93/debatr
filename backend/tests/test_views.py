"""Views by source (services/views): bots, referrer hosts, classes and the beacon's body."""

import pytest

from app.api.routes_reactions import ViewBeacon, _beacon
from app.services.admin.debates import view_breakdown
from app.services.admin.stats import view_columns
from app.services.views import SOURCES, classify, host_of, is_bot

SITE = "debatr.example"
CHROME = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/141.0.0.0 Safari/537.36"
)
IPHONE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 19_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like "
    "Gecko) Version/19.0 Mobile/15E148 Safari/604.1"
)


@pytest.mark.parametrize(
    "agent",
    [
        None,
        "",
        "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
        "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; bingbot/2.0)",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 HeadlessChrome/141.0",
        "Mozilla/5.0 (Linux; Android 11) Chrome-Lighthouse",
        "Mozilla/5.0 (compatible; Google-InspectionTool/1.0)",
        "facebookexternalhit/1.1",
        "TelegramBot (like TwitterBot)",
        "python-httpx/0.28.1",
        "curl/8.7.1",
        "Mozilla/5.0 (compatible; YandexBot/3.0; +http://yandex.com/bots)",
    ],
)
def test_bots_are_not_views(agent: str | None) -> None:
    assert is_bot(agent)


@pytest.mark.parametrize(
    "agent",
    [CHROME, IPHONE, "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"],
)
def test_browsers_are_views(agent: str) -> None:
    assert not is_bot(agent)


def test_host_of() -> None:
    assert host_of("https://www.Google.com/") == "google.com"
    assert host_of("https://news.ycombinator.com/item?id=1") == "news.ycombinator.com"
    assert host_of("t.co") == "t.co"
    assert host_of("WWW.Example.org:8443") == "example.org"
    assert host_of("localhost") == "localhost"
    assert host_of("http://localhost:5173/d/x") == "localhost"
    for junk in (
        "",
        None,
        "   ",
        "not a host",
        "http://[::1",
        "<script>",
        "a" * 300 + ".com",
        "intranet",
    ):
        assert host_of(junk) is None


@pytest.mark.parametrize(
    ("host", "source"),
    [
        ("google.com", "search"),
        ("google.co.uk", "search"),
        ("google.com.br", "search"),
        ("news.google.com", "search"),
        ("bing.com", "search"),
        ("cn.bing.com", "search"),
        ("duckduckgo.com", "search"),
        ("yandex.ru", "search"),
        ("ya.ru", "search"),
        ("search.brave.com", "search"),
        ("gemini.google.com", "ai"),
        ("chatgpt.com", "ai"),
        ("perplexity.ai", "ai"),
        ("claude.ai", "ai"),
        ("t.co", "social"),
        ("l.facebook.com", "social"),
        ("old.reddit.com", "social"),
        ("t.me", "social"),
        ("web.telegram.org", "social"),
        ("youtube.com", "social"),
        ("news.ycombinator.com", "social"),
        ("mail.google.com", "other"),
        ("docs.google.com", "other"),
        ("someblog.example", "other"),
        ("notgoogle.com", "other"),
        ("t.co.evil.example", "other"),
        (None, "direct"),
        (SITE, "internal"),
    ],
)
def test_classify_pages(host: str | None, source: str) -> None:
    assert classify(host, site_host=SITE) == source


def test_classify_embeds_and_navigation() -> None:
    # The player on another site, and its "Watch on Debatr" link to the page.
    assert classify("someblog.example", site_host=SITE, place="embed") == "embed"
    assert classify(None, site_host=SITE, place="embed") == "embed"
    assert classify(SITE, site_host=SITE, ref="embed") == "embed"
    assert classify(None, site_host=SITE, ref="embed") == "embed"
    # The Share menu's preview plays the player on the site itself.
    assert classify(SITE, site_host=SITE, place="embed") == "internal"
    # A navigation inside the site keeps the first page's referrer: it does not count.
    assert classify("google.com", site_host=SITE, internal=True) == "internal"
    # An unknown ref changes nothing.
    assert classify("google.com", site_host=SITE, ref="newsletter") == "search"


def test_beacon_body() -> None:
    assert _beacon(b"") == ViewBeacon()
    assert _beacon(b"not json") == ViewBeacon()
    assert _beacon(b'{"place": "elsewhere"}') == ViewBeacon()
    assert _beacon(b'{"place": "embed", "referrer": "blog.example", "ref": ""}') == ViewBeacon(
        place="embed", referrer="blog.example"
    )
    assert _beacon(b'{"internal": true, "ref": "embed"}') == ViewBeacon(internal=True, ref="embed")
    # A huge body is cut before parsing (and then fails validation: the defaults).
    assert _beacon(b'{"referrer": "' + b"a" * 5000 + b'"}') == ViewBeacon()


def test_view_breakdown() -> None:
    counts = {
        ("search", "page"): 5,
        ("embed", "embed"): 3,
        ("embed", "page"): 1,
        ("direct", "page"): 2,
    }
    out = view_breakdown(counts, total=20)
    assert out["sources"] == [
        {"source": "search", "page": 5, "embed": 0},
        {"source": "embed", "page": 1, "embed": 3},
        {"source": "direct", "page": 2, "embed": 0},
    ]
    assert out["untracked"] == 9
    assert view_breakdown({}, total=0) == {"total": 0, "sources": [], "untracked": 0}
    # A counter behind the rows (an old restore) never goes negative.
    assert view_breakdown({("search", "page"): 4}, total=1)["untracked"] == 0


def test_series_has_a_column_per_source() -> None:
    assert view_columns() == [f"views_{source}" for source in SOURCES]
    assert len(set(SOURCES)) == 7
