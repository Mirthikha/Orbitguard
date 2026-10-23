"""Deterministic tests for Three.js globe geometry and run-bound inputs."""
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import unittest
import inspect

from src.mapping.globe import create_three_globe_html

SOURCE = Path(__file__).parents[1] / "src" / "mapping" / "globe.py"
SPEC = importlib.util.spec_from_file_location("orbitguard_globe_test", SOURCE)
globe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(globe)


def point(lat, lon, minute=0, **extra):
    return {"latitude": lat, "longitude": lon, "altitude_km": 400.0,
            "time": datetime(2026, 1, 1, 0, minute, tzinfo=timezone.utc), **extra}


def run(run_id, points, name="Test satellite"):
    return {"run_id": run_id, "configuration_fingerprint": run_id,
            "catalog_id": "99999", "name": name, "points": points}


class ThreeGlobeTest(unittest.TestCase):
    def test_package_import_and_streamlit_html_contract(self):
        self.assertEqual(list(inspect.signature(create_three_globe_html).parameters), ["run"])
        result = create_three_globe_html(run("minimal-run", [point(0, 0)]))
        self.assertIsInstance(result, str)
        self.assertTrue(result.lstrip().startswith("<!doctype html>"))
        self.assertIn('"run_id":"minimal-run"', result)
        self.assertIn('"three_xyz":[0.0,0.0,1.0]', result)

    def test_geodetic_conversion_uses_y_north_and_east_longitude(self):
        self.assertEqual(globe.geodetic_to_three_unit(0, 0), (0.0, 0.0, 1.0))
        x, y, z = globe.geodetic_to_three_unit(0, 90)
        self.assertAlmostEqual(x, 1.0)
        self.assertAlmostEqual(y, 0.0)
        self.assertAlmostEqual(z, 0.0, places=14)
        pole = globe.geodetic_to_three_unit(90, -20)
        self.assertAlmostEqual(pole[0], 0.0, places=14)
        self.assertAlmostEqual(pole[1], 1.0, places=14)
        self.assertAlmostEqual(pole[2], 0.0, places=14)
        with self.assertRaises(ValueError):
            globe.geodetic_to_three_unit(91, 0)

    def test_track_segments_preserve_real_coordinates_and_breaks(self):
        points = [point(2, 170), point(3, 179, 1), point(4, -179, 2),
                  point(5, -170, 3), point(6, -160, 4, break_before=True),
                  point(7, -150, 5)]
        payload = globe.build_globe_payload(run("run-a", points))
        self.assertEqual(payload["run_id"], "run-a")
        self.assertEqual([len(segment) for segment in payload["segments"]], [2, 2, 2])
        actual = payload["segments"][0][0]
        self.assertEqual((actual["latitude"], actual["longitude"]), (2.0, 170.0))
        self.assertEqual(actual["three_xyz"], list(globe.geodetic_to_three_unit(2, 170)))
        self.assertEqual(actual["time_utc"], "2026-01-01T00:00:00Z")

    def test_payload_is_bound_to_fingerprint_and_rejects_stale_or_empty_runs(self):
        run_a = run("fingerprint-a", [point(1, 2)])
        html_a = globe.create_three_globe_html(run_a)
        html_b = globe.create_three_globe_html(run("fingerprint-b", [point(30, 40)]))
        self.assertIn('"run_id":"fingerprint-a"', html_a)
        self.assertIn('"latitude":1.0', html_a)
        self.assertIn('"run_id":"fingerprint-b"', html_b)
        self.assertNotIn('"latitude":1.0', html_b)
        with self.assertRaises(ValueError):
            globe.build_globe_payload({**run_a, "configuration_fingerprint": "stale"})
        with self.assertRaisesRegex(ValueError, "no valid positions"):
            globe.build_globe_payload(run("empty-run", []))
        with self.assertRaisesRegex(ValueError, "no valid positions"):
            globe.build_globe_payload(run("invalid-run", [point(91, 0)]))

    def test_generated_document_has_pinned_three_texture_fallback_controls_and_active_data(self):
        document = globe.create_three_globe_html(run("run-style", [point(1, 2)]))
        self.assertIn(globe.THREE_MODULE_URL, document)
        self.assertIn(globe.THREE_ADDONS_URL, document)
        self.assertIn(globe.NASA_TEXTURE_URL, document)
        self.assertIn("NASA Earth Observatory", document)
        self.assertIn("MeshBasicMaterial({color:0x31546b})", document)
        self.assertIn("gridLine(points)", document)
        self.assertIn("OrbitControls", document)
        self.assertIn("0x35e0d0", document)
        self.assertIn("0xf5b942", document)
        self.assertIn("time_utc", document)
        self.assertIn("altitude_km", document)
        self.assertNotIn("Cesium", document)
        self.assertNotIn("cesium", document)

    def test_embedded_page_exposes_each_lifecycle_stage_and_exception(self):
        document = create_three_globe_html(run("diagnostic-run", [point(1, 2)]))
        for element_id in ("html-js-status", "three-status", "renderer-status",
                           "texture-status", "track-status", "exception-status"):
            self.assertIn(f'id="{element_id}"', document)
        self.assertIn('type="module"', document)
        self.assertIn("await import('three')", document)
        self.assertIn("new THREE.WebGLRenderer", document)
        self.assertIn("loader.load(", document)
        self.assertIn("setDiagnostic('track-status'", document)
        self.assertIn("setDiagnostic('exception-status',currentStage+' — '+detail,true)", document)
        self.assertIn("console.error('ORBITGUARD Three.js '+stage", document)


if __name__ == "__main__":
    unittest.main()
