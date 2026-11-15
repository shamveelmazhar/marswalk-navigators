"""Curiosity's real path, stops and photos, from NASA's public mission map and raw image site."""
import json

import requests

from .site import lonlat_to_xy

TRAVERSE_URL = "https://mars.nasa.gov/mmgis-maps/MSL/Layers/json/MSL_traverse.json"
WAYPOINTS_URL = "https://mars.nasa.gov/mmgis-maps/MSL/Layers/json/MSL_waypoints.json"
RAW_IMAGES_URL = "https://mars.nasa.gov/api/v1/raw_image_items/"


def _points(geometry):
    kind, coords = geometry["type"], geometry["coordinates"]
    if kind == "Point":
        return [coords]
    if kind == "LineString":
        return coords
    if kind == "MultiLineString":
        return [p for line in coords for p in line]
    return []


def inside(bounds, lon, lat):
    """True if a longitude and latitude fall inside map bounds (left, bottom, right, top)."""
    x, y = lonlat_to_xy(lon, lat)
    left, bottom, right, top = bounds
    return left <= x <= right and bottom <= y <= top


def clip_features(collection, bounds):
    """Keep only the GeoJSON features that touch the area."""
    kept = [
        f
        for f in collection["features"]
        if any(inside(bounds, p[0], p[1]) for p in _points(f["geometry"]))
    ]
    return dict(collection, features=kept)


def fetch_geojson(url, session=None):
    http = session or requests.Session()
    return json.loads(http.get(url, timeout=120).text)


def rover_position_by_sol(waypoints):
    """The rover's last known stop for each sol: {sol: (lat, lon, elevation_m)}."""
    positions = {}
    for f in waypoints["features"]:
        p = f["properties"]
        positions[p["sol"]] = (p["lat"], p["lon"], p["elev_geoid"])
    return positions


def position_on(sol, positions):
    """Where the rover was on a given sol (its most recent stop on or before that sol)."""
    earlier = [s for s in positions if s <= sol]
    return positions[max(earlier)] if earlier else (None, None, None)


def fetch_raw_images(first_sol, last_sol, cameras, session=None, max_pages=50):
    """List Curiosity's raw photos between two sols for the given cameras (full images, no thumbnails)."""
    http = session or requests.Session()
    images = []
    for camera in cameras:
        for page in range(max_pages):
            params = {
                "order": "sol asc",
                "per_page": 100,
                "page": page,
                "condition_1": "msl:mission",
                "condition_2": f"{first_sol}:sol:gte",
                "condition_3": f"{last_sol}:sol:lte",
                "search": camera,
            }
            data = http.get(RAW_IMAGES_URL, params=params, timeout=60).json()
            for item in data.get("items", []):
                if item.get("is_thumbnail") or item.get("sample_type") == "thumbnail":
                    continue
                images.append(
                    {
                        "sol": item["sol"],
                        "camera": item["instrument"],
                        "date_taken_utc": item.get("date_taken"),
                        "image_url": item["https_url"],
                    }
                )
            if not data.get("more"):
                break
    return images
