"""IP → country, region and city, and IP → network (AS number and operator), from local
MaxMind-format databases (no outside service sees the visitors' addresses).

By default they are DB-IP's free "IP to City Lite" and "IP to ASN Lite" (CC BY 4.0: the console
credits them), fetched once a month into GEOIP_DIR by `jobs.maintenance_job` or `python -m
app.manage geoip update`. A GeoLite2-City / GeoLite2-ASN (or any file of their shape) put there
by hand works the same; an empty GEOIP_URL / GEOIP_ASN_URL turns that download off. Without a
file every lookup answers None and visits keep their IP, so `jobs.backfill` places them once the
database arrives. The network tells data centres from home and mobile networks (audience/bots).
"""

import fcntl
import gzip
import ipaddress
import json
import logging
import os
import shutil
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import maxminddb

from app.core.config import settings

logger = logging.getLogger(__name__)

LOCK = ".download.lock"  # one download at a time, of either database
# Monthly releases; a file older than this is fetched again (a failed try waits a day).
REFRESH_AFTER = timedelta(days=32)
RETRY_AFTER = timedelta(days=1)
DOWNLOAD_TIMEOUT = 300.0
CHECK_SECONDS = 60  # how often a process looks for a newer file
ATTRIBUTION = "IP geolocation by DB-IP (db-ip.com), CC BY 4.0"


@dataclass(frozen=True)
class Database:
    """One of the two files: `<name>.mmdb` in GEOIP_DIR (`<name>.json` beside it notes where it
    came from and when) and the setting with its download address."""

    name: str  # "city" | "asn"
    url_setting: str

    @property
    def file(self) -> str:
        return f"{self.name}.mmdb"

    @property
    def meta(self) -> str:
        return f"{self.name}.json"

    @property
    def url(self) -> str:
        return str(getattr(settings, self.url_setting))


CITY = Database("city", "GEOIP_URL")
ASN = Database("asn", "GEOIP_ASN_URL")
DATABASES = (CITY, ASN)


@dataclass(frozen=True)
class Place:
    country: str | None  # ISO 3166-1 alpha-2
    region: str | None
    city: str | None
    longitude: float | None = None  # the bot verdict compares the browser's clock with it


@dataclass(frozen=True)
class Network:
    asn: int | None
    org: str | None  # the operator's name, as registered ("Hetzner Online GmbH")


@dataclass
class _Open:
    reader: Any = None
    mtime: float = 0.0
    checked_at: float = 0.0


_lock = threading.Lock()
_open: dict[str, _Open] = {}


def database_path(db: Database = CITY) -> Path:
    return settings.geoip_path / db.file


def _current_reader(db: Database = CITY) -> Any:
    """The open database, reopened when the file changed (a monthly update)."""
    state = _open.setdefault(db.name, _Open())
    now = time.monotonic()
    if state.reader is not None and now - state.checked_at < CHECK_SECONDS:
        return state.reader
    with _lock:
        state.checked_at = now
        path = database_path(db)
        try:
            mtime = path.stat().st_mtime
        except OSError:
            state.reader = None
            return None
        if state.reader is None or mtime != state.mtime:
            try:
                reader = maxminddb.open_database(str(path), maxminddb.MODE_MMAP)
            except (OSError, ValueError, maxminddb.InvalidDatabaseError):
                logger.warning("The GeoIP database at %s cannot be read", path)
                return state.reader
            old, state.reader, state.mtime = state.reader, reader, mtime
            if old is not None:
                old.close()
        return state.reader


def _name(node: Any) -> str | None:
    names = node.get("names") if isinstance(node, dict) else None
    value = names.get("en") if isinstance(names, dict) else None
    return str(value)[:80] if value else None


def place_of(record: Any) -> Place | None:
    """A GeoIP2-City shaped record → its place (pure)."""
    if not isinstance(record, dict):
        return None
    country = record.get("country") or record.get("registered_country") or {}
    code = country.get("iso_code") if isinstance(country, dict) else None
    subdivisions = record.get("subdivisions") or []
    region = _name(subdivisions[0]) if isinstance(subdivisions, list) and subdivisions else None
    city = _name(record.get("city"))
    if not code and not region and not city:
        return None
    location = record.get("location")
    longitude = location.get("longitude") if isinstance(location, dict) else None
    return Place(
        str(code).upper()[:2] if code else None,
        region,
        city,
        float(longitude) if isinstance(longitude, int | float) else None,
    )


def is_public_ip(value: str | None) -> bool:
    try:
        address = ipaddress.ip_address((value or "").strip())
    except ValueError:
        return False
    return address.is_global


def network_of(record: Any) -> Network | None:
    """A GeoIP2-ASN shaped record → its network (pure)."""
    if not isinstance(record, dict):
        return None
    number = record.get("autonomous_system_number")
    org = record.get("autonomous_system_organization")
    asn = number if isinstance(number, int) and number > 0 else None
    name = str(org).strip()[:120] if org else None
    if asn is None and not name:
        return None
    return Network(asn, name or None)


