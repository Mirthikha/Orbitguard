"""Tests for authentic sample loading, upload validation, decay safeguards and metrics."""

import unittest

from src.data.cords_loader import validate_reentry_csv
from src.data.sample_data import (
    load_sample_bundle, parse_uploaded_kp_csv, parse_uploaded_solar_csv, parse_uploaded_tle,
)
from src.decay.altitude_analysis import analyze_tle_decay_trend
from src.validation.metrics import evaluate_prediction_pairs, parse_prediction_pairs_csv


class InputValidationTests(unittest.TestCase):
    def test_bundled_feed_files_load_with_provenance_without_network(self):
        bundle = load_sample_bundle()
        self.assertEqual(bundle.mode, "bundled")
        self.assertGreater(len(bundle.records), 1)
        self.assertTrue(bundle.kp)
        self.assertTrue(bundle.solar_flux)
        self.assertTrue(all(row["retrieval_status"] == "bundled" for row in bundle.kp))
        self.assertTrue(all(record.source.startswith("https://") for record in bundle.records))

    def test_single_tle_epoch_does_not_create_decay_rate_or_reentry_estimate(self):
        bundle = load_sample_bundle()
        record = bundle.records[0]
        result = analyze_tle_decay_trend([record])
        self.assertFalse(result["supportable"])
        self.assertIsNone(result["slope_km_per_day"])
        self.assertIn("three valid TLE epochs", result["message"])

    def test_tle_and_space_weather_upload_parsers_keep_uploaded_attribution(self):
        bundle = load_sample_bundle()
        record = bundle.records[0]
        uploaded = parse_uploaded_tle(
            f"{record.name}\n{record.line1}\n{record.line2}", "local.tle")
        self.assertEqual(uploaded[0].retrieval_status, "uploaded")
        self.assertIn("local.tle", uploaded[0].source)
        kp = parse_uploaded_kp_csv(
            "time_tag,Kp,a_running,station_count\n2026-10-22T00:00:00,2.33,9,8\n", "kp.csv")
        solar = parse_uploaded_solar_csv(
            "time_tag,flux\n2026-10-22T20:00:00,106\n", "solar.csv")
        self.assertEqual(kp[0]["retrieval_status"], "uploaded")
        self.assertEqual(solar[0]["flux_sfu"], 106.0)

    def test_historical_event_schema_rejects_naive_dates_and_duplicates(self):
        events, issues = validate_reentry_csv(
            "object_name,norad_id,observed_reentry_utc,source\n"
            "Object A,12345,2025-01-01T00:00:00Z,Provider\n"
            "Object A,12345,2025-01-01T00:00:00Z,Provider\n"
            "Object B,23456,2025-01-02T00:00:00,Provider\n")
        self.assertEqual(len(events), 1)
        self.assertEqual(len(issues), 2)
        with self.assertRaises(ValueError):
            validate_reentry_csv("name,date\nA,2025-01-01\n")

    def test_validation_metrics_reject_future_leakage_and_calculate_defined_error(self):
        csv_text = (
            "object_id,predicted_at_utc,predicted_reentry_utc,observed_reentry_utc,source\n"
            "123,2025-01-01T00:00:00Z,2025-01-02T01:00:00Z,2025-01-02T00:00:00Z,Archive\n"
            "456,2025-02-03T13:00:00Z,2025-02-04T00:00:00Z,2025-02-03T12:00:00Z,Archive\n"
        )
        result = evaluate_prediction_pairs(parse_prediction_pairs_csv(csv_text))
        self.assertTrue(result["eligible"])
        self.assertEqual(result["sample_size"], 1)
        self.assertEqual(result["mae_hours"], 1.0)
        self.assertEqual(len(result["rejected"]), 1)


if __name__ == "__main__":
    unittest.main()
