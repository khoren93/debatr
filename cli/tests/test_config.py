import json
import os
import stat
import sys

import pytest

from debatr.config import DEFAULT_URL, Login, Store, config_path, normalize_url, resolve


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("debatr.tv", "https://debatr.tv"),
        ("https://Debatr.tv/", "https://debatr.tv"),
        ("https://debatr.tv/api/", "https://debatr.tv"),
        # The former host of the default server means the new one.
        ("ai-debates.net", "https://debatr.tv"),
        ("http://www.ai-debates.net/api", "https://debatr.tv"),
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
    store.default_url = "https://debatr.tv"
    store.logins["https://debatr.tv"] = Login(token="debatr_x", email="a@b.co", token_name="cli")
    path = store.save()
    assert path == config_path()
    loaded = Store.load()
    assert loaded.default_url == "https://debatr.tv"
    assert loaded.logins["https://debatr.tv"] == Login("debatr_x", "a@b.co", "cli")
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


def test_logins_saved_for_the_former_host_follow_the_move():
    old = {"token": "debatr_old", "email": "a@b.co"}
    store = Store(
        {"default_url": "https://ai-debates.net", "hosts": {"https://ai-debates.net": old}}
    )
    assert store.default_url == DEFAULT_URL
    assert store.logins == {DEFAULT_URL: Login("debatr_old", "a@b.co")}
    assert resolve(store=store).token == "debatr_old"
    # A login made on the new host already wins over the old one.
    new = {"token": "debatr_new"}
    hosts = {DEFAULT_URL: new, "https://ai-debates.net": old}
    assert Store({"hosts": hosts}).logins[DEFAULT_URL].token == "debatr_new"
    hosts = {"https://ai-debates.net": old, DEFAULT_URL: new}
    assert Store({"hosts": hosts}).logins[DEFAULT_URL].token == "debatr_new"
