# ORBITGUARD

**Predictive Modeling and Ground-Track Risk Mapping for Uncontrolled Satellite and Rocket-Body Reentry**

ORBITGUARD calculates satellite positions from TLEs and presents ground-track and space-weather views. Ground tracks represent calculated satellite positions, not impact predictions; validated long-term reentry forecasts are not provided.

## Current capabilities

- Select data from **Bundled sample**, **Live feeds**, or **Upload my data**. The selector is populated from the active TLE set.
- Run a user-configured SGP4 propagation with UTC start time, duration, and step; calculated results render directly below the run controls on the same page, including summary metrics, an interactive map, altitude/latitude/longitude charts, a scrollable results table, and a provenance-bearing downloadable CSV.
- Review NOAA SWPC planetary Kp and 10.7 cm solar radio flux, including observation coverage, retrieval time, source, and long gaps.
- Examine a descriptive TLE-derived mean-perigee trend only when at least three epochs for the selected object span at least one day.
- Import normalized historical event rows and forecast/event pairs. Metrics are computed only for eligible, attributed pairs issued before the observed event.
- Download a JSON analysis/provenance report and calculated track CSV.

Live CelesTrak/NOAA data are fetched only when the user loads or refreshes live feeds; ordinary dashboard reruns do not make external requests.

## Data modes

### Bundled sample

The application includes direct feed snapshots in data/sample/: a CelesTrak 3LE Potential Decays response, NOAA planetary Kp JSON, and NOAA 10.7 cm flux JSON. Their exact retrieval timestamp, endpoints, row counts, and formats are in the sample manifest; provenance and limitations are in data/sample/README.md. These are genuine sourced feed snapshots, not generated examples. They age over time, and the UI labels them bundled with their retrieval timestamps.

No authentic historical reentry observations or eligible archived forecast/event pairs are bundled. Header-only CSV templates are provided for the documented upload schemas.

### Live feeds

Select **Live feeds**, then press **Load / refresh live feeds**. CelesTrak Potential Decays is retrieved with a timeout, validated, cached locally for two hours, and uses a clearly labelled stale cache on network failure. The two-hour interval respects CelesTrak's documented GP update cadence; repeated button presses use the cache while it is fresh. NOAA planetary Kp is cached for three hours and solar radio flux for 24 hours. Source timestamps are retained. Feed/cache files are kept in the ignored data/cache/ directory.

Sources:

