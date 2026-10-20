"""Canonical addresses, robots.txt and sitemaps (services/seo)."""

from datetime import UTC, datetime, timedelta, timezone

from app.services import seo
from app.services.seo import SitemapUrl


def test_kebab_keeps_words_of_any_script() -> None:
    assert seo.kebab("Is remote work better than the office?") == (
        "is-remote-work-better-than-the-office"
    )
    assert seo.kebab("  Tabs — or SPACES?!  ") == "tabs-or-spaces"
    assert seo.kebab("Isn't AI overhyped? Don\u2019t ask") == "isnt-ai-overhyped-dont-ask"
    assert seo.kebab("Лучше ли удалённая работа, чем офис?") == "лучше-ли-удалённая-работа-чем-офис"
    # Combining marks stay inside their word (Devanagari vowel signs, virama).
    assert seo.kebab("क्या हिंदी कठिन है?") == "क्या-हिंदी-कठिन-है"
    assert seo.kebab("远程工作比办公室更好吗\uff1f") == "远程工作比办公室更好吗"
    # NFKC: fullwidth letters and digits become plain ones.
    assert seo.kebab("\uff26\uff55\uff4c\uff4c \uff12\uff10\uff12\uff16") == "full-2026"
    assert seo.kebab("🔥🤖 ?!") == ""


def test_kebab_cuts_between_words() -> None:
    text = "Should governments regulate frontier artificial intelligence models before release?"
    words = seo.kebab(text)
    assert len(words) <= seo.KEBAB_MAX
    assert words == "should-governments-regulate-frontier-artificial-intelligence"
    # One word longer than the limit (scripts without spaces) is cut as it is.
    assert seo.kebab("a" * 80) == "a" * seo.KEBAB_MAX
    assert seo.kebab("x" * 80, limit=10) == "x" * 10


def test_paths() -> None:
    assert seo.debate_path("abc123", "Tabs or spaces?") == "/d/abc123/tabs-or-spaces"
    assert seo.debate_path("abc123", "?!") == "/d/abc123"
    assert seo.topic_path("t0p1c", "Cats or dogs") == "/t/t0p1c/cats-or-dogs"
    assert seo.absolute("https://example.com/", "/d/x") == "https://example.com/d/x"


def test_encoded_escapes_only_non_ascii() -> None:
    assert seo.encoded("https://example.com/d/x/tabs-or-spaces") == (
        "https://example.com/d/x/tabs-or-spaces"
    )
    assert seo.encoded("https://example.com/d/x/офис") == (
        "https://example.com/d/x/%D0%BE%D1%84%D0%B8%D1%81"
    )
    # Already encoded stays as it is; queries keep their separators.
    assert seo.encoded("https://e.com/d/x/%D0%BE") == "https://e.com/d/x/%D0%BE"
    assert seo.encoded("https://e.com/gallery?format=rap_battle&a=1") == (
        "https://e.com/gallery?format=rap_battle&a=1"
    )


def test_robots_outside_production_refuses_everything() -> None:
    text = seo.robots_txt(site_url="http://localhost", production=False, allow_ai=True)
    assert text == "User-agent: *\nDisallow: /\n"


def test_robots_in_production() -> None:
    text = seo.robots_txt(site_url="https://debatr.example/", production=True, allow_ai=True)
    lines = text.splitlines()
    assert lines[:2] == ["User-agent: *", "Allow: /"]
    for prefix in ("/api/", "/library", "/account", "/create", "/device", "/debate/"):
        assert f"Disallow: {prefix}" in lines
    assert "Disallow: /d/" not in lines and "Disallow: /embed/" not in lines
    assert lines[-1] == "Sitemap: https://debatr.example/sitemap.xml"
    assert "GPTBot" not in text

    closed = seo.robots_txt(site_url="https://debatr.example", production=True, allow_ai=False)
    group = closed.split("\n\n")[1].splitlines()
    assert "User-agent: GPTBot" in group and "User-agent: ClaudeBot" in group
    assert group[-1] == "Disallow: /"


def test_urlset() -> None:
    moment = datetime(2026, 10, 20, 15, 30, 5, 123, tzinfo=timezone(timedelta(hours=4)))
    xml = seo.urlset(
        [
            SitemapUrl("https://e.com/d/a/tabs-&-spaces", moment),
            SitemapUrl("https://e.com/d/b/офис"),
        ]
    )
    assert xml.startswith('<?xml version="1.0" encoding="UTF-8"?>\n<urlset ')
    assert "xmlns:image" not in xml
    assert "<loc>https://e.com/d/a/tabs-&amp;-spaces</loc>" in xml
    assert "<lastmod>2026-10-20T11:30:05Z</lastmod>" in xml
    assert "<loc>https://e.com/d/b/%D0%BE%D1%84%D0%B8%D1%81</loc></url>" in xml

    with_images = seo.urlset([SitemapUrl("https://e.com/d/a", images=["https://e.com/og/a.png"])])
    assert 'xmlns:image="http://www.google.com/schemas/sitemap-image/1.1"' in with_images
    assert "<image:image><image:loc>https://e.com/og/a.png</image:loc></image:image>" in with_images


def test_sitemap_index_and_counts() -> None:
    naive = datetime(2026, 10, 1, 8, 0)
    xml = seo.sitemap_index(
        [SitemapUrl("https://e.com/sitemaps/pages.xml", naive), SitemapUrl("https://e.com/x.xml")]
    )
    assert "<sitemapindex " in xml
    assert (
        "<sitemap><loc>https://e.com/sitemaps/pages.xml</loc>"
        "<lastmod>2026-10-01T08:00:00Z</lastmod></sitemap>"
    ) in xml
    assert "<sitemap><loc>https://e.com/x.xml</loc></sitemap>" in xml
    assert [seo.debate_sitemap_count(n) for n in (0, 1, 10_000, 10_001)] == [0, 1, 1, 2]
    first, second = datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 2, 1, tzinfo=UTC)
    assert seo.latest(None, first, second) == second
    assert seo.latest(None) is None
