# Data and scientific notes

ORBITGUARD has three data modes: a verified-attribution public feed snapshot under data/sample, explicitly loaded live CelesTrak/NOAA feeds, and user uploads. See the project [README](../README.md) and the [sample-data provenance note](../data/sample/README.md).

## Data contracts

- CelesTrak Potential Decays uses documented SPECIAL=DECAYING 3LE. The parser requires complete records, matching catalog IDs, valid TLE checksums, and parseable TLE epochs. Respect the [CelesTrak usage policy](https://celestrak.org/usage-policy.php); GP data are updated every two hours, so the live cache uses that interval and the UI does not refresh on ordinary reruns.
- NOAA SWPC Kp rows use time_tag, Kp, a_running, and station_count. The 10.7 cm solar-flux endpoint uses time_tag and flux. Parsers validate schema and numeric ranges, normalize timestamps to UTC, and retain retrieval time, source, and whether values were retrieved, cached, stale-cache, bundled, or uploaded.
- Historical event uploads use the ORBITGUARD normalized CSV schema rather than assuming that every CORDS export has identical fields. Forecast/event pairs are eligible only when issue time precedes observed event time; uploaded provenance is attributed but not independently authenticated.

## Coordinates and scientific interpretation

SGP4 positions are produced in TEME. Ground track conversion rotates by GMST, treats UTC as an approximation to UT1, omits polar motion, and reports WGS-84 geodetic latitude, longitude, and altitude. Antimeridian crossings and SGP4-invalid timestamps break map segments. Ground tracks are orbital sub-satellite paths, never impact corridors.

The decay panel derives mean perigee altitude from TLE mean motion and eccentricity and fits a linear trend only when at least three unique epochs span at least one day. It reports sampling gaps, duplicate epochs, potential residual outliers, and an in-window fit diagnostic. It does not extrapolate a reentry date or calculate calibrated predictive uncertainty. No independent atmospheric-drag estimator or historical backtest is implemented.
