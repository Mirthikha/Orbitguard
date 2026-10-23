"""Descriptive trends from multiple TLEs; never an independent reentry forecast."""

from __future__ import annotations

from datetime import datetime
from collections import Counter
import math
from statistics import median

EARTH_MU_KM3_S2 = 398600.4418
EARTH_EQUATORIAL_RADIUS_KM = 6378.137


def tle_perigee_series(records: list) -> list[dict]:
    """Calculate TLE-derived mean perigee altitude at each element epoch (km)."""
    points = []
    for record in sorted(records, key=lambda item: item.epoch):
        mean_motion_rad_s = record.satellite.no_kozai / 60.0
        if mean_motion_rad_s <= 0:
            continue
        semi_major_axis_km = (EARTH_MU_KM3_S2 / mean_motion_rad_s**2) ** (1 / 3)
        perigee_altitude_km = (
            semi_major_axis_km * (1 - record.satellite.ecco) - EARTH_EQUATORIAL_RADIUS_KM
        )
        points.append({"time": record.epoch, "perigee_altitude_km": perigee_altitude_km,
                       "catalog_id": record.catalog_id, "source": record.source})
    return points


def analyze_tle_decay_trend(records: list) -> dict:
    """Fit a transparent linear description only with >=3 TLEs spanning >=1 day.

    The slope describes TLE-derived perigee trend in the observed window. It is
    not a drag model, lifetime estimate, reentry date, or calibrated uncertainty.
    """
    points = tle_perigee_series(records)
    result = {"points": points, "supportable": False, "slope_km_per_day": None,
              "fit": [], "gaps": [], "outliers": [], "duplicate_epochs": [],
              "message": ""}
    epoch_counts = Counter(point["time"] for point in points)
    result["duplicate_epochs"] = [epoch for epoch, count in epoch_counts.items() if count > 1]
    if result["duplicate_epochs"]:
        result["message"] = "Duplicate TLE epochs were found; resolve duplicate or conflicting records before fitting a trend."
        return result
    if len(points) < 3:
        result["message"] = "At least three valid TLE epochs for this object are required to describe a trend."
        return result
    times = [point["time"] for point in points]
    days = [(moment - times[0]).total_seconds() / 86400.0 for moment in times]
    if days[-1] < 1.0:
        result["message"] = "The available TLE epochs span less than one day; a trend is not reported."
        return result
    values = [point["perigee_altitude_km"] for point in points]
    x_bar, y_bar = sum(days) / len(days), sum(values) / len(values)
    denominator = sum((x - x_bar) ** 2 for x in days)
    slope = sum((x - x_bar) * (y - y_bar) for x, y in zip(days, values)) / denominator
    intercept = y_bar - slope * x_bar
    fitted = [intercept + slope * x for x in days]
    residuals = [y - y_hat for y, y_hat in zip(values, fitted)]
    residual_median = median(residuals)
    mad = median([abs(value - residual_median) for value in residuals])
    outliers = [i for i, residual in enumerate(residuals)
                if mad > 0 and abs(residual - residual_median) > 3 * 1.4826 * mad]
    intervals = [(b - a).total_seconds() / 86400 for a, b in zip(times, times[1:])]
    typical_gap = median(intervals)
    gaps = [{"start": a, "end": b, "days": interval}
            for a, b, interval in zip(times, times[1:], intervals)
            if typical_gap > 0 and interval > 2 * typical_gap]
    result.update({"supportable": True, "slope_km_per_day": slope,
                   "fit": [{"time": point["time"], "perigee_altitude_km": value}
                           for point, value in zip(points, fitted)],
                   "gaps": gaps, "outliers": outliers,
                   "residual_rmse_km": math.sqrt(sum(value**2 for value in residuals) / len(residuals)),
                   "message": "Descriptive linear fit to TLE-derived perigee altitude over the observed interval only. No reentry date is inferred."})
    return result
