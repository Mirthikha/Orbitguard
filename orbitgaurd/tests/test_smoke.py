"""Dashboard result-workflow tests with deterministic Streamlit and map adapters."""

from contextlib import ExitStack, nullcontext
from datetime import datetime, time, timedelta, timezone
import importlib
import sys
import types
import unittest
from unittest.mock import Mock, patch


class _Column:
    def __init__(self, ui):
        self.ui = ui
    def __enter__(self): return self
    def __exit__(self, *_args): return False
    def __getattr__(self, name):
        if name == "metric":
            return self.ui.metric
        if name == "slider":
            return lambda label, *_args, **kwargs: self.ui.session_state.get(
                kwargs.get("key"), _args[2] if len(_args) > 2 else kwargs.get("value"))
        if name in {"date_input", "time_input", "select_slider"}:
            return lambda _label, *_args, **kwargs: self.ui.session_state.get(
                kwargs.get("key"), kwargs.get("value"))
        return Mock()


def _with_checksum(line: str) -> str:
    line = line[:68].ljust(68)
    checksum = sum(int(char) if char.isdigit() else 1 if char == "-" else 0 for char in line) % 10
    return line + str(checksum)


class DashboardSmokeTest(unittest.TestCase):
    def _runtime(self, selector=None):
        ui = types.ModuleType("streamlit")
        ui.session_state = {}
        for name in ("set_page_config", "markdown", "title", "caption", "warning", "info", "success",
                     "header", "subheader", "metric", "code", "write", "error", "dataframe",
                     "download_button", "plotly_chart"):
            setattr(ui, name, Mock())
        ui.sidebar = nullcontext()
        ui._run_requested = True
        ui.button = Mock(side_effect=lambda label, **_kwargs:
                         bool(ui._run_requested and "Run Analysis" in label))
        ui.radio = Mock(return_value="Bundled sample")
        ui.selectbox = Mock(side_effect=selector or (lambda _label, options, **_kwargs: options[0]))
        ui.file_uploader = Mock(return_value=None)
        ui.columns = Mock(side_effect=lambda spec: [_Column(ui) for _ in range(spec if isinstance(spec, int) else len(spec))])
        ui.tabs = Mock(side_effect=lambda names: [nullcontext() for _ in names])
        ui.components = types.SimpleNamespace(v1=types.SimpleNamespace(html=Mock()))
        ui.container = Mock(return_value=nullcontext())
        ui.spinner = Mock(return_value=nullcontext())
        ui.expander = Mock(return_value=nullcontext())
        ui.form_submit_button = Mock(return_value=True)
        ui.date_input = Mock(side_effect=lambda _label, value=None, **_kwargs: value)
        ui.time_input = Mock(side_effect=lambda _label, value=None, **_kwargs: value)
        ui.slider = Mock(side_effect=lambda _label, _min, _max, value, *_args, **_kwargs: value)
        ui.select_slider = Mock(side_effect=lambda _label, options, value=None, **kwargs:
                                ui.session_state.get(kwargs.get("key"), value))
        ui.rerun = Mock()
        folium_ui = types.ModuleType("streamlit_folium")
        folium_ui.st_folium = Mock()
        track_module = types.ModuleType("src.mapping.ground_track")
        track_module.create_ground_track_map = Mock(return_value="test-map")

        go = types.ModuleType("plotly.graph_objects")
        go.Scatter = Mock(side_effect=lambda *args, **kwargs: {"args": args, "kwargs": kwargs})
        go.Figure = Mock(side_effect=lambda *args, **kwargs: Mock())
        plotly = types.ModuleType("plotly")
        plotly.__path__ = []

        previous_app = sys.modules.pop("app", None)
        modules = {"streamlit": ui, "streamlit_folium": folium_ui,
                   "src.mapping.ground_track": track_module,
                   "plotly": plotly, "plotly.graph_objects": go}
        return ui, folium_ui, track_module, previous_app, modules

    def _import_app(self, modules):
        return importlib.import_module("app")

    def _restore_app(self, previous_app):
        sys.modules.pop("app", None)
        if previous_app is not None:
            sys.modules["app"] = previous_app

    def test_run_renders_current_calculation_map_charts_table_and_provenance_csv(self):
        ui, folium_ui, track_module, previous_app, modules = self._runtime()
        try:
            with patch.dict(sys.modules, modules):
                app = self._import_app(modules)
                with ExitStack() as stack:
                    stack.enter_context(patch.object(app, "fetch_decaying_tles",
                        side_effect=AssertionError("sample mode must not call live TLE service")))
                    stack.enter_context(patch.object(app, "fetch_space_weather",
                        side_effect=AssertionError("sample mode must not call live NOAA service")))
                    stack.enter_context(patch.object(app, "fetch_solar_flux",
                        side_effect=AssertionError("sample mode must not call live NOAA service")))
                    globe_html = stack.enter_context(patch.object(app, "create_three_globe_html",
                        return_value="test-globe"))
                    fake_point = {"time": datetime(2026, 10, 21, tzinfo=timezone.utc), "latitude": 10.0,
                                  "longitude": 20.0, "altitude_km": 400.0, "break_before": False,
                                  "skipped_positions": 0}
                    propagate = stack.enter_context(patch.object(app, "propagate_ground_track",
                        return_value=[fake_point]))
                    app.main()
                selected = ui.session_state["analysis_run"]
                self.assertEqual(propagate.call_args.args[0].catalog_id, selected["catalog_id"])
                self.assertEqual(propagate.call_args.args[2:], (90, 60))
                self.assertEqual(track_module.create_ground_track_map.call_args.args[0], [fake_point])
                self.assertEqual(track_module.create_ground_track_map.call_args.args[1], selected["name"])
                self.assertEqual(folium_ui.st_folium.call_args.args[0], "test-map")
                self.assertTrue(folium_ui.st_folium.call_args.kwargs["use_container_width"])
                self.assertIs(globe_html.call_args.args[0], selected)
                self.assertEqual(ui.components.v1.html.call_args.args[0], "test-globe")
                self.assertEqual(ui.components.v1.html.call_args.kwargs,
                                 {"height": 620, "scrolling": False})
                self.assertTrue(any(call.args[0] == "SELECTED OBJECT" and
                                    selected["name"] in call.args[1] and
                                    str(selected["catalog_id"]) in call.args[1]
                                    for call in ui.metric.call_args_list))
                self.assertTrue(any(selected["run_id"][:12] in str(call)
                                    for call in ui.caption.call_args_list))
                self.assertGreaterEqual(ui.plotly_chart.call_count, 3)
                for chart_call in ui.plotly_chart.call_args_list[:3]:
                    chart = chart_call.args[0]
                    self.assertTrue(any(kwargs.get("meta") == {"analysis_run_id": selected["run_id"]}
                                        for _args, kwargs in chart.update_layout.call_args_list))
                    self.assertEqual(chart.update_layout.call_args.kwargs["template"], "plotly_dark")
                    self.assertEqual(chart.update_layout.call_args.kwargs["plot_bgcolor"], "#0D1B2A")
                self.assertGreaterEqual(ui.dataframe.call_count, 1)
                self.assertTrue(any("Analysis complete for" in str(call)
                                    for call in ui.success.call_args_list),
                                f"success={ui.success.call_args_list!r}; info={ui.info.call_args_list!r}")
                csv_call = next(call for call in ui.download_button.call_args_list
                                if "ground_track.csv" in str(call))
                csv_data = csv_call.args[1]
                self.assertIn("latitude_deg", csv_data)
                self.assertIn("object_name", csv_data)
                self.assertIn(str(selected["catalog_id"]), csv_data)
                self.assertIn("tle_epoch_utc", csv_data)
                self.assertIn("analysis_run_id", csv_data)
                self.assertIn(selected["run_id"], csv_data)
                self.assertTrue(any(selected["run_id"] in str(call.args[0])
                                    for call in ui.dataframe.call_args_list))
        finally:
            self._restore_app(previous_app)

    def test_switching_satellites_and_rerunning_replaces_all_bound_results(self):
        seen = {"count": 0}
        def choose(_label, options, **_kwargs):
            seen["count"] += 1
            return options[seen["count"] - 1]
        ui, folium_ui, map_module, previous_app, modules = self._runtime(choose)
        try:
            with patch.dict(sys.modules, modules):
                app = self._import_app(modules)
                outputs = [
                    [{"time": datetime(2026, 10, 21, tzinfo=timezone.utc), "latitude": 1.0,
                      "longitude": 2.0, "altitude_km": 300.0, "break_before": False}],
                    [{"time": datetime(2026, 10, 21, tzinfo=timezone.utc), "latitude": 3.0,
                      "longitude": 4.0, "altitude_km": 500.0, "break_before": False}],
                ]
                with patch.object(app, "propagate_ground_track", side_effect=outputs) as propagate:
                    app.main()
                    first_id = ui.session_state["analysis_run"]["catalog_id"]
                    app.main()
                run = ui.session_state["analysis_run"]
                self.assertNotEqual(first_id, run["catalog_id"])
                self.assertEqual(run["points"][0]["latitude"], 3.0)
                self.assertEqual(propagate.call_count, 2)
                self.assertEqual(map_module.create_ground_track_map.call_args.args[0], outputs[1])
                self.assertGreaterEqual(folium_ui.st_folium.call_count, 2)
        finally:
            self._restore_app(previous_app)

    def test_start_duration_and_step_changes_invalidate_then_replace_all_outputs(self):
        ui, folium_ui, map_module, previous_app, modules = self._runtime()
        try:
            with patch.dict(sys.modules, modules):
                app = self._import_app(modules)
                calls = []
                def propagate(record, start, duration, step):
                    calls.append((record.catalog_id, start, duration, step))
                    end_seconds = duration * 60
                    offsets = list(range(0, end_seconds + 1, step))
                    if offsets[-1] != end_seconds:
                        offsets.append(end_seconds)
                    latitude = float(len(calls) * 10)
                    return [{"time": start + timedelta(seconds=offset), "latitude": latitude,
                             "longitude": latitude + 1, "altitude_km": 400 + latitude,
                             "break_before": False} for offset in offsets]

                with patch.object(app, "propagate_ground_track", side_effect=propagate):
                    app.main()
                    first = ui.session_state["analysis_run"]
                    date_key = next(key for key in ui.session_state if key.startswith("analysis_start_date_"))
                    time_key = next(key for key in ui.session_state if key.startswith("analysis_start_time_"))
                    duration_key = next(key for key in ui.session_state if key.startswith("analysis_duration_"))
                    step_key = next(key for key in ui.session_state if key.startswith("analysis_step_"))
                    ui.session_state[date_key] += timedelta(days=1)
                    ui.session_state[time_key] = (datetime.combine(datetime.today(), ui.session_state[time_key]) +
                                                   timedelta(hours=1)).time()
                    ui.session_state[duration_key] = 60
                    ui.session_state[step_key] = 120
                    ui._run_requested = False
                    prior_success_count = ui.success.call_count
                    prior_map_count = folium_ui.st_folium.call_count
                    app.main()
                    self.assertEqual(ui.success.call_count, prior_success_count)
                    self.assertEqual(folium_ui.st_folium.call_count, prior_map_count)
                    self.assertTrue(any("Configuration changed" in str(call)
                                        for call in ui.info.call_args_list))

                    ui._run_requested = True
                    app.main()

                updated = ui.session_state["analysis_run"]
                self.assertNotEqual(first["run_id"], updated["run_id"])
                self.assertNotEqual(first["configuration"]["start_utc"], updated["configuration"]["start_utc"])
                self.assertEqual(updated["duration_minutes"], 60)
                self.assertEqual(updated["step_seconds"], 120)
                self.assertEqual(len(updated["points"]), 31)
                self.assertEqual(updated["points"][0]["time"], updated["start"])
                self.assertEqual(updated["points"][-1]["time"], updated["end"])
                self.assertEqual(map_module.create_ground_track_map.call_args.args[0], updated["points"])
                csv_call = next(call for call in reversed(ui.download_button.call_args_list)
                                if "ground_track.csv" in str(call))
                self.assertIn(updated["run_id"], csv_call.args[1])
                self.assertIn(updated["points"][0]["time"].isoformat(), csv_call.args[1])
        finally:
            self._restore_app(previous_app)

    def test_failed_second_run_does_not_show_previous_result_as_current(self):
        ui, folium_ui, _map_module, previous_app, modules = self._runtime()
        try:
            with patch.dict(sys.modules, modules):
                app = self._import_app(modules)
                point = {"time": datetime(2026, 10, 21, tzinfo=timezone.utc), "latitude": 1.0,
                         "longitude": 2.0, "altitude_km": 300.0, "break_before": False}
                with patch.object(app, "propagate_ground_track",
                                  side_effect=[[point], app.PropagationError("SGP4 error code 6")]):
                    app.main()
                    old_id = ui.session_state["analysis_run"]["run_id"]
                    successes = ui.success.call_count
                    app.main()
                self.assertNotIn("analysis_run", ui.session_state)
                self.assertEqual(ui.session_state["previous_analysis_run"]["run_id"], old_id)
                self.assertEqual(ui.session_state["analysis_status"], "failed")
                self.assertEqual(ui.success.call_count, successes)
                self.assertTrue(any("error code 6" in str(call) for call in ui.error.call_args_list))
                self.assertEqual(folium_ui.st_folium.call_count, 1)
        finally:
            self._restore_app(previous_app)

    def test_switching_from_sample_to_live_hides_sample_run(self):
        ui, folium_ui, _map_module, previous_app, modules = self._runtime()
        ui.radio.side_effect = ["Bundled sample", "Live feeds"]
        try:
            with patch.dict(sys.modules, modules):
                app = self._import_app(modules)
                with patch.object(app, "propagate_ground_track", return_value=[{
                    "time": datetime(2026, 10, 21, tzinfo=timezone.utc), "latitude": 1.0,
                    "longitude": 2.0, "altitude_km": 300.0, "break_before": False,
                }]):
                    app.main()
                    self.assertIn("analysis_run", ui.session_state)
                    ui._run_requested = False
                    app.main()
                self.assertNotIn("analysis_run", ui.session_state)
                self.assertEqual(folium_ui.st_folium.call_count, 1)
                self.assertTrue(any("Load / refresh live feeds" in str(call)
                                    for call in ui.info.call_args_list))
        finally:
            self._restore_app(previous_app)

    def test_replacing_tle_for_same_object_creates_new_run_and_positions(self):
        from dataclasses import replace
        from sgp4.api import Satrec
        from src.data.sample_data import load_sample_bundle
        from src.orbit.workflow import latest_record_per_object

        ui, folium_ui, map_module, previous_app, modules = self._runtime()
        sample_one = load_sample_bundle()
        record = latest_record_per_object(sample_one.records)[0]
        old_mean_anomaly = float(record.line2[43:51])
        new_mean_anomaly = f"{(old_mean_anomaly + 10) % 360:8.4f}"
        new_line2 = _with_checksum(record.line2[:43] + new_mean_anomaly + record.line2[51:68])
        replacement = replace(record, line2=new_line2,
                              satellite=Satrec.twoline2rv(record.line1, new_line2))
        sample_two = replace(sample_one, records=[replacement if item.catalog_id == record.catalog_id else item
                                                  for item in sample_one.records])
        try:
            with patch.dict(sys.modules, modules):
                app = self._import_app(modules)
                with patch.object(app, "load_sample_bundle", side_effect=[sample_one, sample_two]), \
                     patch.object(app, "propagate_ground_track", side_effect=[
                         [{"time": record.epoch, "latitude": 11.0, "longitude": 21.0,
                           "altitude_km": 300.0, "break_before": False}],
                         [{"time": record.epoch, "latitude": 22.0, "longitude": 32.0,
                           "altitude_km": 500.0, "break_before": False}],
                     ]):
                    app.main()
                    first = ui.session_state["analysis_run"]
                    app.main()
                second = ui.session_state["analysis_run"]
                self.assertEqual(first["catalog_id"], second["catalog_id"])
                self.assertNotEqual(first["input_snapshot"]["tle_sha256"],
                                    second["input_snapshot"]["tle_sha256"])
                self.assertNotEqual(first["run_id"], second["run_id"])
                self.assertEqual(second["input_snapshot"]["line2"], new_line2)
                self.assertEqual(second["points"][0]["latitude"], 22.0)
                self.assertEqual(map_module.create_ground_track_map.call_args.args[0], second["points"])
                self.assertEqual(folium_ui.st_folium.call_count, 2)
        finally:
            self._restore_app(previous_app)

    def test_same_named_upload_with_new_content_has_a_new_signature(self):
        ui, _folium_ui, _map_module, previous_app, modules = self._runtime()
        try:
            with patch.dict(sys.modules, modules):
                app = self._import_app(modules)
                class Upload:
                    name = "selected.tle"
                    def __init__(self, payload): self.payload = payload
                    def getvalue(self): return self.payload
                first = app._upload_signature(Upload(b"TLE version one"))
                second = app._upload_signature(Upload(b"TLE version two"))
                self.assertNotEqual(first, second)
                self.assertEqual(first[0][0], second[0][0])
        finally:
            self._restore_app(previous_app)

    def test_empty_propagation_is_explicit_and_never_successful(self):
        ui, _folium_ui, _map_module, previous_app, modules = self._runtime()
        try:
            with patch.dict(sys.modules, modules):
                app = self._import_app(modules)
                with patch.object(app, "propagate_ground_track", return_value=[]):
                    app.main()
                self.assertNotIn("analysis_run", ui.session_state)
                self.assertFalse(any("Analysis complete." in str(call)
                                     for call in ui.success.call_args_list))
                self.assertTrue(any("No valid positions were produced" in str(call)
                                    for call in ui.error.call_args_list))
        finally:
            self._restore_app(previous_app)

    def test_invalid_configuration_shows_error_without_success(self):
        ui, _folium_ui, _map_module, previous_app, modules = self._runtime()
        try:
            with patch.dict(sys.modules, modules):
                app = self._import_app(modules)
                with patch.object(app, "validate_run_configuration", side_effect=ValueError("test validation error")):
                    app.main()
                self.assertNotIn("analysis_run", ui.session_state)
                self.assertTrue(any("test validation error" in str(call)
                                    for call in ui.error.call_args_list))
                self.assertFalse(any("Analysis complete." in str(call)
                                     for call in ui.success.call_args_list))
        finally:
            self._restore_app(previous_app)


if __name__ == "__main__":
    unittest.main()
