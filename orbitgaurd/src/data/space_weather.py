"""NOAA SWPC planetary K-index feed with schema validation and TTL caching."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile

import requests

from config.settings import (CACHE_DIR, HTTP_TIMEOUT_SECONDS, NOAA_KP_URL, NOAA_SOLAR_FLUX_URL,
                             SOLAR_FLUX_CACHE_TTL_SECONDS, WEATHER_CACHE_TTL_SECONDS)
from src.data.tle_loader import DataFeedError

SOURCE_NAME = "NOAA Space Weather Prediction Center planetary K-index"
SOLAR_SOURCE_NAME = "NOAA Space Weather Prediction Center 10.7 cm solar radio flux"


def parse_kp_response(payload, retrieved_at: datetime | None = None,
                      source: str = SOURCE_NAME,
                      retrieval_status: str = "retrieved") -> list[dict]:
    """Validate NOAA's observed JSON schema (list of time_tag/Kp/a_running/station_count rows)."""
    if not isinstance(payload, list):
        raise DataFeedError("NOAA K-index response must be a JSON list.")
    retrieved_at = retrieved_at or datetime.now(timezone.utc)
    result = []
    for row in payload:
        if not isinstance(row, dict) or not {"time_tag", "Kp", "a_running", "station_count"}.issubset(row):
            raise DataFeedError("NOAA K-index response row does not match the inspected schema.")
        try:
            observed_at = datetime.fromisoformat(str(row["time_tag"]).replace("Z", "+00:00"))
            if observed_at.tzinfo is None:
                observed_at = observed_at.replace(tzinfo=timezone.utc)
            kp = float(row["Kp"])
            a_running = int(row["a_running"])
            station_count = int(row["station_count"])
            if not 0 <= kp <= 9 or a_running < 0 or station_count < 0:
                raise ValueError("value outside valid range")
        except (TypeError, ValueError) as exc:
            raise DataFeedError(f"NOAA K-index response contains an invalid observation: {exc}") from exc
        result.append({"time": observed_at.astimezone(timezone.utc), "kp": kp,
                       "a_running": a_running, "station_count": station_count,
                       "source": source, "retrieved_at": retrieved_at,
                       "retrieval_status": retrieval_status})
    if not result:
        raise DataFeedError("NOAA returned no K-index observations.")
    return result


def fetch_space_weather(*, session=requests, cache_path: Path | None = None,
                        cache_ttl_seconds: int = WEATHER_CACHE_TTL_SECONDS,
                        force_refresh: bool = False,
                        now=lambda: datetime.now(timezone.utc)) -> list[dict]:
    """Fetch current NOAA planetary K-index observations; return cached observations offline."""
    cache_path = Path(cache_path or CACHE_DIR / "noaa_kp.json")
    current_time = now().astimezone(timezone.utc)
    try:
        if cache_path.exists() and not force_refresh:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            retrieved_at = datetime.fromisoformat(cached["retrieved_at"])
            if (current_time - retrieved_at).total_seconds() <= cache_ttl_seconds:
                return parse_kp_response(cached["payload"], retrieved_at, retrieval_status="cached")
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        pass
    try:
        response = session.get(NOAA_KP_URL, timeout=HTTP_TIMEOUT_SECONDS)
        response.raise_for_status()
        payload = response.json()
        retrieved_at = now().astimezone(timezone.utc)
        observations = parse_kp_response(payload, retrieved_at)
    except (requests.RequestException, OSError, ValueError, DataFeedError) as exc:
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            return parse_kp_response(cached["payload"], datetime.fromisoformat(cached["retrieved_at"]),
                                     retrieval_status="stale cache")
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError, DataFeedError):
            raise DataFeedError(f"Unable to retrieve valid NOAA space-weather data: {exc}") from exc
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=cache_path.parent, delete=False) as tmp:
            json.dump({"retrieved_at": retrieved_at.isoformat(), "payload": payload}, tmp)
            temporary_path = Path(tmp.name)
        temporary_path.replace(cache_path)
    except OSError:
        pass
    return observations


def parse_solar_flux_response(payload, retrieved_at: datetime | None = None,
                              source: str = SOLAR_SOURCE_NAME,
                              retrieval_status: str = "retrieved") -> list[dict]:
    """Validate NOAA's 10.7 cm flux list schema (time_tag and flux; units are SFU)."""
    if not isinstance(payload, list):
        raise DataFeedError("NOAA solar-flux response must be a JSON list.")
    retrieved_at = retrieved_at or datetime.now(timezone.utc)
    rows = []
    for row in payload:
        if not isinstance(row, dict) or not {"time_tag", "flux"}.issubset(row):
            raise DataFeedError("NOAA solar-flux response row does not match the inspected schema.")
        try:
            observed_at = datetime.fromisoformat(str(row["time_tag"]).replace("Z", "+00:00"))
            if observed_at.tzinfo is None:
                observed_at = observed_at.replace(tzinfo=timezone.utc)
            flux = float(row["flux"])
            if flux <= 0:
                raise ValueError("flux must be positive")
        except (TypeError, ValueError) as exc:
            raise DataFeedError(f"NOAA solar-flux response contains an invalid observation: {exc}") from exc
        rows.append({"time": observed_at.astimezone(timezone.utc), "flux_sfu": flux,
                     "source": source, "retrieved_at": retrieved_at,
                     "retrieval_status": retrieval_status})
    if not rows:
        raise DataFeedError("NOAA returned no solar-flux observations.")
    return rows


def fetch_solar_flux(*, session=requests, cache_path: Path | None = None,
                     cache_ttl_seconds: int = SOLAR_FLUX_CACHE_TTL_SECONDS,
                     force_refresh: bool = False,
                     now=lambda: datetime.now(timezone.utc)) -> list[dict]:
    """Fetch NOAA 10.7 cm solar radio-flux observations with TTL cache and stale fallback."""
    cache_path = Path(cache_path or CACHE_DIR / "noaa_solar_flux.json")
    current_time = now().astimezone(timezone.utc)
    try:
        if cache_path.exists() and not force_refresh:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            retrieved_at = datetime.fromisoformat(cached["retrieved_at"])
            if (current_time - retrieved_at).total_seconds() <= cache_ttl_seconds:
                return parse_solar_flux_response(cached["payload"], retrieved_at,
                                                 retrieval_status="cached")
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        pass
    try:
        response = session.get(NOAA_SOLAR_FLUX_URL, timeout=HTTP_TIMEOUT_SECONDS)
        response.raise_for_status()
        payload = response.json()
        retrieved_at = now().astimezone(timezone.utc)
        rows = parse_solar_flux_response(payload, retrieved_at)
    except (requests.RequestException, OSError, ValueError, DataFeedError) as exc:
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            return parse_solar_flux_response(cached["payload"], datetime.fromisoformat(cached["retrieved_at"]),
                                             retrieval_status="stale cache")
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError, DataFeedError):
            raise DataFeedError(f"Unable to retrieve valid NOAA solar-flux data: {exc}") from exc
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=cache_path.parent, delete=False) as tmp:
            json.dump({"retrieved_at": retrieved_at.isoformat(), "payload": payload}, tmp)
            temporary_path = Path(tmp.name)
        temporary_path.replace(cache_path)
    except OSError:
        pass
    return rows
