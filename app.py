"""ORBITGUARD satellite orbit monitoring and reentry analysis dashboard."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import html
import json

import streamlit as st
from streamlit_folium import st_folium

from src.data.cords_loader import validate_reentry_csv
from src.data.sample_data import (
    DataBundle, load_sample_bundle, parse_uploaded_kp_csv, parse_uploaded_solar_csv,
    parse_uploaded_tle,
)
from src.data.space_weather import fetch_solar_flux, fetch_space_weather
from src.data.tle_loader import DataFeedError, fetch_decaying_tles
from src.decay.altitude_analysis import analyze_tle_decay_trend
from src.mapping.ground_track import create_ground_track_map
from src.mapping.globe import create_three_globe_html
from src.orbit.propagator import PropagationError, propagate_ground_track
from src.orbit.workflow import (
    build_run_identity, latest_record_per_object, requested_point_count, track_csv,
    validate_run_configuration,
)
from src.validation.metrics import evaluate_prediction_pairs, parse_prediction_pairs_csv


def _load_live_bundle() -> DataBundle:
    # Keep the CelesTrak two-hour cache; its GP usage policy asks clients not
    # to fetch the same feed more than once per update.
    records = fetch_decaying_tles(force_refresh=False)
    notices = []
    try:
        kp = fetch_space_weather(force_refresh=False)
    except DataFeedError as exc:
        kp = []
        notices.append(f"NOAA Kp unavailable: {exc}")
    try:
        solar = fetch_solar_flux(force_refresh=False)
    except DataFeedError as exc:
        solar = []
        notices.append(f"NOAA solar flux unavailable: {exc}")
    retrieved = max((record.retrieved_at for record in records), default=datetime.now(timezone.utc))
    return DataBundle(records, kp, solar, "live", "CelesTrak and NOAA SWPC public feeds",
                      retrieved, notices)


def _load_upload_bundle(tle_upload, kp_upload, solar_upload) -> DataBundle:
    if tle_upload is None:
        raise ValueError("Upload a 2LE or 3LE TLE file to load orbital data.")
    records = parse_uploaded_tle(tle_upload.getvalue(), tle_upload.name)
    notices = []
    kp, solar = [], []
    if kp_upload is not None:
        kp = parse_uploaded_kp_csv(kp_upload.getvalue(), kp_upload.name)
    else:
        notices.append("No Kp CSV uploaded; the Kp panel is empty.")
    if solar_upload is not None:
        solar = parse_uploaded_solar_csv(solar_upload.getvalue(), solar_upload.name)
    else:
        notices.append("No solar-flux CSV uploaded; the solar-flux panel is empty.")
    return DataBundle(records, kp, solar, "upload", "User-uploaded files",
                      datetime.now(timezone.utc), notices)


def _upload_signature(*uploads) -> tuple:
    """Detect content changes even when an uploaded file keeps the same name."""
    return tuple(None if upload is None else
                 (upload.name, hashlib.sha256(upload.getvalue()).hexdigest())
                 for upload in uploads)


def _break_aware_series(points: list[dict], value_key: str, split_antimeridian: bool = False):
    """Build chart arrays with explicit gaps after failed propagation or longitude wraps."""
    times, values = [], []
    previous_longitude = None
    for point in points:
        value = point[value_key]
        split = point.get("break_before", False)
        if split_antimeridian and previous_longitude is not None:
            split = split or abs(value - previous_longitude) > 180
        if split:
            times.append(point["time"])
            values.append(None)
        times.append(point["time"])
        values.append(value)
        previous_longitude = value if split_antimeridian else None
    return times, values


def _break_aware_customdata(points: list[dict], split_antimeridian: bool = False):
    """Keep Plotly hover metadata aligned with inserted gap separators."""
    rows = []
    previous_longitude = None
    for point in points:
        split = point.get("break_before", False)
        if split_antimeridian and previous_longitude is not None:
            split = split or abs(point["longitude"] - previous_longitude) > 180
        if split:
            rows.append([None, None, None])
        rows.append([point["latitude"], point["longitude"], point["altitude_km"]])
        previous_longitude = point["longitude"] if split_antimeridian else None
    return rows


def _style_figure(figure, title: str, x_title: str, y_title: str,
                  analysis_run_id: str | None = None) -> None:
    """Apply the shared ORBITGUARD dark chart treatment and readable axes."""
    layout = {
        "title": {"text": title, "x": 0.02, "xanchor": "left"},
        "xaxis_title": x_title,
        "yaxis_title": y_title,
        "template": "plotly_dark",
        "paper_bgcolor": "rgba(0,0,0,0)",
        "plot_bgcolor": "#0D1B2A",
        "font": {"color": "#E8F1F8", "family": "Inter, Segoe UI, sans-serif", "size": 12},
        "margin": {"l": 46, "r": 20, "t": 54, "b": 44},
        "height": 350,
        "hovermode": "x unified",
        "legend": {"orientation": "h", "yanchor": "bottom", "y": 1.02,
                   "xanchor": "right", "x": 1},
    }
    if analysis_run_id is not None:
        layout["meta"] = {"analysis_run_id": analysis_run_id}
    figure.update_layout(**layout)
    axis_style = {"gridcolor": "#22394D", "zerolinecolor": "#22394D",
                  "linecolor": "#22394D", "tickfont": {"color": "#9FB2C5"},
                  "title_font": {"color": "#9FB2C5"}}
    figure.update_xaxes(**axis_style, tickformat="%d %b<br>%H:%M")
    figure.update_yaxes(**axis_style)


def _format_utc_range(start: datetime, end: datetime) -> str:
    if start.date() == end.date():
        return f"{start:%d %b %H:%M}–{end:%H:%M} UTC"
    return f"{start:%d %b %H:%M}–{end:%d %b %H:%M} UTC"


def _plot_space_weather(rows: list[dict], value_key: str, title: str, y_label: str,
                        run: dict | None, expected_step_hours: float) -> None:
    if not rows:
        st.info("No data for this panel in the active source. Load NOAA data or upload a supported CSV.")
        return
    st.caption(f"Coverage: {min(row['time'] for row in rows):%Y-%m-%d %H:%M UTC} — "
               f"{max(row['time'] for row in rows):%Y-%m-%d %H:%M UTC} · "
               f"{rows[0]['source']} · {rows[0]['retrieval_status']} · "
               f"retrieved {rows[0]['retrieved_at']:%Y-%m-%d %H:%M UTC}")
    ordered = sorted(rows, key=lambda row: row["time"])
    gaps = [(b["time"] - a["time"]).total_seconds() / 3600
            for a, b in zip(ordered, ordered[1:])]
    gap_count = sum(gap > expected_step_hours * 1.5 for gap in gaps)
    st.caption(f"{len(rows)} observations · {gap_count} interval gap(s) larger than "
               f"{expected_step_hours * 1.5:g} hours.")
    try:
        import plotly.graph_objects as go
        figure = go.Figure()
        figure.add_trace(go.Scatter(
            x=[row["time"] for row in ordered], y=[row[value_key] for row in ordered],
            mode="lines+markers", line={"color": "#38E1D1", "width": 2},
            marker={"size": 5, "color": "#14B8A6"}, name=title,
            hovertemplate="UTC: %{x|%Y-%m-%d %H:%M:%S} UTC<br>Value: %{y:.2f}<extra></extra>",
        ))
        if run:
            figure.add_vrect(x0=run["start"], x1=run["end"], fillcolor="#ffb45b",
                             opacity=0.16, line_width=0, annotation_text="Analysis interval")
        _style_figure(figure, title, "Observation time (UTC)", y_label)
        st.plotly_chart(figure, use_container_width=True)
    except ImportError:
        st.warning("Space-weather charts are unavailable; the observation data remain loaded.")
    st.dataframe([{"time_utc": row["time"].isoformat(), value_key: row[value_key]}
                  for row in ordered], use_container_width=True, hide_index=True)


def main() -> None:
    st.set_page_config(page_title="ORBITGUARD | Orbit Analysis", page_icon="🛰️",
                       layout="wide", initial_sidebar_state="expanded")
    st.markdown(
        """<style>
        :root { color-scheme: dark; }
        h1,h2,h3 { color: #E8F1F8; }
        h1 { font-size: 2.15rem; letter-spacing: .045em; margin-bottom: .15rem; }
        h2,h3 { letter-spacing: .01em; }
        button:focus-visible, input:focus-visible { outline: 2px solid #38E1D1; outline-offset: 2px; }
        [data-testid="stAlert"] { border-radius: 9px; }
        .og-eyebrow { color: #38E1D1; font-size: .72rem; font-weight: 700; letter-spacing: .15em; text-transform: uppercase; margin: .1rem 0 .35rem; }
        .og-subtitle { color: #9FB2C5; font-size: .98rem; margin: 0 0 .9rem; }
        .og-source-strip { display: flex; flex-wrap: wrap; align-items: center; gap: .55rem .8rem; background: #0D1B2A; border: 1px solid #22394D; border-left: 3px solid #14B8A6; border-radius: 9px; padding: .65rem .85rem; margin: .4rem 0 1rem; color: #9FB2C5; font-size: .84rem; }
        .og-source-strip strong { color: #E8F1F8; font-weight: 600; }
        .og-source-dot { color: #38E1D1; }
        </style>""", unsafe_allow_html=True,
    )
    st.markdown('<div class="og-eyebrow">Orbital monitoring · mission analysis</div>', unsafe_allow_html=True)
    st.title("ORBITGUARD")
    st.markdown('<div class="og-subtitle">TLE-based orbit monitoring and calculated ground-track analysis</div>',
                unsafe_allow_html=True)

    state = st.session_state
    with st.sidebar:
        st.markdown("### Data Source")
        st.caption("Bundled sample works offline. Live data is retrieved when requested. Upload a TLE or supported files.")
        if st.button("Clear selections and results", use_container_width=True):
            for key in ("active_bundle", "active_bundle_mode", "analysis_run", "selected_catalog_id",
                        "source_mode", "loaded_upload_names", "uploaded_originals",
                        "loaded_upload_signature", "historical_event_upload",
                        "prediction_pairs_upload", "object_choice"):
                state.pop(key, None)
            st.rerun()
        source_mode = st.radio(
            "Choose a source", ["Bundled sample", "Live feeds", "Upload my data"],
            key="source_mode", help="Choose the dataset used by the object selector and analysis.",
        )
        active_mode = {"Bundled sample": "sample", "Live feeds": "live", "Upload my data": "upload"}[source_mode]
        if state.get("_last_source_mode") != active_mode:
            state.pop("active_bundle", None)
            state.pop("active_bundle_mode", None)
            state.pop("analysis_run", None)
            state.pop("object_choice", None)
            state.pop("weather_chart_start", None)
            state.pop("weather_chart_end", None)
            state["_last_source_mode"] = active_mode
        tle_upload = kp_upload = solar_upload = None
        if active_mode == "sample":
            try:
                with st.spinner("Loading the verified bundled feed snapshot…"):
                    bundle = load_sample_bundle()
                state["active_bundle"] = bundle
                state["active_bundle_mode"] = "sample"
            except (OSError, ValueError, KeyError, DataFeedError) as exc:
                st.error(f"Bundled sample data could not be loaded: {exc}")
        elif active_mode == "live":
            if st.button("Load / refresh live feeds", type="primary", use_container_width=True):
                try:
                    with st.spinner("Retrieving public TLE and NOAA feeds…"):
                        bundle = _load_live_bundle()
                    state["active_bundle"], state["active_bundle_mode"] = bundle, "live"
                    state.pop("analysis_run", None)
                    state.pop("object_choice", None)
                except DataFeedError as exc:
                    st.error(f"Live TLE feed unavailable: {exc}")
            if state.get("active_bundle_mode") == "live":
                bundle = state.get("active_bundle")
                if bundle and bundle.records:
                    st.caption(f"{len(bundle.records)} objects · retrieved {bundle.retrieved_at:%Y-%m-%d %H:%M UTC}")
        else:
            tle_upload = st.file_uploader("TLE file (2LE / 3LE)", type=["txt", "tle", "3le"])
            kp_upload = st.file_uploader("Optional Kp CSV", type=["csv"], key="upload_kp")
            solar_upload = st.file_uploader("Optional solar-flux CSV", type=["csv"], key="upload_solar")
            if st.button("Load uploaded files", type="primary", use_container_width=True):
                try:
                    with st.spinner("Validating uploaded files…"):
                        bundle = _load_upload_bundle(tle_upload, kp_upload, solar_upload)
                    state["active_bundle"], state["active_bundle_mode"] = bundle, "upload"
                    state["loaded_upload_names"] = (tle_upload.name, kp_upload.name if kp_upload else None,
                                                     solar_upload.name if solar_upload else None)
                    state["loaded_upload_signature"] = _upload_signature(tle_upload, kp_upload, solar_upload)
                    state["uploaded_originals"] = {
                        tle_upload.name: tle_upload.getvalue(),
                        **({kp_upload.name: kp_upload.getvalue()} if kp_upload else {}),
                        **({solar_upload.name: solar_upload.getvalue()} if solar_upload else {}),
                    }
                    state.pop("analysis_run", None)
                    state.pop("object_choice", None)
                    st.caption(f"Loaded {len(bundle.records)} TLE record(s).")
                except (ValueError, DataFeedError, UnicodeDecodeError) as exc:
                    st.error(f"Upload validation failed: {exc}")

    bundle = state.get("active_bundle") if state.get("active_bundle_mode") == active_mode else None
    if active_mode == "sample":
        bundle = state.get("active_bundle")
    if active_mode == "upload" and bundle is not None:
        selected_upload_signature = _upload_signature(tle_upload, kp_upload, solar_upload)
        if selected_upload_signature != state.get("loaded_upload_signature"):
            bundle = None
            st.info("Uploaded file content changed. Select **Load uploaded files** to validate and activate the new data.")

    source_labels = {"sample": "Bundled sample", "bundled": "Bundled sample",
                     "live": "Live / cached feeds", "upload": "User upload"}
    if bundle is not None:
        source_detail = html.escape(bundle.source)
        source_retrieved = f"retrieved {bundle.retrieved_at:%Y-%m-%d %H:%M UTC}"
        source_status = source_labels.get(bundle.mode, bundle.mode)
    else:
        source_detail = "Load a data source to begin"
        source_retrieved = ""
        source_status = source_labels[active_mode]
    freshness_html = (f'<span class="og-source-dot">·</span><span>{source_retrieved}</span>'
                      if source_retrieved else "")
    st.markdown(
        f'<div class="og-source-strip"><strong>DATA LINK</strong>'
        f'<span class="og-source-dot">●</span><strong>{html.escape(source_status)}</strong>'
        f'<span>{source_detail}</span>'
        f'{freshness_html}</div>',
        unsafe_allow_html=True,
    )

    selected_record = None
    current_run_identity = None

    with st.container(border=True):
        st.subheader("Mission Setup")
        if bundle is None:
            if active_mode == "live":
                st.info("Select **Load / refresh live feeds** in the Data Source panel to retrieve current TLE and weather data.")
            elif active_mode == "upload":
                st.info("Upload a TLE file and press **Load uploaded files**. Weather CSVs are optional.")
            else:
                st.error("Bundled sample files are unavailable or invalid.")
        else:
            st.caption("Select an object and configure the interval for this SGP4 propagation run.")
            for notice in bundle.notices:
                st.warning(notice)
            objects = latest_record_per_object(bundle.records)
            if not objects:
                st.warning("This source contains no valid TLE objects.")
            else:
                choices = {f"{record.name}  ·  NORAD {record.catalog_id}": record for record in objects}
                choice_labels = list(choices)
                prior_id = state.get("selected_catalog_id")
                default_index = next((i for i, item in enumerate(objects) if item.catalog_id == prior_id), 0)
                selected_label = st.selectbox("Select Satellite", choice_labels,
                    index=default_index, key="object_choice",
                    help="The selector is populated from the currently loaded dataset.")
                selected_record = choices[selected_label]
                state["selected_catalog_id"] = selected_record.catalog_id
                if selected_record.retrieval_status == "stale cache":
                    st.warning("The active TLE came from a stale local cache after a feed retrieval failure. Check its epoch before interpreting the track.")
                with st.container(border=True):
                    cols = st.columns(4)
                    cols[0].metric("NORAD ID", selected_record.catalog_id)
                    cols[1].metric("TLE EPOCH (UTC)", selected_record.epoch.strftime("%Y-%m-%d %H:%M"))
                    cols[2].metric("DATA QUALITY", selected_record.retrieval_status.title())
                    cols[3].metric("TLE RECORDS", sum(
                        rec.catalog_id == selected_record.catalog_id for rec in bundle.records))
                preferred_start = (selected_record.epoch if bundle.mode in {"bundled", "upload"}
                                   else datetime.now(timezone.utc))
                if abs((preferred_start - selected_record.epoch).total_seconds()) > 7 * 86400:
                    preferred_start = selected_record.epoch
                    st.info("The TLE is over seven days from the current time. The default analysis starts at its TLE epoch.")
                st.caption(f"Orbital element age at default start: {(preferred_start - selected_record.epoch).total_seconds() / 3600:.1f} hours.")
                tle_hash = build_run_identity(selected_record, bundle.mode, preferred_start, 90, 60)["tle_sha256"][:12]
                widget_scope = f"{selected_record.catalog_id}_{tle_hash}"
                start_date_key = f"analysis_start_date_{widget_scope}"
                start_time_key = f"analysis_start_time_{widget_scope}"
                duration_key = f"analysis_duration_{widget_scope}"
                step_key = f"analysis_step_{widget_scope}"
                state.setdefault(start_date_key, preferred_start.date())
                state.setdefault(start_time_key, preferred_start.time().replace(tzinfo=None, microsecond=0))
                state.setdefault(duration_key, 90)
                state.setdefault(step_key, 60)
                st.markdown("#### Analysis Settings")
                st.caption("Times are in UTC. Select a start within seven days of the TLE epoch; duration is limited to six hours.")
                c1, c2, c3 = st.columns(3)
                start_date = c1.date_input("Start date (UTC)", key=start_date_key)
                start_clock = c2.time_input("Start time (UTC)", key=start_time_key)
                duration = c3.slider("Propagation duration (minutes)", 15, 360, step=15,
                                      key=duration_key)
                with st.expander("Advanced settings", expanded=False):
                    step = st.select_slider("Calculation interval (seconds)", options=[15, 30, 60, 120, 300, 600],
                                            key=step_key)
                    st.caption("Interval controls the time between calculated positions. Coordinates are calculated from the selected TLE.")
                submitted = st.button("▶  Run Analysis", type="primary", use_container_width=True,
                                      key="run_analysis")
                start = datetime.combine(start_date, start_clock, tzinfo=timezone.utc)
                current_run_identity = build_run_identity(selected_record, bundle.mode, start, duration, step)
                if submitted:
                    previous_run = state.pop("analysis_run", None)
                    if previous_run:
                        state["previous_analysis_run"] = previous_run
                    state["analysis_status"] = "calculating"
                    state["requested_run_id"] = current_run_identity["run_id"]
                    state.pop("analysis_error", None)
                    try:
                        validate_run_configuration(selected_record, start, duration, step)
                        with st.spinner("Calculating orbital positions…"):
                            points = propagate_ground_track(selected_record, start, duration, step)
                        if not points:
                            raise PropagationError("No valid positions were produced. Check the selected TLE and analysis time.")
                        required = ("time", "latitude", "longitude", "altitude_km")
                        if any(any(key not in point for key in required) for point in points):
                            raise PropagationError("The propagation output is missing required position fields.")
                        completed_run = {
                            "run_id": current_run_identity["run_id"],
                            "configuration_fingerprint": current_run_identity["run_id"],
                            "configuration": current_run_identity["configuration"],
                            "input_snapshot": {
                                "name": selected_record.name, "catalog_id": selected_record.catalog_id,
                                "line1": selected_record.line1, "line2": selected_record.line2,
                                "tle_sha256": current_run_identity["tle_sha256"],
                                "tle_epoch_utc": selected_record.epoch.isoformat(),
                                "source": selected_record.source,
                                "retrieved_at_utc": selected_record.retrieved_at.isoformat(),
                                "retrieval_status": selected_record.retrieval_status,
                            },
                            "catalog_id": selected_record.catalog_id, "name": selected_record.name,
                            "record": selected_record, "points": points, "start": start,
                            "end": start + timedelta(minutes=duration), "duration_minutes": duration,
                            "step_seconds": step, "requested_count": requested_point_count(duration, step),
                            "run_at": datetime.now(timezone.utc), "source_mode": bundle.mode,
                            "data_source": selected_record.source,
                            "retrieved_at": selected_record.retrieved_at,
                            "data_status": selected_record.retrieval_status,
                            "weather_sources": [
                                {"source": rows[0]["source"], "retrieved_at": rows[0]["retrieved_at"].isoformat(),
                                 "first_observation": min(row["time"] for row in rows).isoformat(),
                                 "last_observation": max(row["time"] for row in rows).isoformat()}
                                for rows in (bundle.kp, bundle.solar_flux) if rows
                            ],
                            "weather_row_counts": {"kp": len(bundle.kp), "solar_flux": len(bundle.solar_flux)},
                            "valid_count": len(points),
                            "failed_count": requested_point_count(duration, step) - len(points),
                            "diagnostics": {"skipped_positions": points[-1].get("skipped_positions", 0)},
                        }
                        if completed_run["run_id"] != current_run_identity["run_id"]:
                            raise RuntimeError("Completed output does not match the active analysis configuration.")
                        state["analysis_run"] = completed_run
                        state["analysis_status"] = "complete"
                    except (ValueError, RuntimeError) as exc:
                        state.pop("analysis_run", None)
                        state["analysis_status"] = "failed"
                        state["analysis_error"] = str(exc)

    stored_run = state.get("analysis_run")
    run = stored_run if (stored_run and current_run_identity and
                         stored_run.get("run_id") == current_run_identity["run_id"] and
                         state.get("requested_run_id") == current_run_identity["run_id"]) else None
    if stored_run and run is None:
        state["analysis_status"] = "outdated"
        st.info("Configuration changed — run analysis to update results.")
    elif run is None and state.get("analysis_status") == "failed":
        st.error(f"The latest analysis failed: {state.get('analysis_error', 'Check the selected data and settings.')}")
    elif run is None:
        st.caption("Ready to run.")

    with st.container(border=True):
        st.subheader("Current Analysis")
        if not run:
            st.info("Select a satellite, configure the analysis, and choose **Run Analysis** to view results here.")
        else:
            valid_count = run["valid_count"]
            failed_count = run["failed_count"]
            if valid_count == 0:
                st.warning("No valid propagation positions are available for this run.")
            metrics = st.columns(5)
            metrics[0].metric("SELECTED OBJECT", f"{run['name']} · NORAD {run['catalog_id']}")
            metrics[1].metric("VALID POSITIONS", valid_count, help="Positions successfully calculated by SGP4.")
            metrics[2].metric("FAILED POSITIONS", failed_count, help="Requested timestamps where SGP4 did not return a valid location.")
            metrics[3].metric("ACTUAL COVERAGE", _format_utc_range(
                run["points"][0]["time"], run["points"][-1]["time"]) if run["points"] else "Unavailable")
            metrics[4].metric("LATEST ALTITUDE", f"{run['points'][-1]['altitude_km']:.2f} km"
                              if run["points"] else "Unavailable",
                              help="Altitude at the latest valid propagated position.")
            if run["points"]:
                st.caption(f"Run {run['run_id'][:12]} · {run['data_source']} · {run['data_status']} · "
                           f"retrieved {run['retrieved_at']:%Y-%m-%d %H:%M:%S UTC} · "
                           f"TLE epoch {run['record'].epoch:%Y-%m-%d %H:%M:%S UTC}")
                st.markdown("#### Propagated Ground Track")
                st.caption("This SGP4 ground track is the calculated sub-satellite path, not an impact path or validated long-term reentry forecast. The 2D map tiles and Three.js / NASA Earth texture require internet access; the 3D globe retains a deterministic Earth fallback if its texture cannot load.")
                map_view, globe_view = st.tabs(["2D Map", "3D Globe"])
                with map_view:
                    try:
                        track_map = create_ground_track_map(run["points"], run["name"])
                        st_folium(track_map, height=600,
                                  key=f"track-{run['catalog_id']}-{run['run_id']}",
                                  returned_objects=[], use_container_width=True)
                    except Exception as exc:
                        st.error(f"Ground track could not be displayed: {exc}")
                with globe_view:
                    st.caption("Interactive Earth sphere. Drag to rotate, scroll to zoom, and hover over track positions for UTC, coordinates and SGP4 altitude. NASA Blue Marble provides the optional Earth texture; a visible graticule sphere remains if imagery is unavailable. This propagated ground track is not an impact path.")
                    try:
                        globe_html = create_three_globe_html(run)
                        st.components.v1.html(globe_html, height=620, scrolling=False)
                    except (ValueError, TypeError) as exc:
                        st.error(f"3D globe could not be prepared for this analysis run: {exc}")
                st.caption(f"{valid_count} valid positions were calculated from "
                           f"{run['points'][0]['time']:%Y-%m-%d %H:%M:%S UTC} through "
                           f"{run['points'][-1]['time']:%Y-%m-%d %H:%M:%S UTC}; latest valid altitude is "
                           f"{run['points'][-1]['altitude_km']:.2f} km.")
            if failed_count:
                st.caption(f"Data quality: {failed_count} requested timestamps failed; track gaps are retained.")
            try:
                import plotly.graph_objects as go
                chart_columns = st.columns(2)
                for chart_index, (title, key, y_label) in enumerate((
                    ("Orbital Altitude", "altitude_km", "Geodetic altitude (km)"),
                    ("Latitude Over Time", "latitude", "Latitude (degrees)"),
                )):
                    chart_times, chart_values = _break_aware_series(run["points"], key)
                    fig = go.Figure(go.Scatter(
                        x=chart_times, y=chart_values,
                        mode="lines+markers", connectgaps=False,
                        line={"color": "#38E1D1", "width": 2.2},
                        marker={"size": 4, "color": "#14B8A6"}, name=title,
                        customdata=_break_aware_customdata(run["points"]),
                        hovertemplate="UTC: %{x|%Y-%m-%d %H:%M:%S} UTC<br>Value: %{y:.3f}<br>"
                                      "Lat: %{customdata[0]:.3f}°<br>Lon: %{customdata[1]:.3f}°<br>"
                                      "Altitude: %{customdata[2]:.2f} km<extra></extra>"))
                    _style_figure(fig, title, "Time (UTC)", y_label, run["run_id"])
                    chart_columns[chart_index].plotly_chart(fig, use_container_width=True)
                longitude_times, longitude = _break_aware_series(run["points"], "longitude", True)
                fig = go.Figure(go.Scatter(x=longitude_times, y=longitude,
                    mode="lines+markers", connectgaps=False,
                    line={"color": "#38E1D1", "width": 2.2},
                    marker={"size": 4, "color": "#14B8A6"},
                    customdata=_break_aware_customdata(run["points"], split_antimeridian=True),
                    name="Longitude",
                    hovertemplate="UTC: %{x|%Y-%m-%d %H:%M:%S} UTC<br>"
                                  "Longitude: %{y:.3f}°<extra></extra>"))
                _style_figure(fig, "Longitude Over Time", "Time (UTC)",
                              "Longitude (degrees, −180 to 180)", run["run_id"])
                st.columns(2)[0].plotly_chart(fig, use_container_width=True)
            except ImportError:
                st.warning("Charts are unavailable in this environment; calculated positions remain in the table and CSV.")
            st.markdown("#### Position Data")
            st.caption("Coordinates are shown to five decimal places and altitude to three; the CSV preserves full calculated precision.")
            try:
                import pandas as pd
                frame = pd.DataFrame([{"Time (UTC)": p["time"].astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                    "Latitude (°)": round(p["latitude"], 5),
                    "Longitude (°)": round(p["longitude"], 5),
                    "Altitude (km)": round(p["altitude_km"], 3),
                    "SGP4 Status": "Valid", "Gap Before": p.get("break_before", False)}
                    for p in run["points"]])
                frame.insert(0, "analysis_run_id", run["run_id"])
                st.dataframe(frame, use_container_width=True, hide_index=True, height=420)
            except ImportError:
                table_rows = [{"analysis_run_id": run["run_id"], **point} for point in run["points"]]
                st.dataframe(table_rows, use_container_width=True, hide_index=True, height=420)
            slug = f"orbitguard_{run['catalog_id']}_{run['run_at']:%Y%m%dT%H%M%SZ}"
            st.markdown("#### Reports & Exports")
            st.caption("Downloads are bound to the active object, TLE, source and analysis configuration.")
            st.download_button("Download Track CSV", track_csv(run["points"], {
                "analysis_run_id": run["run_id"], "data_mode": run["source_mode"],
                "object_name": run["name"], "norad_id": run["catalog_id"],
                "data_source": run["data_source"], "retrieval_status": run["data_status"],
                "retrieved_at_utc": run["retrieved_at"].isoformat(),
                "tle_epoch_utc": run["record"].epoch.isoformat(),
                "analysis_start_utc": run["start"].isoformat(), "analysis_end_utc": run["end"].isoformat(),
                "duration_minutes": run["duration_minutes"], "step_seconds": run["step_seconds"],
            }),
                file_name=f"{slug}_ground_track.csv", mime="text/csv")
            report = {
                "application": "ORBITGUARD orbital analysis",
                "run_id": run["run_id"],
                "configuration": run["configuration"],
                "object": {"name": run["name"], "norad_id": run["catalog_id"]},
                "data_mode": run["source_mode"], "source": run["data_source"],
                "retrieval_status": run["data_status"],
                "retrieved_at_utc": run["retrieved_at"].isoformat(),
                "weather_sources": run["weather_sources"],
                "tle_epoch_utc": run["record"].epoch.isoformat(),
                "run_at_utc": run["run_at"].isoformat(),
                "settings": {"start_utc": run["start"].isoformat(), "end_utc": run["end"].isoformat(),
                             "duration_minutes": run["duration_minutes"], "step_seconds": run["step_seconds"]},
                "counts": {"requested": run["requested_count"], "valid": valid_count, "failed": failed_count,
                           "weather_kp_rows": run["weather_row_counts"]["kp"],
                           "weather_solar_flux_rows": run["weather_row_counts"]["solar_flux"]},
                "track_summary": {
                    "minimum_altitude_km": min(point["altitude_km"] for point in run["points"]),
                    "maximum_altitude_km": max(point["altitude_km"] for point in run["points"]),
                    "first_latitude_deg": run["points"][0]["latitude"],
                    "first_longitude_deg": run["points"][0]["longitude"],
                    "last_latitude_deg": run["points"][-1]["latitude"],
                    "last_longitude_deg": run["points"][-1]["longitude"],
                },
                "method": "SGP4 propagation in TEME; GMST rotation with UTC as UT1 approximation; WGS-84 geodetic coordinates.",
                "limitations": ["Ground track shows calculated satellite positions, not impact predictions.",
                                "SGP4 does not provide a validated long-term reentry forecast.",
                                "UTC approximates UT1 and polar motion is omitted."],
            }
            st.download_button("Download Analysis Report (JSON)",
                json.dumps(report, indent=2), file_name=f"{slug}_report.json", mime="application/json")

    tabs = st.tabs(["Decay Analysis", "Space Weather", "Validation", "Methodology"])

    with tabs[0]:
        st.subheader("TLE-derived perigee trend")
        if bundle is None or selected_record is None:
            st.info("Load a dataset and select an object to inspect its available TLE history.")
        else:
            history = [record for record in bundle.records if record.catalog_id == selected_record.catalog_id]
            result = analyze_tle_decay_trend(history)
            st.caption("This panel describes element-to-element perigee changes. It does not estimate atmospheric drag, lifetime, or a reentry date.")
            st.metric("TLE epochs for selected object", len(result["points"]))
            if not result["supportable"]:
                if result["duplicate_epochs"]:
                    st.warning(result["message"])
                else:
                    st.info(result["message"])
                    if bundle.mode in {"live", "bundled"}:
                        st.caption("Live and bundled snapshots provide one current TLE per object. Upload time-ordered TLE history for a descriptive trend.")
            else:
                st.info(result["message"])
                st.metric("Descriptive fitted slope", f"{result['slope_km_per_day']:+.3f} km/day")
                st.caption(f"Observed-window residual RMSE: {result['residual_rmse_km']:.2f} km. This is a fit diagnostic, not a forecast uncertainty.")
                if result["gaps"]:
                    st.warning(f"{len(result['gaps'])} irregular sampling gap(s) detected (>2× median interval).")
                if result["outliers"]:
                    st.warning(f"{len(result['outliers'])} possible trend residual outlier(s) flagged; none were removed.")
                try:
                    import plotly.graph_objects as go
                    fig = go.Figure()
                    fig.add_trace(go.Scatter(x=[p["time"] for p in result["points"]],
                        y=[p["perigee_altitude_km"] for p in result["points"]],
                        mode="markers", name="TLE-derived values", marker={"color": "#39d7c5", "size": 8}))
                    fig.add_trace(go.Scatter(x=[p["time"] for p in result["fit"]],
                        y=[p["perigee_altitude_km"] for p in result["fit"]],
                        mode="lines", name="Observed-window linear fit", line={"color": "#ffb45b"}))
                    _style_figure(fig, "TLE-derived perigee trend", "TLE epoch (UTC)",
                                  "Mean perigee altitude (km)")
                    st.plotly_chart(fig, use_container_width=True)
                except ImportError:
                    st.dataframe(result["points"], use_container_width=True, hide_index=True)

    with tabs[1]:
        st.subheader("Solar and geomagnetic context")
        if bundle is None:
            st.info("Load a data source to view available NOAA observations.")
        else:
            selected_run = run if run and run["source_mode"] == bundle.mode else None
            if selected_run:
                st.caption(f"Selected object's interval: {selected_run['start']:%Y-%m-%d %H:%M UTC} — {selected_run['end']:%Y-%m-%d %H:%M UTC}.")
            all_weather_times = [row["time"] for row in bundle.kp + bundle.solar_flux]
            if all_weather_times:
                date_cols = st.columns(2)
                weather_start = date_cols[0].date_input("Chart start date (UTC)", value=min(all_weather_times).date(),
                                                        key="weather_chart_start")
                weather_end = date_cols[1].date_input("Chart end date (UTC)", value=max(all_weather_times).date(),
                                                      key="weather_chart_end")
                if weather_start > weather_end:
                    st.error("Chart start date must be on or before the chart end date.")
                    filtered_kp, filtered_flux = [], []
                else:
                    filtered_kp = [row for row in bundle.kp if weather_start <= row["time"].date() <= weather_end]
                    filtered_flux = [row for row in bundle.solar_flux if weather_start <= row["time"].date() <= weather_end]
            else:
                filtered_kp, filtered_flux = [], []
            st.markdown("#### Planetary Kp")
            _plot_space_weather(filtered_kp, "kp", "NOAA planetary Kp index", "Kp (0–9)",
                                selected_run, 3)
            st.markdown("#### 10.7 cm solar radio flux (F10.7)")
            _plot_space_weather(filtered_flux, "flux_sfu", "NOAA 10.7 cm solar radio flux",
                                "Solar flux units (SFU)", selected_run, 24)
            st.caption("Space-weather indicators provide atmospheric context; they do not alone determine reentry timing.")

    with tabs[2]:
        st.subheader("Historical events and forecast validation")
        st.markdown("Import a normalized, attributed historical event CSV. Historical outcomes alone do not provide the forecast snapshots required to recreate predictions.")
        events_file = st.file_uploader("Historical event CSV", type=["csv"], key="historical_events")
        if events_file:
            try:
                state["historical_event_upload"] = {"name": events_file.name, "bytes": events_file.getvalue()}
                events, issues = validate_reentry_csv(events_file.getvalue())
                st.success(f"{len(events)} valid event row(s) from {events_file.name}; original upload remains in this session.")
                st.dataframe([{"object_name": event["object_name"], "norad_id": event["norad_id"],
                    "observed_reentry_utc": event["observed_reentry_utc"].isoformat(), "source": event["source"]}
                    for event in events], use_container_width=True, hide_index=True)
                if issues:
                    st.warning(f"{len(issues)} invalid/duplicate row(s): " + "; ".join(issues[:5]))
                st.download_button("Download original event CSV", events_file.getvalue(),
                                   file_name=events_file.name, mime="text/csv")
            except (ValueError, UnicodeDecodeError) as exc:
                st.error(f"Historical event import failed: {exc}")
        st.markdown("#### Eligible prediction-versus-observation pairs")
        st.caption("Required columns: object_id, predicted_at_utc, predicted_reentry_utc, observed_reentry_utc, source. A forecast must have been issued before the observed event.")
        pairs_file = st.file_uploader("Forecast / event-pair CSV", type=["csv"], key="prediction_pairs")
        if pairs_file:
            try:
                state["prediction_pairs_upload"] = {"name": pairs_file.name, "bytes": pairs_file.getvalue()}
                pair_rows = parse_prediction_pairs_csv(pairs_file.getvalue())
                evaluation = evaluate_prediction_pairs(pair_rows)
                if evaluation["eligible"]:
                    c1, c2, c3 = st.columns(3)
                    c1.metric("ELIGIBLE PAIRS", evaluation["sample_size"])
                    c2.metric("MAE", f"{evaluation['mae_hours']:.2f} h")
                    c3.metric("RMSE", f"{evaluation['rmse_hours']:.2f} h")
                    st.caption(f"Observed event period: {evaluation['evaluation_start']:%Y-%m-%d} — "
                               f"{evaluation['evaluation_end']:%Y-%m-%d} UTC · "
                               f"{evaluation['metric_definitions']['MAE']} {evaluation['notice']}")
                    if evaluation["rejected"]:
                        st.warning(f"{len(evaluation['rejected'])} row(s) excluded: {evaluation['rejected'][:5]}")
                    st.download_button("Download validation metrics JSON",
                        json.dumps(evaluation, indent=2, default=str),
                        file_name="orbitguard_validation_metrics.json", mime="application/json")
                    st.download_button("Download original forecast/event CSV", pairs_file.getvalue(),
                        file_name=pairs_file.name, mime="text/csv")
                else:
                    st.warning("Validation data insufficient — " + evaluation["reason"])
            except (ValueError, UnicodeDecodeError) as exc:
                st.error(f"Forecast-pair import failed: {exc}")
        else:
            st.info("Validation data insufficient. No historical forecast/event pairs are bundled; see data/sample/README.md for the documented schema.")

    with tabs[3]:
        st.subheader("Methodology")
        st.markdown("""
        **Data:** CelesTrak Potential Decays supplies candidate TLEs. NOAA SWPC planetary Kp and 10.7 cm solar flux provide space-weather context. Source, retrieval time, and TLE epoch are retained with results.

        **Propagation:** SGP4 propagates the selected TLE in TEME. Coordinates use GMST and a WGS-84 ellipsoid; UTC approximates UT1 and polar motion is omitted. The perigee trend is descriptive and uses only the observed TLE epoch window. Validation metrics use eligible uploaded forecast/event pairs issued before the observed event.
        """)
        st.markdown("""
        **Available:** TLE ingestion, SGP4 propagation, ground-track mapping, NOAA Kp and F10.7 visualizations when data are present, and provenance diagnostics.

        **Future work:** trained ML remaining-lifetime estimation, validated long-term reentry-window forecasting, calibrated impact probabilities/corridors, and historical forecast validation when eligible archived pairs are available.
        """)
        st.markdown("[CelesTrak GP data documentation](https://celestrak.org/NORAD/documentation/gp-data-formats.php) · "
                    "[NOAA Kp JSON](https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json) · "
                    "[NOAA 10.7 cm flux JSON](https://services.swpc.noaa.gov/products/10cm-flux-30-day.json)")


if __name__ == "__main__":
    main()
