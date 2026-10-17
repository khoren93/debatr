import json
import os
import stat
import sys

import pytest

from debatr.config import DEFAULT_URL, Login, Store, config_path, normalize_url, resolve


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("ai-debates.net", "https://ai-debates.net"),
        ("https://AI-Debates.net/", "https://ai-debates.net"),
        ("https://ai-debates.net/api/", "https://ai-debates.net"),
        ("localhost", "http://localhost"),
        ("localhost:5173/api", "http://localhost:5173"),
        ("127.0.0.1:8000", "http://127.0.0.1:8000"),
        ("http://example.com/debatr", "http://example.com/debatr"),
    ],
)
def test_normalize_url(raw: str, expected: str):
    assert normalize_url(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "ftp://example.com", "https://"])
def test_normalize_url_rejects(raw: str):
    with pytest.raises(ValueError):
        normalize_url(raw)


def test_store_roundtrip_is_private():
    store = Store()
    store.default_url = "https://ai-debates.net"
    store.logins["https://ai-debates.net"] = Login(
        token="debatr_x", email="a@b.co", token_name="cli"
    )
    path = store.save()
    assert path == config_path()
    loaded = Store.load()
    assert loaded.default_url == "https://ai-debates.net"
    assert loaded.logins["https://ai-debates.net"] == Login("debatr_x", "a@b.co", "cli")
    if sys.platform != "win32":
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
        assert stat.S_IMODE(os.stat(path.parent).st_mode) == 0o700


def test_broken_config_is_ignored():
    config_path().parent.mkdir(parents=True)
    config_path().write_text("{nope")
    assert Store.load().logins == {}
    config_path().write_text(json.dumps(["not", "an", "object"]))
    assert Store.load().logins == {}


def test_resolve_precedence(monkeypatch):
    store = Store()
    assert resolve(store=store).url == DEFAULT_URL
    store.default_url = "https://mine.example"
    store.logins["https://mine.example"] = Login(token="debatr_saved")
    s = resolve(store=store)
    assert (s.url, s.token, s.token_source) == ("https://mine.example", "debatr_saved", "login")

    monkeypatch.setenv("DEBATR_URL", "other.example")
    s = resolve(store=store)
    assert (s.url, s.token) == ("https://other.example", None)  # no login for that server

    s = resolve("mine.example", store=store)  # --url wins over DEBATR_URL
    assert s.token == "debatr_saved"

    monkeypatch.setenv("DEBATR_TOKEN", " debatr_env ")
    s = resolve("mine.example", store=store)
    assert (s.token, s.token_source) == ("debatr_env", "env")
