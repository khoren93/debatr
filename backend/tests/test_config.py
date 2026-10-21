"""Settings parsed from the environment (app/core/config)."""

import pytest

from app.core.config import Settings, bare_host


@pytest.mark.parametrize(
    ("raw", "host"),
    [
        ("admin.example.com", "admin.example.com"),
        ("https://Admin.Example.com:8443/path", "admin.example.com"),
        ("  ", ""),
        ("[::1]", "[::1]"),
    ],
)
def test_bare_host(raw: str, host: str) -> None:
    assert bare_host(raw) == host


def test_site_aliases_are_bare_hosts() -> None:
    config = Settings(
        SITE_ALIASES="ai-debates.example, https://www.AI-Debates.example/, ,old.example:80"
    )
    assert config.site_aliases == ("ai-debates.example", "old.example")
    assert Settings(SITE_ALIASES="").site_aliases == ()
