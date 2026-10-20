"""Embedding on other sites: links, sizes and the oEmbed answer (services/embed)."""

from html.parser import HTMLParser

import pytest

from app.services import embed
from app.services.embed import EmbedTarget

SITE = "https://debatr.example"


def test_parse_url_names_debates_topics_and_players() -> None:
    assert embed.parse_url(f"{SITE}/d/abc123/tabs-or-spaces", SITE) == EmbedTarget(
        "debate", "abc123"
    )
    assert embed.parse_url(f"{SITE}/d/abc123", SITE) == EmbedTarget("debate", "abc123")
    assert embed.parse_url(f"{SITE}/t/t0p1c/cats-or-dogs", SITE) == EmbedTarget("topic", "t0p1c")
    # The player's own address keeps the Short and the start.
    assert embed.parse_url(f"{SITE}/embed/abc123?format=short&t=83", SITE) == EmbedTarget(
        "debate", "abc123", "short", 83
    )
    assert embed.parse_url(f"{SITE}/d/abc123/old-words?t=12s&ref=x", SITE) == EmbedTarget(
        "debate", "abc123", "long", 12
    )
    # Unicode topic words, percent-encoded or not.
    assert embed.parse_url(f"{SITE}/d/abc123/%D0%BB%D1%83%D1%87%D1%88%D0%B5", SITE) == (
        EmbedTarget("debate", "abc123")
    )
    assert embed.parse_url(f"{SITE}/d/abc123/лучше-ли", SITE) == EmbedTarget("debate", "abc123")


def test_parse_url_host_ignores_port_and_www() -> None:
    assert embed.parse_url("http://www.debatr.example:5173/d/abc123", SITE) is not None
    assert (
        embed.parse_url("https://DEBATR.example/d/abc123", "https://www.debatr.example/")
        is not None
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/d/abc123",
        "https://debatr.example.evil.example/d/abc123",
        "https://evil.example@debatr.example.attacker/d/abc123",
        "ftp://debatr.example/d/abc123",
        "debatr.example/d/abc123",
        f"{SITE}/",
        f"{SITE}/gallery",
        f"{SITE}/d",
        f"{SITE}/d/abc123/words/more",
        f"{SITE}/embed/abc123/words",
        f"{SITE}/debate/0b6f6a52-6f5e-4c55-9a43-1d1f3b1c0c11",
        f"{SITE}/d/bad slug!",
        f"{SITE}/d/../admin",
        "http://[::1",
        "",
    ],
)
def test_parse_url_refuses_other_pages_and_hosts(url: str) -> None:
    assert embed.parse_url(url, SITE) is None


def test_parse_start() -> None:
    assert embed.parse_start("83") == 83
    assert embed.parse_start("83s") == 83
    assert embed.parse_start("1m23s") == 0
    assert embed.parse_start("-5") == 0
    assert embed.parse_start("") == 0
    assert embed.parse_start(str(embed.MAX_START + 1)) == 0


def test_fit_keeps_the_proportions_within_the_limits() -> None:
    assert embed.fit("long") == (640, 360)
    assert embed.fit("short") == (360, 640)
    # As wide as allowed, up to the largest player.
    assert embed.fit("long", maxwidth=600) == (600, 337)
    assert embed.fit("long", maxwidth=4000) == (1280, 720)
    assert embed.fit("short", maxwidth=1200) == (405, 720)
    # The height limit wins when it is the tighter one.
    assert embed.fit("long", maxwidth=1000, maxheight=300) == (533, 299)
    assert embed.fit("short", maxheight=400) == (225, 400)
    for fmt in ("long", "short"):
        for maxwidth in (1, 7, 199, 333, 640, 999):
            for maxheight in (None, 1, 50, 333, 777):
                width, height = embed.fit(fmt, maxwidth, maxheight)
                assert 1 <= width <= maxwidth
                assert maxheight is None or height <= max(1, maxheight)


def test_embed_path() -> None:
    assert embed.embed_path("abc123") == "/embed/abc123"
    assert embed.embed_path("abc123", "short") == "/embed/abc123?format=short"
    assert embed.embed_path("abc123", "long", 83) == "/embed/abc123?t=83"
    assert embed.embed_path("abc123", "short", 5) == "/embed/abc123?format=short&t=5"


class _Tags(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[tuple[str, dict[str, str | None]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append((tag, dict(attrs)))


def test_iframe_html_escapes_the_title() -> None:
    html = embed.iframe_html(
        f"{SITE}/embed/abc?format=short&t=3", 'Is "AI" <b>safe</b>? — A vs B', 360, 640
    )
    parser = _Tags()
    parser.feed(html)
    assert [tag for tag, _ in parser.tags] == ["iframe"]
    attrs = parser.tags[0][1]
    assert attrs["src"] == f"{SITE}/embed/abc?format=short&t=3"
    assert attrs["title"] == 'Is "AI" <b>safe</b>? — A vs B'
    assert attrs["width"] == "360" and attrs["height"] == "640"
    assert attrs["allow"] == embed.ALLOW
    assert "allowfullscreen" in attrs and attrs["loading"] == "lazy"
    assert "<b>" not in html


def test_embed_title() -> None:
    assert (
        embed.embed_title("  Tabs or\nspaces? ", ["Claude", "GPT-5.5"])
        == "Tabs or spaces? — Claude vs GPT-5.5"
    )
    assert embed.embed_title("Tabs?", []) == "Tabs?"
    assert embed.embed_title("", ["", ""]) == "AI debate"


def test_oembed_payload() -> None:
    payload = embed.oembed_payload(
        site_url=f"{SITE}/",
        slug="abc123",
        title="Лучше ли офис? — Claude vs Gemini",
        author="Khoren",
        playable=True,
        fmt="short",
        start=7,
        maxwidth=300,
    )
    assert payload["version"] == "1.0"
    assert payload["type"] == "video"
    assert payload["provider_name"] == "Debatr"
    assert payload["provider_url"] == f"{SITE}/"
    assert payload["author_name"] == "Khoren"
    assert (payload["width"], payload["height"]) == (300, 533)
    assert payload["thumbnail_url"] == f"{SITE}/og/d/abc123.png"
    assert (payload["thumbnail_width"], payload["thumbnail_height"]) == embed.THUMBNAIL_SIZE
    assert payload["cache_age"] == embed.CACHE_AGE
    assert f'src="{SITE}/embed/abc123?format=short&amp;t=7"' in payload["html"]
    assert 'width="300" height="533"' in payload["html"]


def test_oembed_payload_without_video_is_rich_and_anonymous() -> None:
    payload = embed.oembed_payload(
        site_url=SITE, slug="abc123", title="T", author=None, playable=False
    )
    assert payload["type"] == "rich"
    assert "author_name" not in payload
    assert (payload["width"], payload["height"]) == (640, 360)
    assert f'src="{SITE}/embed/abc123"' in payload["html"]
