"""Eligibility checks and metrics for user-supplied forecast/event pairs."""

from __future__ import annotations

import math
from statistics import mean, median

from src.data.cords_loader import _parse_utc

REQUIRED_PAIR_COLUMNS = {
    "object_id", "predicted_at_utc", "predicted_reentry_utc",
    "observed_reentry_utc", "source",
}


def parse_prediction_pairs_csv(content: str | bytes) -> list[dict]:
    import csv
    import io
    if isinstance(content, bytes):
        content = content.decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(content)))
    if not rows:
        raise ValueError("Prediction-pair CSV has no rows.")
    missing = REQUIRED_PAIR_COLUMNS - set(rows[0])
    if missing:
        raise ValueError("Prediction-pair CSV is missing columns: " + ", ".join(sorted(missing)))
    seen = set()
    for line_number, row in enumerate(rows, start=2):
        key = (str(row.get("object_id") or "").strip(),
               str(row.get("predicted_at_utc") or "").strip(),
               str(row.get("observed_reentry_utc") or "").strip())
        if key in seen:
            raise ValueError(f"Prediction-pair CSV has a duplicate object/forecast/outcome row at line {line_number}.")
        seen.add(key)
    return rows


def evaluate_prediction_pairs(rows: list[dict]) -> dict:
    """Compute timing errors only for attributed rows forecast before the observed event."""
    if not rows:
        return {"eligible": False, "reason": "No prediction-versus-observation rows were supplied."}
    missing = REQUIRED_PAIR_COLUMNS - set(rows[0])
    if missing:
        return {"eligible": False, "reason": "Missing required columns: " + ", ".join(sorted(missing))}
    eligible = []
    rejected = []
    for index, row in enumerate(rows, start=1):
        try:
            predicted_at = _parse_utc(row["predicted_at_utc"])
            predicted_event = _parse_utc(row["predicted_reentry_utc"])
            observed_event = _parse_utc(row["observed_reentry_utc"])
            object_id = str(row["object_id"]).strip()
            source = str(row["source"]).strip()
            if not object_id or not source:
                raise ValueError("object_id and source are required")
            if predicted_at >= observed_event:
                raise ValueError("forecast issue time must precede observed event (future-data leakage)")
            if predicted_event <= predicted_at:
                raise ValueError("forecasted event time must be after the forecast issue time")
            signed_error_hours = (predicted_event - observed_event).total_seconds() / 3600.0
            eligible.append({"object_id": object_id, "source": source,
                             "predicted_at_utc": predicted_at,
                             "predicted_reentry_utc": predicted_event,
                             "observed_reentry_utc": observed_event,
                             "signed_error_hours": signed_error_hours,
                             "absolute_error_hours": abs(signed_error_hours)})
        except (KeyError, TypeError, ValueError) as exc:
            rejected.append({"row": index, "reason": str(exc)})
    if not eligible:
        return {"eligible": False, "reason": "No eligible forecast/event pairs.", "rejected": rejected}
    errors = [item["signed_error_hours"] for item in eligible]
    return {
        "eligible": True, "sample_size": len(eligible),
        "evaluation_start": min(item["observed_reentry_utc"] for item in eligible),
        "evaluation_end": max(item["observed_reentry_utc"] for item in eligible),
        "mae_hours": mean(abs(error) for error in errors),
        "median_absolute_error_hours": median(abs(error) for error in errors),
        "rmse_hours": math.sqrt(mean(error * error for error in errors)),
        "metric_definitions": {
            "MAE": "Mean absolute difference between predicted and observed reentry timestamps, in hours.",
            "RMSE": "Square root of mean squared timestamp difference, in hours.",
        },
        "rows": eligible, "rejected": rejected,
        "notice": "Metrics describe only the user-supplied eligible rows. Their source and forecast lineage have not been independently verified.",
    }
