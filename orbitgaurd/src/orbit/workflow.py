"""Pure helpers for deterministic, selection-specific propagation runs."""

from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import math


def latest_record_per_object(records: list) -> list:
    latest = {}
    for record in records:
        if record.catalog_id not in latest or record.epoch > latest[record.catalog_id].epoch:
            latest[record.catalog_id] = record
    return sorted(latest.values(), key=lambda record: (record.name.casefold(), record.catalog_id))


def build_run_identity(record, source_mode: str, start: datetime, duration_minutes: int,
                       step_seconds: int) -> dict:
    """Fingerprint every input that can identify an SGP4 output set."""
    if start.tzinfo is None:
        raise ValueError("Analysis start must have a timezone.")
    start_utc = start.astimezone(timezone.utc)
    tle_payload = f"{record.line1.strip()}\n{record.line2.strip()}".encode("utf-8")
    tle_fingerprint = hashlib.sha256(tle_payload).hexdigest()
    configuration = {
        "source_mode": source_mode,
        "data_source": record.source,
        "retrieval_status": record.retrieval_status,
        "retrieved_at_utc": record.retrieved_at.astimezone(timezone.utc).isoformat(),
        "object_name": record.name,
        "norad_id": record.catalog_id,
        "tle_epoch_utc": record.epoch.astimezone(timezone.utc).isoformat(),
        "tle_sha256": tle_fingerprint,
        "start_utc": start_utc.isoformat(),
        "duration_minutes": int(duration_minutes),
        "step_seconds": int(step_seconds),
    }
    canonical = json.dumps(configuration, sort_keys=True, separators=(",", ":"))
    run_id = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return {"run_id": run_id, "configuration": configuration,
            "tle_sha256": tle_fingerprint}


def validate_run_configuration(record, start: datetime, duration_minutes: int,
                               step_seconds: int, maximum_epoch_offset_days: int = 7,
                               maximum_duration_minutes: int = 360) -> None:
    if start.tzinfo is None:
        raise ValueError("Analysis start must have a timezone; the dashboard interprets entered wall time as UTC.")
    if duration_minutes < 1 or duration_minutes > maximum_duration_minutes:
        raise ValueError(f"Duration must be between 1 and {maximum_duration_minutes} minutes.")
    if step_seconds < 1 or step_seconds > 600:
        raise ValueError("Time step must be between 1 and 600 seconds.")
    if abs((start.astimezone(timezone.utc) - record.epoch).total_seconds()) > maximum_epoch_offset_days * 86400:
        raise ValueError(
            f"Analysis start must be within {maximum_epoch_offset_days} days of this TLE epoch; "
            "TLE extrapolation is limited to seven days from its epoch."
        )
    end = start.astimezone(timezone.utc) + timedelta(minutes=duration_minutes)
    if abs((end - record.epoch).total_seconds()) > maximum_epoch_offset_days * 86400:
        raise ValueError(
            f"Analysis end must also be within {maximum_epoch_offset_days} days of this TLE epoch."
        )


def requested_point_count(duration_minutes: int, step_seconds: int) -> int:
    duration_seconds = duration_minutes * 60
    return math.ceil(duration_seconds / step_seconds) + 1


def track_csv(points: list[dict], provenance: dict | None = None) -> str:
    output = io.StringIO(newline="")
    fields = ["time_utc", "latitude_deg", "longitude_deg", "altitude_km", "propagation_status",
              "sgp4_gap_before"]
    provenance = provenance or {}
    fields.extend(provenance)
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for point in points:
        row = {
            "time_utc": point["time"].astimezone(timezone.utc).isoformat(),
            "latitude_deg": point["latitude"],
            "longitude_deg": point["longitude"],
            "altitude_km": point["altitude_km"],
            "propagation_status": "valid",
            "sgp4_gap_before": bool(point.get("break_before", False)),
        }
        row.update(provenance)
        writer.writerow(row)
    return output.getvalue()
