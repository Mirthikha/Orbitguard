"""Configuration for public data feeds and local caching."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = PROJECT_ROOT / "data" / "cache"
CELESTRAK_DECAYING_URL = "https://celestrak.org/NORAD/elements/gp.php"
NOAA_KP_URL = "https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json"
NOAA_SOLAR_FLUX_URL = "https://services.swpc.noaa.gov/products/10cm-flux-30-day.json"
HTTP_TIMEOUT_SECONDS = 12
TLE_CACHE_TTL_SECONDS = 2 * 60 * 60
WEATHER_CACHE_TTL_SECONDS = 3 * 60 * 60
SOLAR_FLUX_CACHE_TTL_SECONDS = 24 * 60 * 60

