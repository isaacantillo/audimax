"""IP -> "City, Region, Country" from the free DB-IP Lite database (IP geolocation by DB-IP, CC BY 4.0,
https://db-ip.com). Lookups read a local file; the IP never leaves the server.

Download or refresh the database (monthly; the server's cron does this):
    python -m app.services.geoip
"""

import datetime
import gzip
import ipaddress
import logging
import os
import shutil
import urllib.request
from pathlib import Path

import maxminddb

from app.config import settings

log = logging.getLogger("audimax.geoip")

URL = "https://download.db-ip.com/free/dbip-city-lite-{month}.mmdb.gz"

_reader: maxminddb.Reader | None = None
_reader_mtime = 0.0


def _open() -> maxminddb.Reader | None:
    """The reader for the current file, reopened after a refresh replaced it."""
    global _reader, _reader_mtime
    path = Path(settings.geoip_path)
    try:
        mtime = path.stat().st_mtime
    except FileNotFoundError:
        return None
    if _reader is None or mtime != _reader_mtime:
        if _reader is not None:
            _reader.close()
        _reader, _reader_mtime = maxminddb.open_database(str(path)), mtime
    return _reader


def lookup(ip: str | None) -> str | None:
    if not ip:
        return None
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return None
    if address.is_private or address.is_loopback:
        return "Local network"
    try:
        reader = _open()
        record = reader.get(ip) if reader else None
    except Exception:  # a broken database must never break a login
        log.exception("geoip lookup failed")
        return None
    if not isinstance(record, dict):
        return None

    def name(entry: object) -> str | None:
        return entry.get("names", {}).get("en") if isinstance(entry, dict) else None

    region = name((record.get("subdivisions") or [None])[0])
    parts = [name(record.get("city")), region, name(record.get("country"))]
    # Drop repeats like "Vienna, Vienna, Austria".
    return ", ".join(dict.fromkeys(p for p in parts if p)) or None


def download() -> Path:
    """Fetch this month's database (or last month's, early in the month) and swap it in atomically."""
    path = Path(settings.geoip_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    today = datetime.date.today()
    last_month = (today.replace(day=1) - datetime.timedelta(days=1))
    for month in (today, last_month):
        url = URL.format(month=month.strftime("%Y-%m"))
        tmp = path.with_suffix(".download")
        try:
            # download.db-ip.com answers Python's default User-Agent with 403.
            request = urllib.request.Request(url, headers={"User-Agent": "audimax (+https://db-ip.com attribution in the app)"})
            with urllib.request.urlopen(request, timeout=120) as response, gzip.open(response) as unzipped, tmp.open("wb") as out:
                shutil.copyfileobj(unzipped, out)
        except Exception as e:
            log.warning("could not download %s: %s", url, e)
            tmp.unlink(missing_ok=True)
            continue
        maxminddb.open_database(str(tmp)).close()  # refuse to install a broken file
        os.replace(tmp, path)
        return path
    raise RuntimeError("could not download the DB-IP database for this or last month")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(f"wrote {download()}")
