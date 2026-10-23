"""TEME-to-ground coordinates using the conventional GMST rotation."""

from __future__ import annotations

from datetime import datetime, timezone
import math


def julian_date(moment: datetime) -> float:
    """Convert an aware datetime to Julian date in UTC."""
    if moment.tzinfo is None:
        raise ValueError("Datetime must be timezone-aware.")
    moment = moment.astimezone(timezone.utc)
    year, month = moment.year, moment.month
    day = moment.day + (moment.hour + (moment.minute + (moment.second + moment.microsecond / 1e6) / 60) / 60) / 24
    if month <= 2:
        year -= 1
        month += 12
    a = year // 100
    b = 2 - a + a // 4
    return math.floor(365.25 * (year + 4716)) + math.floor(30.6001 * (month + 1)) + day + b - 1524.5


def teme_to_geodetic(position_km: tuple[float, float, float], moment: datetime) -> tuple[float, float, float]:
    """Rotate SGP4 TEME km into Earth-fixed coordinates, then WGS-84 geodetic lat/lon/alt.

    Uses UTC as a UT1 approximation and omits polar motion; resulting map points are
    suitable for an illustrative orbital ground track, not precision geodesy.
    """
    x, y, z = position_km
    jd = julian_date(moment)
    t = (jd - 2451545.0) / 36525.0
    gmst_deg = (280.46061837 + 360.98564736629 * (jd - 2451545.0)
                + 0.000387933 * t * t - t * t * t / 38710000.0) % 360
    theta = math.radians(gmst_deg)
    xe = math.cos(theta) * x + math.sin(theta) * y
    ye = -math.sin(theta) * x + math.cos(theta) * y

    a, flattening = 6378.137, 1 / 298.257223563
    eccentricity_sq = flattening * (2 - flattening)
    longitude = math.atan2(ye, xe)
    p = math.hypot(xe, ye)
    latitude = math.atan2(z, p * (1 - eccentricity_sq))
    for _ in range(8):
        n = a / math.sqrt(1 - eccentricity_sq * math.sin(latitude) ** 2)
        altitude = p / max(math.cos(latitude), 1e-12) - n
        latitude = math.atan2(z, p * (1 - eccentricity_sq * n / (n + altitude)))
    n = a / math.sqrt(1 - eccentricity_sq * math.sin(latitude) ** 2)
    altitude = p / max(math.cos(latitude), 1e-12) - n
    return math.degrees(latitude), ((math.degrees(longitude) + 180) % 360) - 180, altitude
