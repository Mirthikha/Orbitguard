"""SGP4 propagation of a TLE over an explicitly bounded time interval."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.data.tle_loader import TLERecord
from src.orbit.coordinates import teme_to_geodetic


class PropagationError(RuntimeError):
    """Raised when SGP4 cannot propagate an object at a requested time."""


def propagate_ground_track(record: TLERecord, start: datetime, duration_minutes: int = 90,
                           step_seconds: int = 60) -> list[dict]:
    """Propagate with SGP4 and return valid geodetic points and UTC timestamps."""
    if start.tzinfo is None or duration_minutes <= 0 or step_seconds <= 0:
        raise ValueError("Use an aware start time and positive duration/step.")
    start = start.astimezone(timezone.utc)
    end = start + timedelta(minutes=duration_minutes)
    times = []
    moment = start
    while moment <= end:
        times.append(moment)
        moment += timedelta(seconds=step_seconds)
    if times[-1] != end:
        times.append(end)

    points = []
    errors = []
    break_before = False
    for moment in times:
        jd = record.satellite.jdsatepoch
        fr = record.satellite.jdsatepochF
        elapsed = (moment - record.epoch).total_seconds() / 86400
        jd += int(elapsed)
        fr += elapsed - int(elapsed)
        jd += int(fr)
        fr -= int(fr)
        error, position, _velocity = record.satellite.sgp4(jd, fr)
        if error:
            errors.append((moment, error))
            break_before = True
            continue
        lat, lon, altitude = teme_to_geodetic(position, moment)
        points.append({"time": moment, "latitude": lat, "longitude": lon,
                       "altitude_km": altitude, "break_before": break_before})
        break_before = False
    if not points:
        error_text = ", ".join(f"{code}" for _, code in errors[:3]) or "unknown error"
        raise PropagationError(f"SGP4 returned no valid positions (error codes: {error_text}).")
    for point in points:
        point["skipped_positions"] = len(errors)
    return points
