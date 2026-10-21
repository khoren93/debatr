"""Where the CLI talks to and with which token.

The server URL comes from `--url`, then `DEBATR_URL`, then the last server you signed in to,
then https://debatr.tv (the site moved there from ai-debates.net: old addresses and logins
saved for them follow it). The token comes from `DEBATR_TOKEN`, then the one saved by
`debatr login` for that server. Saved logins live in `config.json` (mode 0600) in
`$DEBATR_CONFIG_DIR`, `%APPDATA%\\debatr` on Windows or `$XDG_CONFIG_HOME/debatr`
(`~/.config/debatr`) elsewhere.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

DEFAULT_URL = "https://debatr.tv"
# Former hosts of the default server (they redirect there): a URL or a saved login naming one
# means the new host.
MOVED_HOSTS = {"ai-debates.net": "debatr.tv", "www.ai-debates.net": "debatr.tv"}
ENV_URL = "DEBATR_URL"
ENV_TOKEN = "DEBATR_TOKEN"
ENV_CONFIG_DIR = "DEBATR_CONFIG_DIR"
_LOCAL_HOSTS = ("localhost", "127.0.0.1", "0.0.0.0", "[::1]", "::1")


def config_dir() -> Path:
    override = os.environ.get(ENV_CONFIG_DIR)
    if override:
        return Path(override).expanduser()
    if sys.platform == "win32" and os.environ.get("APPDATA"):
        return Path(os.environ["APPDATA"]) / "debatr"
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base).expanduser() / "debatr"


def config_path() -> Path:
    return config_dir() / "config.json"


def normalize_url(raw: str) -> str:
    """ "debatr.tv" -> "https://debatr.tv", "localhost:5173/api/" -> "http://localhost:5173",
    "ai-debates.net" (a former host) -> "https://debatr.tv". Raises ValueError for anything that
    is not an http(s) site."""
    value = raw.strip()
    if not value:
        raise ValueError("Empty server URL")
    if "://" not in value:
        host = value.split("/", 1)[0].split(":", 1)[0].lower()
        local = host in _LOCAL_HOSTS or value.startswith("[::1]")
        value = f"{'http' if local else 'https'}://{value}"
    parts = urlsplit(value)
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        raise ValueError(f"Not an http(s) URL: {raw}")
    path = parts.path.rstrip("/")
    if path.endswith("/api"):
        path = path[: -len("/api")]
    scheme, netloc = parts.scheme.lower(), parts.netloc.lower()
    if netloc in MOVED_HOSTS:
        scheme, netloc = "https", MOVED_HOSTS[netloc]
    return urlunsplit((scheme, netloc, path, "", ""))


def _current(url: str) -> str:
    """A saved server URL with a former host replaced (saved by an older version)."""
    try:
        return normalize_url(url)
    except ValueError:
        return url


@dataclass
class Login:
    token: str
    email: str | None = None
    token_name: str | None = None


class Store:
    """The saved logins, one per server."""

    def __init__(self, data: dict[str, Any] | None = None) -> None:
        data = data or {}
        default_url = data.get("default_url")
        self.default_url: str | None = _current(default_url) if default_url else None
        self.logins: dict[str, Login] = {}
        hosts = data.get("hosts") or {}
        # A login saved for the current address wins over one saved for its former host.
        for url, entry in sorted(hosts.items(), key=lambda item: _current(item[0]) == item[0]):
            if isinstance(entry, dict) and entry.get("token"):
                self.logins[_current(url)] = Login(
                    token=str(entry["token"]),
                    email=entry.get("email"),
                    token_name=entry.get("token_name"),
                )

    @classmethod
    def load(cls) -> Store:
        try:
            data = json.loads(config_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        return cls(data if isinstance(data, dict) else None)

    def dump(self) -> dict[str, Any]:
        return {
            "default_url": self.default_url,
            "hosts": {
                url: {"token": login.token, "email": login.email, "token_name": login.token_name}
                for url, login in self.logins.items()
            },
        }

    def save(self) -> Path:
        path = config_path()
        _write_private(path, json.dumps(self.dump(), indent=2) + "\n")
        return path


def _write_private(path: Path, text: str) -> None:
    """Write a file only the current user can read (it holds API tokens), atomically."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_name(f".{path.name}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    with contextlib.suppress(OSError):  # no-op on Windows
        os.chmod(tmp, 0o600)
    os.replace(tmp, path)


@dataclass
class Settings:
    url: str
    token: str | None
    # "env" (DEBATR_TOKEN), "login" (debatr login) or None (anonymous)
    token_source: str | None


def resolve(url_option: str | None = None, store: Store | None = None) -> Settings:
    store = store or Store.load()
    raw_url = url_option or os.environ.get(ENV_URL) or store.default_url or DEFAULT_URL
    url = normalize_url(raw_url)
    env_token = (os.environ.get(ENV_TOKEN) or "").strip()
    if env_token:
        return Settings(url=url, token=env_token, token_source="env")
    login = store.logins.get(url)
    if login is not None:
        return Settings(url=url, token=login.token, token_source="login")
    return Settings(url=url, token=None, token_source=None)
