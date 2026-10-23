"""CelesTrak potential-decays feed retrieval, validation, and local TTL cache."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
from typing import Callable

import requests
from sgp4.api import Satrec

from config.settings import (
    CACHE_DIR,
    CELESTRAK_DECAYING_URL,
    HTTP_TIMEOUT_SECONDS,
    TLE_CACHE_TTL_SECONDS,
)

SOURCE_NAME = "CelesTrak Potential Decays (SPECIAL=DECAYING)"


class DataFeedError(RuntimeError):
    """Raised when a public feed cannot provide valid data."""


@dataclass(frozen=True)
class TLERecord:
    name: str
    line1: str
    line2: str
    catalog_id: int
    epoch: datetime
    satellite: Satrec
    source: str
    retrieved_at: datetime
    retrieval_status: str = "retrieved"


def _parse_epoch(line1: str) -> datetime:
    year_short = int(line1[18:20])
    year = 1900 + year_short if year_short >= 57 else 2000 + year_short
    day_of_year = float(line1[20:32])
    if not 1 <= day_of_year < 367:
        raise ValueError("TLE epoch day is outside the valid year range")
    return datetime(year, 1, 1, tzinfo=timezone.utc) + timedelta(days=day_of_year - 1)


def _valid_checksum(line: str) -> bool:
    if len(line) < 69 or not line[68].isdigit():
        return False
    checksum = sum(int(char) if char.isdigit() else 1 if char == "-" else 0 for char in line[:68]) % 10
    return checksum == int(line[68])


def parse_tle_text(text: str, retrieved_at: datetime | None = None,
                   source: str = SOURCE_NAME,
                   retrieval_status: str = "retrieved") -> list[TLERecord]:
    """Parse and validate CelesTrak 3LE/TLE text, rejecting malformed records."""
    retrieved_at = retrieved_at or datetime.now(timezone.utc)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    records: list[TLERecord] = []
    index = 0
    while index < len(lines):
        if lines[index].startswith("1 "):
            name, line1, line2 = "", lines[index], lines[index + 1] if index + 1 < len(lines) else ""
            index += 2
        else:
            name = lines[index].removeprefix("0 ").strip()
            line1 = lines[index + 1] if index + 1 < len(lines) else ""
            line2 = lines[index + 2] if index + 2 < len(lines) else ""
            index += 3
        if not line1.startswith("1 ") or not line2.startswith("2 "):
            raise DataFeedError("CelesTrak returned an incomplete TLE record.")
        if not _valid_checksum(line1) or not _valid_checksum(line2):
            raise DataFeedError("CelesTrak returned a TLE with an invalid checksum.")
        try:
            catalog_id = int(line1[2:7])
            if int(line2[2:7]) != catalog_id:
                raise ValueError("catalog number mismatch")
            satellite = Satrec.twoline2rv(line1, line2)
            epoch = _parse_epoch(line1)
        except (ValueError, IndexError) as exc:
            raise DataFeedError(f"CelesTrak returned an invalid TLE: {exc}") from exc
        records.append(TLERecord(name or f"NORAD {catalog_id}", line1, line2, catalog_id,
                                 epoch, satellite, source, retrieved_at, retrieval_status))
    if not records:
        raise DataFeedError("CelesTrak returned no TLE records for the potential-decays feed.")
    return records


def fetch_decaying_tles(
    *,
    session=requests,
    cache_path: Path | None = None,
    cache_ttl_seconds: int = TLE_CACHE_TTL_SECONDS,
    force_refresh: bool = False,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> list[TLERecord]:
    """Fetch CelesTrak's potential-decays TLE feed, using a local TTL cache."""
    cache_path = Path(cache_path or CACHE_DIR / "celestrak_decaying.json")
    current_time = now().astimezone(timezone.utc)
    try:
        if cache_path.exists() and not force_refresh:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            retrieved_at = datetime.fromisoformat(cached["retrieved_at"])
            if (current_time - retrieved_at).total_seconds() <= cache_ttl_seconds:
                return parse_tle_text(cached["content"], retrieved_at, retrieval_status="cached")
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        pass

    try:
        response = session.get(
            CELESTRAK_DECAYING_URL,
            params={"SPECIAL": "DECAYING", "FORMAT": "TLE"},
            timeout=HTTP_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        content = response.text
        retrieved_at = now().astimezone(timezone.utc)
        records = parse_tle_text(content, retrieved_at)
    except (requests.RequestException, OSError, DataFeedError) as exc:
        # Only use a stale cache as an explicit offline fallback after a failed request.
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            stale_time = datetime.fromisoformat(cached["retrieved_at"])
            records = parse_tle_text(cached["content"], stale_time, retrieval_status="stale cache")
            return records
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError, DataFeedError):
            raise DataFeedError(f"Unable to retrieve valid CelesTrak potential-decays data: {exc}") from exc

    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"retrieved_at": retrieved_at.isoformat(), "content": content})
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=cache_path.parent, delete=False) as tmp:
            tmp.write(payload)
            temporary_path = Path(tmp.name)
        temporary_path.replace(cache_path)
    except OSError:
        # A valid live response remains usable even if the optional cache cannot be written.
        pass
    return records
