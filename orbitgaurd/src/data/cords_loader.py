"""Validated import for user-supplied historical reentry event CSVs.

This module validates a documented normalized schema; it does not download,
endorse, or transform an external CORDS export automatically.
"""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import io

REQUIRED_COLUMNS = {"object_name", "norad_id", "observed_reentry_utc", "source"}


def _parse_utc(value: str) -> datetime:
    timestamp = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    if timestamp.tzinfo is None:
        raise ValueError("timestamp must include a UTC offset")
    return timestamp.astimezone(timezone.utc)


def validate_reentry_csv(content: str | bytes) -> tuple[list[dict], list[str]]:
    """Validate normalized event records and return rows plus non-fatal quality notes."""
    if isinstance(content, bytes):
        content = content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(content))
    columns = set(reader.fieldnames or [])
    missing = sorted(REQUIRED_COLUMNS - columns)
    if missing:
        raise ValueError(f"Historical event CSV is missing required columns: {', '.join(missing)}")

    events = []
    errors = []
    seen = set()
    for line_number, row in enumerate(reader, start=2):
        name = (row.get("object_name") or "").strip()
        norad_id = (row.get("norad_id") or "").strip()
        timestamp = (row.get("observed_reentry_utc") or "").strip()
        source = (row.get("source") or "").strip()
        if not all((name, norad_id, timestamp, source)):
            errors.append(f"Row {line_number}: required field is empty.")
            continue
        if norad_id and not norad_id.isdigit():
            errors.append(f"Row {line_number}: norad_id must be numeric.")
            continue
        try:
            observed = _parse_utc(timestamp)
        except ValueError as exc:
            errors.append(f"Row {line_number}: invalid observed_reentry_utc ({exc}).")
            continue
        key = (norad_id, observed.isoformat())
        if key in seen:
            errors.append(f"Row {line_number}: duplicate object/time record.")
            continue
        seen.add(key)
        events.append({"object_name": name, "norad_id": int(norad_id),
                       "observed_reentry_utc": observed, "source": source})
    if not events:
        raise ValueError("No valid historical event rows were found.")
    return events, errors