def _record(db: Database, ip: str | None) -> Any:
    if not ip or not is_public_ip(ip):
        return None
    reader = _current_reader(db)
    if reader is None:
        return None
    try:
        return reader.get(ip.strip())
    except (ValueError, maxminddb.InvalidDatabaseError):
        return None


def lookup(ip: str | None) -> Place | None:
    """The place of a public IP, None for a private one, without a database or unknown."""
    return place_of(_record(CITY, ip))


def network(ip: str | None) -> Network | None:
    """The network of a public IP, None for a private one, without a database or unknown."""
    return network_of(_record(ASN, ip))


def info() -> dict[str, Any]:
    """For the console: whether places are known, and the city database's date and source."""
    meta_file = settings.geoip_path / CITY.meta
    try:
        meta = json.loads(meta_file.read_text())
    except (OSError, ValueError):
        meta = {}
    path = database_path(CITY)
    available = path.exists()
    updated = meta.get("updated_at")
    if available and not updated:
        updated = datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat()
    return {
        "available": available,
        "updated_at": updated,
        "release": meta.get("release"),
        "attribution": ATTRIBUTION if "db-ip.com" in str(meta.get("url", CITY.url)) else None,
    }


def _months(today: date) -> list[str]:
    """This month's release and the one before (the new one appears on the 1st)."""
    first = today.replace(day=1)
    previous = (first - timedelta(days=1)).replace(day=1)
    return [first.strftime("%Y-%m"), previous.strftime("%Y-%m")]


def update_due(now: datetime | None = None, db: Database = CITY) -> bool:
    if not db.url:
        return False
    moment = now or datetime.now(UTC)
    meta_file = settings.geoip_path / db.meta
    try:
        meta = json.loads(meta_file.read_text())
    except (OSError, ValueError):
        meta = {}
    tried = meta.get("tried_at")
    if tried and moment - datetime.fromisoformat(tried) < RETRY_AFTER:
        return False
    path = database_path(db)
    if not path.exists():
        return True
    return moment - datetime.fromtimestamp(path.stat().st_mtime, UTC) > REFRESH_AFTER


def _write_meta(db: Database, **fields: Any) -> None:
    meta_file = settings.geoip_path / db.meta
    try:
        meta = json.loads(meta_file.read_text())
    except (OSError, ValueError):
        meta = {}
    meta.update(fields)
    meta_file.write_text(json.dumps(meta))


def update(transport: httpx.BaseTransport | None = None, db: Database = CITY) -> bool:
    """Fetch the newest release into GEOIP_DIR (checked before it replaces the old file). One
    download at a time across the processes sharing the folder (a file lock); a second caller
    returns False at once."""
    if not db.url:
        return False
    folder = settings.geoip_path
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / LOCK).open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            logger.info("A GeoIP download is already running")
            return False
        return _download(db, folder, transport)


def _download(db: Database, folder: Path, transport: httpx.BaseTransport | None) -> bool:
    now = datetime.now(UTC)
    _write_meta(db, tried_at=now.isoformat())
    tag = f"{os.getpid()}-{uuid.uuid4().hex[:8]}"
    gz_file, tmp_file = folder / f"{db.file}.{tag}.gz.part", folder / f"{db.file}.{tag}.part"
    headers = {"User-Agent": f"Debatr/1.0 (+{settings.SITE_URL})"}
    with httpx.Client(timeout=DOWNLOAD_TIMEOUT, transport=transport, headers=headers) as client:
        for release in _months(now.date()):
            url = db.url.format(month=release)
            try:
                with client.stream("GET", url, follow_redirects=True) as response:
                    if response.status_code != 200:
                        logger.info("GeoIP release %s: HTTP %s", release, response.status_code)
                        continue
                    with gz_file.open("wb") as out:
                        for chunk in response.iter_bytes(1 << 20):
                            out.write(chunk)
                if url.endswith(".gz"):
                    with gzip.open(gz_file, "rb") as src, tmp_file.open("wb") as dst:
                        shutil.copyfileobj(src, dst, 1 << 20)
                else:
                    gz_file.replace(tmp_file)
                with maxminddb.open_database(str(tmp_file)) as check:
                    check.get("8.8.8.8")
            except (httpx.HTTPError, OSError, EOFError, ValueError, maxminddb.InvalidDatabaseError):
                logger.warning("GeoIP release %s could not be fetched", release, exc_info=True)
                tmp_file.unlink(missing_ok=True)
                continue
            finally:
                gz_file.unlink(missing_ok=True)
            os.replace(tmp_file, database_path(db))
            _write_meta(db, url=url, release=release, updated_at=datetime.now(UTC).isoformat())
            logger.info("GeoIP %s database updated to the %s release", db.name, release)
            return True
    tmp_file.unlink(missing_ok=True)
    return False
