"""Load the transparently sourced offline sample package and user uploads."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import io
import json
from pathlib import Path

from config.settings import PROJECT_ROOT
from src.data.space_weather import parse_kp_response, parse_solar_flux_response
from src.data.tle_loader import TLERecord, parse_tle_text

SAMPLE_DIR = PROJECT_ROOT / "data" / "sample"


@dataclass
class DataBundle:
    records: list[TLERecord]
    kp: list[dict]
    solar_flux: list[dict]
    mode: str
    source: str
    retrieved_at: datetime
    notices: list[str]


def _manifest_datetime(manifest: dict) -> datetime:
    raw = manifest["retrieval_time_utc"].replace("Z", "+00:00")
    # .NET "o" timestamps may contain seven fractional digits; Python datetime
    # preserves microseconds, so safely truncate the unrepresentable 100 ns digit.
    if "." in raw:
        head, tail = raw.split(".", 1)
        zone_at = max(tail.find("+"), tail.find("-"))
        fraction, zone = (tail[:zone_at], tail[zone_at:]) if zone_at >= 0 else (tail, "")
        raw = f"{head}.{fraction[:6]}{zone}"
    value = datetime.fromisoformat(raw)
    if value.tzinfo is None:
        raise ValueError("Sample manifest retrieval_time_utc must include a timezone.")
    return value.astimezone(timezone.utc)


def load_sample_bundle(sample_dir: Path = SAMPLE_DIR) -> DataBundle:
    """Load authentic downloaded sample files and verify their schema and provenance."""
    manifest = json.loads((sample_dir / "manifest.json").read_text(encoding="utf-8-sig"))
    retrieved_at = _manifest_datetime(manifest)
    files = manifest["files"]
    tle_file = sample_dir / "potential_decays.3le"
    kp_file = sample_dir / "noaa_planetary_k_index.json"
    flux_file = sample_dir / "noaa_solar_flux_30_day.json"
    tle_source = files["potential_decays.3le"]["url"]
    kp_source = files["noaa_planetary_k_index.json"]["url"]
    flux_source = files["noaa_solar_flux_30_day.json"]["url"]
    records = parse_tle_text(tle_file.read_text(encoding="utf-8-sig"), retrieved_at,
                             tle_source, "bundled")
    kp_payload = json.loads(kp_file.read_text(encoding="utf-8-sig"))
    flux_payload = json.loads(flux_file.read_text(encoding="utf-8-sig"))
    kp = parse_kp_response(kp_payload, retrieved_at, kp_source, "bundled")
    flux = parse_solar_flux_response(flux_payload, retrieved_at, flux_source, "bundled")
    return DataBundle(records, kp, flux, "bundled", "Bundled authentic public feed snapshot",
                      retrieved_at, ["Bundled feed snapshot; age is shown from its recorded retrieval time."])


def parse_uploaded_tle(content: str | bytes, filename: str) -> list[TLERecord]:
    """Parse a user-provided 2LE/3LE file without changing its orbital values."""
    if isinstance(content, bytes):
        content = content.decode("utf-8-sig")
    return parse_tle_text(content, datetime.now(timezone.utc), f"User upload: {filename}", "uploaded")


def parse_uploaded_kp_csv(content: str | bytes, filename: str) -> list[dict]:
    """Read CSV rows with the NOAA Kp fields and preserve uploaded-source attribution."""
    if isinstance(content, bytes):
        content = content.decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(content)))
    if not rows:
        raise ValueError("Kp CSV has no observation rows.")
    payload = [{key: row.get(key) for key in ("time_tag", "Kp", "a_running", "station_count")}
               for row in rows]
    return parse_kp_response(payload, datetime.now(timezone.utc), f"User upload: {filename}", "uploaded")


def parse_uploaded_solar_csv(content: str | bytes, filename: str) -> list[dict]:
    """Read CSV rows with NOAA's time_tag/flux fields and preserve attribution."""
    if isinstance(content, bytes):
        content = content.decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(content)))
    if not rows:
        raise ValueError("Solar-flux CSV has no observation rows.")
    payload = [{key: row.get(key) for key in ("time_tag", "flux")} for row in rows]
    return parse_solar_flux_response(payload, datetime.now(timezone.utc), f"User upload: {filename}", "uploaded")