- [CelesTrak GP data documentation](https://celestrak.org/NORAD/documentation/gp-data-formats.php), SPECIAL=DECAYING, 3LE format.
- [CelesTrak usage policy](https://celestrak.org/usage-policy.php).
- [NOAA SWPC planetary Kp JSON](https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json).
- [NOAA SWPC 10.7 cm flux 30-day JSON](https://services.swpc.noaa.gov/products/10cm-flux-30-day.json).

Kp response rows are validated against time_tag, Kp, a_running, and station_count. Solar-flux rows are validated against time_tag and flux. Timestamps without explicit offsets are interpreted as UTC per the product convention; values retain the original provider source and retrieval time.

This milestone deliberately requests TLE/3LE because the propagator consumes TLEs. CelesTrak documents that legacy TLE catalog-number fields cannot represent newly assigned six-digit IDs; if such records enter this feed, the app will need a separately validated OMM-capable ingestion path.

### Uploads

Select **Upload my data** and load a TLE text file (2LE/3LE). Optional supported NOAA-shaped CSVs:

- Kp: time_tag,Kp,a_running,station_count
- Solar flux: time_tag,flux
- Historical events: object_name,norad_id,observed_reentry_utc,source
- Forecast/event pairs: object_id,predicted_at_utc,predicted_reentry_utc,observed_reentry_utc,source

Dates in CSV files must be ISO-8601 with an explicit timezone; UTC Z is recommended. The uploaded event schema is an ORBITGUARD normalized import schema, not a claim that it matches every CORDS export. Transform and attribute source data before import. User files are held in the active Streamlit session and are not written into the repository.

## Analysis limits and scientific interpretation

- SGP4 propagates a TLE in TEME. Coordinate conversion uses GMST and a WGS-84 ellipsoid; UTC approximates UT1 and polar motion is omitted. These map positions are illustrative ground-track coordinates.
- The ground track is the propagated sub-satellite path. SGP4 alone does not reliably predict long-term decay or reentry.
- App controls constrain the start to within seven days of the chosen TLE epoch, duration to six hours, and time steps to 15–600 seconds. Older TLEs may be substantially less predictive.
- The perigee chart derives mean perigee altitude from the TLE mean motion and eccentricity. Its linear fit covers only the observed element-epoch interval. It is not extrapolated to an impact/reentry date; fit residuals are not calibrated prediction uncertainty.
- NOAA solar and geomagnetic indicators provide context. They do not alone determine atmospheric density or reentry timing.
- A historical event record alone cannot recreate a historical forecast. Metric rows require explicit forecast issue time, forecasted reentry time, observed reentry time, object ID, and source; rows issued after the outcome are excluded. Uploaded source lineage is not independently authenticated.
- Missing, invalid, or insufficient data produce an explanation. No dummy observations or default metric values are inserted.

## Windows CMD setup

Open **Command Prompt** in the repository folder:

    py -3.11 -m venv .venv
    .venv\Scripts\activate.bat
    python -m pip install --upgrade pip
    python -m pip install -r requirements.txt

If Python 3.11 is not installed, install it first; the repository environment inspected during this implementation had Python 3.10.11 only.

## Run and test

    python -m unittest discover -s tests -v
    python -m pytest
    streamlit run app.py

## Manual browser verification checklist

After installing the requirements, launch `streamlit run app.py` and check:

1. **Bundled sample:** select an object, confirm the source/retrieval/TLE epoch details, and run an analysis without loading live data.
2. **Immediate results:** confirm metrics, the map, all three time-series plots, and the scrollable point table appear below the controls without opening another tab.
3. **Map details:** hover over path points and start/end markers; confirm the UTC time, coordinates, altitude, visible path, and calculated-ground-track label.
4. **Run binding:** select a different object and rerun; confirm the object, map, plots, table, and CSV all update to the new NORAD ID and coordinates.
5. **Failure states:** try an unsupported date offset or simulate unavailable data; confirm an explanatory error appears and no success state is shown for a failed run.
6. **Downloads and supporting tabs:** inspect the CSV provenance columns and JSON report; check that weather, decay, and validation panels retain their own data/source limitations.

This browser checklist has not been verified in the current development environment because Streamlit and the visualization dependencies are not installed there. The automated UI workflow uses mocked Streamlit components and does not claim browser-level verification.

Tests use deterministic published verification vectors and mocked HTTP responses; they do not require internet. The app's bundled mode works offline. The 2D interactive map uses OpenStreetMap standard raster tiles (`https://tile.openstreetmap.org/{z}/{x}/{y}.png`) with visible © OpenStreetMap contributors attribution. The 3D Globe uses Three.js 0.170.0 and the NASA Earth Observatory Blue Marble Next Generation topography texture. Three.js and the texture are loaded from public HTTPS endpoints by the browser and therefore require internet access. If the texture request fails, the visible opaque slate-blue Earth and deterministic latitude/longitude graticule remain; if Three.js/WebGL initialization fails, a CSS-rendered fallback Earth is shown. The globe binds to the exact current analysis fingerprint and uses that run's geodetic positions, splitting the path at propagation gaps and longitude wraps.

Earth texture source and credit: [NASA Blue Marble Next Generation — Base Topography](https://science.nasa.gov/earth/earth-observatory/blue-marble-next-generation/base-topography/) and [NASA Earth Observatory](https://science.nasa.gov/earth/earth-observatory/blue-marble-next-generation/). Three.js is loaded from jsDelivr using the official version-pinned module/addon paths; this does not require an API key. The 3D sphere maps geodetic latitude/longitude directly to a unit sphere for visualization; the calculated positions themselves are unchanged. The 3D view shows the same SGP4-propagated sub-satellite ground track as the 2D map. It is not an impact path, an orbital trajectory above Earth, a long-term decay estimate, or a validated reentry forecast.

## Project layout

- app.py — Streamlit multi-tab application
- src/data/ — live feeds, authentic sample loading, TLE/weather and history uploads
- src/orbit/ — SGP4, coordinate conversion and run helpers
- src/decay/ — TLE-derived descriptive trend; no lifetime predictor
- src/mapping/ — ground-track map; no impact corridor
- src/validation/ — user-supplied forecast/event-pair eligibility and timing metrics
- data/sample/ — attributed public snapshots and header-only CSV templates
- data/historical/ — reserved; no bundled event dataset
