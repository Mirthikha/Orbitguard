"""Folium rendering of calculated SGP4 ground-track positions."""

from __future__ import annotations

import folium
from folium import Element

OSM_TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
OSM_ATTRIBUTION = (
    '&copy; <a href="https://www.openstreetmap.org/copyright">'
    'OpenStreetMap</a> contributors'
)
MAP_STYLE = """
<style>
.leaflet-container { background: #07111F; border-radius: 10px; }
.leaflet-control-zoom a, .leaflet-control-layers-toggle {
    background-color: #0D1B2A !important;
    color: #E8F1F8 !important;
    border-color: #22394D !important;
}
.leaflet-control-attribution {
    background: rgba(7, 17, 31, .9) !important;
    color: #9FB2C5 !important;
}
.leaflet-control-attribution a { color: #38E1D1 !important; }
</style>
"""


def _minimal_longitude_window(points: list[dict]) -> tuple[float, float, list[float]]:
    """Return an unwrapped minimal longitude interval for map display only.

    Geographic longitude is circular. Using min/max on normalized values makes
    a short track around ±180° appear almost 360° wide. Returned longitudes are
    equivalent map-display coordinates; point records and exported values are
    never changed.
    """
    values = sorted(float(point["longitude"]) % 360.0 for point in points)
    if len(values) == 1:
        west = east = values[0]
    else:
        gaps = [values[index + 1] - values[index] for index in range(len(values) - 1)]
        gaps.append(values[0] + 360.0 - values[-1])
        largest_gap = max(range(len(gaps)), key=gaps.__getitem__)
        if largest_gap == len(values) - 1:
            west, east = values[0], values[-1]
        else:
            west, east = values[largest_gap + 1], values[largest_gap] + 360.0

    display_longitudes = []
    for point in points:
        longitude = float(point["longitude"]) % 360.0
        while longitude < west:
            longitude += 360.0
        display_longitudes.append(longitude)
    return west, east, display_longitudes


def create_ground_track_map(points: list[dict], name: str = "Selected object") -> folium.Map:
    """Render propagated locations over standard OSM raster tiles.

    Tile requests happen in the user's browser and require internet access. If
    unavailable, the calculated vectors and markers still render on a navy map
    background. The OSM tile pane is intentionally not color-filtered so its
    labels, borders and geographic colors remain legible and unaltered.
    """
    if not points:
        raise ValueError("At least one propagated point is required.")

    west, east, display_longitudes = _minimal_longitude_window(points)
    south = min(float(point["latitude"]) for point in points)
    north = max(float(point["latitude"]) for point in points)
    center = [(south + north) / 2.0, (west + east) / 2.0]
    map_view = folium.Map(
        location=center,
        zoom_start=3,
        min_zoom=2,
        max_zoom=18,
        crs="EPSG3857",
        tiles=None,
        control_scale=True,
    )
    folium.TileLayer(
        tiles=OSM_TILE_URL,
        attr=OSM_ATTRIBUTION,
        name="OpenStreetMap",
        overlay=False,
        control=True,
        show=True,
        max_zoom=19,
    ).add_to(map_view)

    segments: list[list[list[float]]] = [[]]
    previous_lon = None
    for point, display_lon in zip(points, display_longitudes):
        original_lon = float(point["longitude"])
        if (point.get("break_before") or
                (previous_lon is not None and abs(original_lon - previous_lon) > 180)) and segments[-1]:
            segments.append([])
        segments[-1].append([float(point["latitude"]), display_lon])
        previous_lon = original_lon

    for segment in segments:
        if len(segment) >= 2:
            # A restrained dark casing keeps the cyan path visible over both
            # light OSM land and darker ocean tiles without recoloring data.
            folium.PolyLine(segment, color="#07111F", weight=7, opacity=0.78,
                            tooltip=f"{name} · SGP4 propagated ground track").add_to(map_view)
            folium.PolyLine(segment, color="#38E1D1", weight=3.5, opacity=0.98,
                            tooltip=f"{name} · SGP4 propagated ground track").add_to(map_view)

    for point, display_lon in zip(points, display_longitudes):
        details = (f"{name}<br>UTC: {point['time'].isoformat()}<br>"
                   f"Latitude: {point['latitude']:.5f}°<br>"
                   f"Longitude: {point['longitude']:.5f}°<br>"
                   f"Altitude: {point['altitude_km']:.3f} km")
        folium.CircleMarker(
            [point["latitude"], display_lon], radius=2.5,
            color="#0D1B2A", weight=2, fill=True, fill_color="#38E1D1",
            fill_opacity=0.95, tooltip=details,
        ).add_to(map_view)

    first, last = points[0], points[-1]
    folium.CircleMarker(
        [first["latitude"], display_longitudes[0]], radius=7,
        color="#F8FBFF", weight=2.5, fill=True, fill_color="#14B8A6",
        fill_opacity=1.0,
        tooltip=(f"START · {name}<br>UTC: {first['time'].isoformat()}<br>"
                 f"Lat: {first['latitude']:.5f}° · Lon: {first['longitude']:.5f}°<br>"
                 f"Altitude: {first['altitude_km']:.3f} km"),
    ).add_to(map_view)
    folium.CircleMarker(
        [last["latitude"], display_longitudes[-1]], radius=7,
        color="#7A4D00", weight=2, fill=True, fill_color="#FFBE55",
        fill_opacity=1.0,
        tooltip=(f"END · {name}<br>UTC: {last['time'].isoformat()}<br>"
                 f"Lat: {last['latitude']:.5f}° · Lon: {last['longitude']:.5f}°<br>"
                 f"Altitude: {last['altitude_km']:.3f} km"),
    ).add_to(map_view)

    if len(points) > 1:
        map_view.fit_bounds(
            [[south, west], [north, east]], padding=(32, 32), max_zoom=7,
        )
    map_view.get_root().html.add_child(Element(
        MAP_STYLE +
        '<div style="position:absolute;left:12px;bottom:12px;z-index:9999;'
        'background:rgba(7,17,31,.94);color:#E8F1F8;border:1px solid #22394D;'
        'border-radius:8px;padding:8px 11px;font:12px/1.5 sans-serif;'
        'box-shadow:0 4px 16px rgba(0,0,0,.22);pointer-events:none">'
        '<span style="color:#38E1D1">━━</span> Calculated SGP4 ground track '
        '<span style="color:#14B8A6">◉</span> Start '
        '<span style="color:#FFBE55">●</span> End</div>'
    ))
    folium.LayerControl(collapsed=True).add_to(map_view)
    return map_view
