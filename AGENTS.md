# ORBITGUARD — Agent Instructions

## Project

**Title:** ORBITGUARD — Predictive Modeling and Ground-Track Risk Mapping for Uncontrolled Satellite and Rocket-Body Reentry.

This project is an advanced academic prototype (Level 2) for live tracking data, solar and geomagnetic data, orbital propagation, an experimental decay estimator, ground-track mapping, uncertainty analysis, historical backtesting, and a Streamlit dashboard.

## Technology stack

- Python 3.11
- Streamlit
- NumPy, pandas, SciPy
- sgp4 and Skyfield
- Plotly, Folium, and streamlit-folium
- requests, python-dotenv, and pytest

## Working rules

1. Work incrementally. Inspect the existing repository and its instructions before changing files. Keep changes scoped to the requested task.
2. Use genuine, attributable data. Never fabricate orbital elements, historical events, predictions, or accuracy metrics. Cite sources and retain provenance.
3. Clearly distinguish SGP4 propagation, long-term orbital decay estimation, and validated reentry forecasting. An experimental estimate is not a validated forecast.
4. Handle coordinate frames, units, timestamps, time zones, and data uncertainty explicitly and correctly. Document conversions and assumptions.
5. Read API credentials from environment variables. Never commit `.env` files, credentials, tokens, or other secrets. Keep a safe `.env.example` free of real credentials when needed.
6. Support offline/sample mode and graceful handling of network errors, unavailable services, malformed responses, and stale data. Label sample data clearly.
7. Preserve source metadata, retrieval times, and TLE epochs alongside data. Do not silently discard provenance.
8. Prevent future-data leakage in historical backtesting. At each simulated prediction time, only use information that would have been available by then; document the evaluation protocol.
9. Do not present an orbital ground track as a predicted impact path. Label map layers and outputs so their meaning and time horizon are unambiguous.
10. Never claim that an uncertainty corridor is statistically calibrated unless calibration has been demonstrated with appropriate evidence. State uncertainty assumptions and limitations.
11. Write automated tests for implemented behavior and run the relevant tests before reporting completion. Report what was run and any failures; do not claim tests passed when they were not run.
12. Maintain a professional dark navy and teal aerospace dashboard. Favor readable contrast, clear labels, and accessible interaction.
13. Document scientific assumptions, data sources, setup, reproducibility, and limitations. Avoid overstating prototype capabilities.

## Repository workflow

- Follow existing repository conventions and any more specific applicable instructions.
- Before implementation, inspect the current files and determine whether a feature already exists.
- Prefer small, reviewable changes with clear scientific and data provenance.
- Do not add fabricated fallback values that could be mistaken for observations or validated results.

## Interactive workflow and bundled data

- Keep the Streamlit data mode explicit: bundled, live, or user-uploaded. Do not make external requests on ordinary reruns; retrieve live feeds on an explicit load/refresh action.
- The bundled snapshot must remain attributable through its manifest, source URLs, retrieval time, and provider format. Do not replace it with synthetic orbital or weather records.
- Preserve uploaded source labels and original files in the active session; do not write private uploads or credentials into the repository.
- Bind analysis outputs, exports, and provenance reports to the exact selected object and Run Analysis settings.
- Keep SGP4 ground tracks distinct from impact paths and long-term decay/reentry forecasting.
- Only compute validation metrics from attributed prediction/event pairs issued before the observed event. Outcomes without archived forecasts do not constitute a backtest.
- When TLE history is insufficient, show the insufficiency. Do not extrapolate an observed-window trend into a reentry date or represent fit residuals as calibrated prediction uncertainty.
