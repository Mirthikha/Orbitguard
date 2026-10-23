"""Offline tests for the public feed clients, validation, cache, and propagation."""

from datetime import datetime, timezone
from dataclasses import replace
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from src.data.space_weather import (fetch_solar_flux, fetch_space_weather, parse_kp_response,
                                    parse_solar_flux_response)
from src.data.tle_loader import DataFeedError, fetch_decaying_tles, parse_tle_text
from src.orbit.propagator import PropagationError, propagate_ground_track
from src.orbit.workflow import (latest_record_per_object, requested_point_count, track_csv,
                                validate_run_configuration)


def _with_checksum(line: str) -> str:
    line = line[:68].ljust(68)
    checksum = sum(int(char) if char.isdigit() else 1 if char == "-" else 0 for char in line) % 10
    return line + str(checksum)


# Public Vanguard 1 SGP4 verification-vector elements; checksum digits are normalized
# from the published element columns so the fixture is accepted by strict validators.
TLE_TEXT = "\n".join([
    "VANGUARD 1",
    _with_checksum("1 00005U 58002B   00179.78495062  .00000023  00000-0  28098-4 0  475"),
    _with_checksum("2 00005  34.2682 331.5174 1849677 331.7664  19.3264 10.8241915741366"),
])


class _Session:
    def __init__(self, response): self.response = response
    def get(self, url, **kwargs):
        self.url, self.kwargs = url, kwargs
        return self.response


class DataPipelineTests(unittest.TestCase):
    def test_celestrak_fetch_validates_and_caches_tle(self):
        response = Mock(text=TLE_TEXT)
        response.raise_for_status.return_value = None
        session = _Session(response)
        now = datetime(2026, 10, 23, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as folder:
            cache = Path(folder) / "tle.json"
            records = fetch_decaying_tles(session=session, cache_path=cache, now=lambda: now)
            cached_records = fetch_decaying_tles(session=Mock(), cache_path=cache, now=lambda: now)
        self.assertEqual(records[0].catalog_id, 5)
        self.assertEqual(records[0].epoch.year, 2000)
        self.assertEqual(records[0].retrieved_at, now)
        self.assertEqual(session.kwargs["params"], {"SPECIAL": "DECAYING", "FORMAT": "TLE"})
        self.assertEqual(len(cached_records), 1)

    def test_celestrak_rejects_bad_checksum_and_handles_network_failure(self):
        broken = TLE_TEXT[:-1] + ("0" if TLE_TEXT[-1] != "0" else "1")
        with self.assertRaises(DataFeedError):
            parse_tle_text(broken)
        session = Mock()
        import requests
        session.get.side_effect = requests.ConnectionError("offline")
        with tempfile.TemporaryDirectory() as folder, self.assertRaises(DataFeedError):
            fetch_decaying_tles(session=session, cache_path=Path(folder) / "missing.json")

    def test_noaa_inspected_schema_and_mocked_http_response(self):
        now = datetime(2026, 10, 23, tzinfo=timezone.utc)
        payload = [{"time_tag": "2026-10-23T00:00:00", "Kp": 2.33,
                    "a_running": 9, "station_count": 8}]
        response = Mock()
        response.json.return_value = payload
        response.raise_for_status.return_value = None
        session = _Session(response)
        with tempfile.TemporaryDirectory() as folder:
            observations = fetch_space_weather(session=session, cache_path=Path(folder) / "kp.json",
                                               now=lambda: now)
        self.assertEqual(observations[0]["kp"], 2.33)
        self.assertEqual(observations[0]["time"].tzinfo, timezone.utc)
        self.assertEqual(session.kwargs["timeout"], 12)
        with self.assertRaises(DataFeedError):
            parse_kp_response([{"time_tag": "2026-10-23T00:00:00", "Kp": 99}])

    def test_noaa_solar_flux_schema_and_mocked_http_response(self):
        now = datetime(2026, 10, 23, tzinfo=timezone.utc)
        response = Mock()
        response.json.return_value = [{"time_tag": "2026-10-22T20:00:00", "flux": 106}]
        response.raise_for_status.return_value = None
        with tempfile.TemporaryDirectory() as folder:
            rows = fetch_solar_flux(session=_Session(response), cache_path=Path(folder) / "solar.json",
                                    now=lambda: now)
        self.assertEqual(rows[0]["flux_sfu"], 106.0)
        self.assertEqual(rows[0]["time"].tzinfo, timezone.utc)
        with self.assertRaises(DataFeedError):
            parse_solar_flux_response([{"time_tag": "2026-10-23T00:00:00", "flux": -1}])

    def test_sgp4_propagates_and_coordinate_transform_is_bounded(self):
        epoch = datetime(2000, 6, 27, 18, 50, 19, tzinfo=timezone.utc)
        record = parse_tle_text(TLE_TEXT, epoch)[0]
        points = propagate_ground_track(record, epoch, duration_minutes=10, step_seconds=60)
        self.assertEqual(len(points), 11)
        self.assertTrue(all(-90 <= point["latitude"] <= 90 for point in points))
        self.assertTrue(all(-180 <= point["longitude"] <= 180 for point in points))
        self.assertTrue(all(isinstance(point["time"], datetime) for point in points))

    def test_partial_and_total_sgp4_failures_are_reported(self):
        epoch = datetime(2000, 6, 27, 18, 50, 19, tzinfo=timezone.utc)
        record = parse_tle_text(TLE_TEXT, epoch)[0]
        satellite = SimpleNamespace(jdsatepoch=record.satellite.jdsatepoch,
                                    jdsatepochF=record.satellite.jdsatepochF)
        satellite.sgp4 = Mock(side_effect=[
            (0, (7000.0, 0.0, 0.0), (0.0, 7.0, 0.0)),
            (6, (0, 0, 0), (0, 0, 0)),
            (0, (0.0, 7000.0, 0.0), (0.0, 7.0, 0.0)),
        ])
        partial = propagate_ground_track(replace(record, satellite=satellite), epoch,
                                         duration_minutes=2, step_seconds=60)
        self.assertEqual(len(partial), 2)
        self.assertEqual(partial[0]["skipped_positions"], 1)
        self.assertTrue(partial[1]["break_before"])
        satellite.sgp4 = Mock(return_value=(6, (0, 0, 0), (0, 0, 0)))
        with self.assertRaises(PropagationError):
            propagate_ground_track(replace(record, satellite=satellite), epoch,
                                   duration_minutes=1, step_seconds=60)

    def test_selection_validation_and_track_export(self):
        epoch = datetime(2000, 6, 27, 18, 50, 19, tzinfo=timezone.utc)
        record = parse_tle_text(TLE_TEXT, epoch)[0]
        self.assertEqual(latest_record_per_object([record, record]), [record])
        validate_run_configuration(record, epoch, 60, 60)
        with self.assertRaises(ValueError):
            validate_run_configuration(record, epoch.replace(year=2001), 60, 60)
        self.assertEqual(requested_point_count(10, 60), 11)
        points = propagate_ground_track(record, epoch, duration_minutes=1, step_seconds=60)
        exported = track_csv(points)
        self.assertIn("latitude_deg", exported.splitlines()[0])
        self.assertGreater(float(exported.splitlines()[1].split(",")[3]), 0)


if __name__ == "__main__":
    unittest.main()
