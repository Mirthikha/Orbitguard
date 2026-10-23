# Bundled data and upload templates

Feed snapshots were retrieved on 2026-10-23 at the UTC timestamp in `manifest.json` from the source URLs listed there. The TLE file is a direct CelesTrak 3LE response for `SPECIAL=DECAYING` and contains 68 named object records. The NOAA JSON files are direct SWPC response bodies: planetary K-index rows use `time_tag`, `Kp`, `a_running`, and `station_count`; 10.7 cm radio-flux rows use `time_tag` and `flux`. NOAA timestamps without offsets are interpreted as UTC. Flux values are shown in solar flux units (SFU). CelesTrak requests compliance with its [usage policy](https://celestrak.org/usage-policy.php), including respecting the two-hour GP update cadence. No separate open-data license is asserted by this project; consult provider terms before redistribution.

These are authentic sourced feed snapshots, not synthetic records. Their epochs and observation times may be older than the current time; the UI labels data as bundled and shows the retrieval timestamp. A snapshot of the potential-decays feed does not constitute a reentry forecast.

No historical reentry observations or historical forecasts are bundled because no verified local source file or eligible forecast/event pairs were available during setup. `historical_reentry_template.csv` and `prediction_pairs_template.csv` contain headers only, not observations. The app offers upload and validation for these explicit schemas; uploading outcomes alone does not create backtest data.

Supported uploads:

- TLE: 2-line or 3-line text. Multiple epochs for one catalog ID can support a descriptive TLE-derived perigee trend.
- Kp CSV: `time_tag,Kp,a_running,station_count`.
- Solar flux CSV: `time_tag,flux`.
- Historical event CSV: `object_name,norad_id,observed_reentry_utc,source`.
- Forecast/event-pair CSV: `object_id,predicted_at_utc,predicted_reentry_utc,observed_reentry_utc,source`.

CSV timestamps must be ISO-8601 with an explicit timezone; UTC `Z` is recommended. The application retains uploaded values in the active session and parses them for analysis; it does not write uploads to the repository.
