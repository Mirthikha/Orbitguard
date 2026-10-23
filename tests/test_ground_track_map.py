"""Offline tests for Folium ground-track layers and tile provenance."""

from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


class GroundTrackBasemapTest(unittest.TestCase):
    def test_uses_public_osm_tiles_with_visible_attribution_and_preserves_track(self):
        layers = []

        class FakeMap:
            def __init__(self, **kwargs):
                self.kwargs = kwargs
                self.layers = []
                self.html = self

            def add_child(self, child):
                self.child = child
                return child

            def get_root(self):
                return self

            def fit_bounds(self, bounds, **kwargs):
                self.bounds = bounds
                self.bounds_kwargs = kwargs

        class FakeLayer:
            def __init__(self, kind, args=(), kwargs=None):
                self.kind = kind
                self.args = args
                self.kwargs = kwargs or {}
                layers.append(self)

            def add_to(self, map_view):
                map_view.layers.append(self)
                return self

        fake_folium = types.ModuleType("folium")
        fake_folium.Map = FakeMap
        fake_folium.TileLayer = lambda *args, **kwargs: FakeLayer("tile", args, kwargs)
        fake_folium.PolyLine = lambda *args, **kwargs: FakeLayer("line", args, kwargs)
        fake_folium.CircleMarker = lambda *args, **kwargs: FakeLayer("marker", args, kwargs)
        fake_folium.LayerControl = lambda *args, **kwargs: FakeLayer("control", args, kwargs)
        fake_folium.Element = lambda value: value

        source = Path(__file__).parents[1] / "src" / "mapping" / "ground_track.py"
        spec = importlib.util.spec_from_file_location("_ground_track_test_module", source)
        module = importlib.util.module_from_spec(spec)
        points = [
            {"latitude": 0.0, "longitude": 170.0, "altitude_km": 400.0,
             "time": datetime(2025, 1, 1, tzinfo=timezone.utc)},
            {"latitude": 1.0, "longitude": 179.0, "altitude_km": 399.0,
             "time": datetime(2025, 1, 1, 0, 1, tzinfo=timezone.utc)},
            {"latitude": 2.0, "longitude": -179.0, "altitude_km": 398.0,
             "time": datetime(2025, 1, 1, 0, 2, tzinfo=timezone.utc)},
            {"latitude": 3.0, "longitude": -170.0, "altitude_km": 397.0,
             "time": datetime(2025, 1, 1, 0, 3, tzinfo=timezone.utc)},
            {"latitude": 4.0, "longitude": -160.0, "altitude_km": 396.0,
             "time": datetime(2025, 1, 1, 0, 4, tzinfo=timezone.utc), "break_before": True},
            {"latitude": 5.0, "longitude": -150.0, "altitude_km": 395.0,
             "time": datetime(2025, 1, 1, 0, 5, tzinfo=timezone.utc)},
        ]

        with patch.dict(sys.modules, {"folium": fake_folium}):
            spec.loader.exec_module(module)
            map_view = module.create_ground_track_map(points, "Test object")

        self.assertIsNone(map_view.kwargs["tiles"])
        tile = next(layer for layer in layers if layer.kind == "tile")
        self.assertEqual(tile.kwargs["tiles"], "https://tile.openstreetmap.org/{z}/{x}/{y}.png")
        self.assertIn("OpenStreetMap</a> contributors", tile.kwargs["attr"])
        self.assertIn("https://www.openstreetmap.org/copyright", tile.kwargs["attr"])
        self.assertEqual(tile.kwargs["name"], "OpenStreetMap")
        # Keep the source tile colors: no map-wide or tile-pane filter is used.
        self.assertNotIn("filter:", map_view.child)
        self.assertIn(".leaflet-container { background: #07111F", map_view.child)
        self.assertIn(".leaflet-control-attribution a { color: #38E1D1", map_view.child)
        self.assertEqual(map_view.kwargs["zoom_start"], 3)
        self.assertEqual(map_view.kwargs["min_zoom"], 2)
        self.assertEqual(map_view.kwargs["crs"], "EPSG3857")
        self.assertEqual(map_view.kwargs["location"], [2.5, 190.0])
        self.assertEqual(map_view.bounds, [[0.0, 170.0], [5.0, 210.0]])
        self.assertEqual(map_view.bounds_kwargs, {"padding": (32, 32), "max_zoom": 7})
        self.assertTrue(map_view.kwargs["control_scale"])
        self.assertEqual(next(layer for layer in layers if layer.kind == "control").kwargs,
                         {"collapsed": True})

        lines = [layer for layer in layers if layer.kind == "line" and
                 layer.kwargs["color"] == "#38E1D1"]
        casing = [layer for layer in layers if layer.kind == "line" and
                  layer.kwargs["color"] == "#07111F"]
        self.assertEqual(len(lines), 3)  # antimeridian and propagation gap split paths
        self.assertEqual(len(casing), 3)
        self.assertEqual(lines[0].args[0], [[0.0, 170.0], [1.0, 179.0]])
        self.assertEqual(lines[1].args[0], [[2.0, 181.0], [3.0, 190.0]])
        self.assertEqual(lines[0].kwargs["weight"], 3.5)
        self.assertEqual(lines[0].kwargs["opacity"], 0.98)
        markers = [layer for layer in layers if layer.kind == "marker"]
        self.assertEqual(len(markers), len(points) + 2)
        self.assertIn("UTC:", markers[0].kwargs["tooltip"])
        self.assertIn("Longitude:", markers[0].kwargs["tooltip"])
        self.assertEqual(markers[-2].kwargs["fill_color"], "#14B8A6")
        self.assertEqual(markers[-2].kwargs["color"], "#F8FBFF")
        self.assertEqual(markers[-1].kwargs["color"], "#7A4D00")
        self.assertEqual(markers[-1].kwargs["fill_color"], "#FFBE55")
        self.assertIn("Lat: 0.00000° · Lon: 170.00000°", markers[-2].kwargs["tooltip"])
        self.assertIn("Lat: 5.00000° · Lon: -150.00000°", markers[-1].kwargs["tooltip"])
        self.assertEqual(points[2]["longitude"], -179.0)  # display unwrapping did not mutate data


if __name__ == "__main__":
    unittest.main()
