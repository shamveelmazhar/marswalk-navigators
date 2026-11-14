"""FastAPI backend service for Marswalk Navigators.

Provides endpoints for map layers, site metadata, bounds, safety limits,
and path planning routes for Gale Crater / Mount Sharp on Mars.
"""
import os
import json
import time
from typing import Optional, Literal
from fastapi import FastAPI, Query, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from marswalk.site import GALE_BOXWORK, xy_to_lonlat, lonlat_to_xy, MARS_RADIUS_M

APP_START_TIME = time.time()

app = FastAPI(
    title="Marswalk Navigators API",
    description="Backend service for Marswalk planning at Mount Sharp, Gale Crater (NASA Space Apps 2026).",
    version="1.0.0",
)

# Enable CORS for frontend dashboard and local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _compute_bounds_latlon(bounds_m):
    """Convert (xmin, ymin, xmax, ymax) in meters to (min_lat, min_lon, max_lat, max_lon) in degrees."""
    left, bottom, right, top = bounds_m
    min_lon, min_lat = xy_to_lonlat(left, bottom)
    max_lon, max_lat = xy_to_lonlat(right, top)
    return {
        "min_lat": min_lat,
        "min_lon": min_lon,
        "max_lat": max_lat,
        "max_lon": max_lon,
    }


def _load_site_json():
    """Load pre-computed site summary if available in web/data/site.json."""
    candidates = [
        os.path.join(os.path.dirname(__file__), "..", "web", "data", "site.json"),
        os.path.join("web", "data", "site.json"),
        os.path.join("data", "site.json"),
    ]
    for path in candidates:
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
    return None


@app.get("/", tags=["Health"])
def root():
    """Root entry point with service metadata and documentation links."""
    return {
        "service": "marswalk-api",
        "name": "Marswalk Navigators API",
        "version": "1.0.0",
        "status": "online",
        "documentation": "/docs",
        "endpoints": {
            "health": "/health",
            "bounds": "/bounds",
            "layers": "/layers",
            "site": "/site",
            "limits": "/limits",
            "route": "/route",
        },
    }


@app.get("/health", tags=["Health"])
def health_check():
    """Service health and uptime status."""
    uptime = time.time() - APP_START_TIME
    return {
        "status": "ok",
        "service": "marswalk-api",
        "version": "1.0.0",
        "uptime_seconds": round(uptime, 2),
        "site": GALE_BOXWORK.name,
    }


@app.get("/bounds", tags=["Map"])
def get_bounds():
    """Site spatial boundaries in both Martian projected meters and geographic degrees."""
    close_bounds_deg = _compute_bounds_latlon(GALE_BOXWORK.bounds)
    wide_bounds_deg = _compute_bounds_latlon(GALE_BOXWORK.wide_bounds)
    center_lon = (close_bounds_deg["min_lon"] + close_bounds_deg["max_lon"]) / 2.0
    center_lat = (close_bounds_deg["min_lat"] + close_bounds_deg["max_lat"]) / 2.0

    return {
        "site": GALE_BOXWORK.name,
        "name": "Mount Sharp boxwork, Gale Crater",
        "mars_radius_m": MARS_RADIUS_M,
        "center": {
            "lat": round(center_lat, 5),
            "lon": round(center_lon, 5),
        },
        "bounds_meters": {
            "left": GALE_BOXWORK.bounds[0],
            "bottom": GALE_BOXWORK.bounds[1],
            "right": GALE_BOXWORK.bounds[2],
            "top": GALE_BOXWORK.bounds[3],
        },
        "bounds_latlon": close_bounds_deg,
        "wide_bounds_meters": {
            "left": GALE_BOXWORK.wide_bounds[0],
            "bottom": GALE_BOXWORK.wide_bounds[1],
            "right": GALE_BOXWORK.wide_bounds[2],
            "top": GALE_BOXWORK.wide_bounds[3],
        },
        "wide_bounds_latlon": wide_bounds_deg,
    }


@app.get("/layers", tags=["Map"])
def get_layers():
    """Metadata for all map layers available for Gale Crater / Mount Sharp."""
    bounds = _compute_bounds_latlon(GALE_BOXWORK.bounds)
    wide_bounds = _compute_bounds_latlon(GALE_BOXWORK.wide_bounds)

    layers = [
        {
            "id": "photo",
            "name": "HiRISE Orthophoto",
            "description": "High-resolution visible imagery (1 m/pixel) from Mars Reconnaissance Orbiter HiRISE camera.",
            "resolution_m": 1.0,
            "bounds": [[bounds["min_lat"], bounds["min_lon"]], [bounds["max_lat"], bounds["max_lon"]]],
            "format": "GeoTIFF / WebP",
            "source": GALE_BOXWORK.hirise_ortho_url,
            "product_id": "ESP_019698_1750_RED_C_01_ORTHO",
        },
        {
            "id": "terrain",
            "name": "HiRISE Elevation (DEM)",
            "description": "Digital Elevation Model (2 m/pixel) capturing steep gullies and boxwork ridges.",
            "resolution_m": 2.0,
            "bounds": [[bounds["min_lat"], bounds["min_lon"]], [bounds["max_lat"], bounds["max_lon"]]],
            "format": "GeoTIFF / WebP",
            "source": GALE_BOXWORK.hirise_dtm_url,
            "product_id": "DTEEC_019698_1750_019988_1750_U01",
        },
        {
            "id": "slope",
            "name": "Terrain Slope",
            "description": "Ground gradient computed from elevation DEM; identifies steep non-traversable ascents.",
            "resolution_m": 2.0,
            "bounds": [[bounds["min_lat"], bounds["min_lon"]], [bounds["max_lat"], bounds["max_lon"]]],
            "unit": "degrees",
            "format": "GeoTIFF / WebP",
        },
        {
            "id": "hazard",
            "name": "Hazard & Roughness Index",
            "description": "Surface roughness and obstacle index combining slope gradient and local height standard deviation.",
            "resolution_m": 2.0,
            "bounds": [[bounds["min_lat"], bounds["min_lon"]], [bounds["max_lat"], bounds["max_lon"]]],
            "format": "GeoTIFF / WebP",
        },
        {
            "id": "thermal",
            "name": "THEMIS Nighttime Infrared",
            "description": "Nighttime thermal infrared mosaic from Mars Odyssey THEMIS (100 m/pixel) indicating thermal inertia (exposed bedrock vs sand).",
            "resolution_m": 100.0,
            "bounds": [[wide_bounds["min_lat"], wide_bounds["min_lon"]], [wide_bounds["max_lat"], wide_bounds["max_lon"]]],
            "format": "GeoTIFF / WebP",
            "source": GALE_BOXWORK.themis_night_url,
        },
        {
            "id": "radiation",
            "name": "Curiosity RAD Surface Dose Rate",
            "description": "Real in-situ radiation dose rate measurements recorded by MSL RAD instrument during the boxwork campaign.",
            "unit": "µGy/h",
            "campaign_sols": list(GALE_BOXWORK.campaign_sols),
            "source": GALE_BOXWORK.rad_folder,
        },
        {
            "id": "traverse",
            "name": "Curiosity Actual Traverse",
            "description": "Ground-truth path driven by NASA's Curiosity rover with verified stops and tilt angles.",
            "format": "GeoJSON",
        },
    ]

    return {
        "site": GALE_BOXWORK.name,
        "count": len(layers),
        "layers": layers,
    }


@app.get("/site", tags=["Map"])
def get_site():
    """Comprehensive site metadata, terrain grid specifications, stats, and science stops."""
    bounds = _compute_bounds_latlon(GALE_BOXWORK.bounds)
    site_data = _load_site_json()

    base_response = {
        "id": GALE_BOXWORK.name,
        "name": "Mount Sharp boxwork, Gale Crater",
        "description": "Boxwork ridges formed by ancient groundwater minerals on Mount Sharp, explored by Curiosity.",
        "center": [-4.80, 137.38],
        "campaign_sols": list(GALE_BOXWORK.campaign_sols),
        "bounds_latlon": bounds,
        "grid": {
            "width": 200,
            "height": 300,
            "cell_size_m": 20.0,
            "bounds": [[bounds["min_lat"], bounds["min_lon"]], [bounds["max_lat"], bounds["max_lon"]]],
        },
        "limits": {
            "slope_caution_deg": 15.0,
            "slope_nogo_deg": 25.0,
            "roughness_caution_m": 1.0,
            "roughness_nogo_m": 2.0,
        },
    }

    if site_data:
        base_response["stats"] = site_data.get("stats", {})
        base_response["stops"] = site_data.get("stops", [])

    return base_response


@app.get("/limits", tags=["Robotics & Safety"])
def get_limits():
    """Traversability limits and mobility profile parameters for astronauts and rovers."""
    return {
        "site": GALE_BOXWORK.name,
        "profiles": {
            "astronaut": {
                "name": "Astronaut (EVA On Foot)",
                "max_slope_deg": 25.0,
                "caution_slope_deg": 15.0,
                "max_roughness_m": 2.0,
                "caution_roughness_m": 1.0,
                "nominal_speed_kmh": 3.6,
                "max_speed_kmh": 4.5,
                "metabolic_rate_w": 300.0,
                "notes": "Higher slope agility than wheeled rover, but strictly limited by life-support EVA duration and cumulative radiation dose.",
            },
            "rover": {
                "name": "Support Rover (Wheeled)",
                "max_slope_deg": 15.0,
                "caution_slope_deg": 10.0,
                "max_roughness_m": 1.0,
                "caution_roughness_m": 0.5,
                "nominal_speed_kmh": 0.15,
                "max_speed_kmh": 0.20,
                "solar_budget_wh_per_sol": 900.0,
                "notes": "Wheel slip on steep slopes and wheel wear from sharp bedrock ridges (Gale Crater boxwork) require stricter slope and roughness ceilings.",
            },
        },
    }


@app.get("/route", tags=["Routing"])
def plan_route(
    start_lat: float = Query(..., description="Starting latitude in Martian degrees"),
    start_lon: float = Query(..., description="Starting longitude in Martian degrees"),
    end_lat: float = Query(..., description="Target latitude in Martian degrees"),
    end_lon: float = Query(..., description="Target longitude in Martian degrees"),
    agent: Literal["astronaut", "rover"] = Query("astronaut", description="Agent type: astronaut or rover"),
):
    """Path planning query endpoint.

    Validates start and end coordinates within Mount Sharp boxwork boundaries.
    Full A* / Dijkstra raster pathfinding engine runs under the route planner module.
    """
    bounds = _compute_bounds_latlon(GALE_BOXWORK.bounds)

    # Validate start point
    if not (bounds["min_lat"] <= start_lat <= bounds["max_lat"] and bounds["min_lon"] <= start_lon <= bounds["max_lon"]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Start point [{start_lat}, {start_lon}] is outside Gale Crater boxwork bounds.",
        )

    # Validate destination point
    if not (bounds["min_lat"] <= end_lat <= bounds["max_lat"] and bounds["min_lon"] <= end_lon <= bounds["max_lon"]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"End point [{end_lat}, {end_lon}] is outside Gale Crater boxwork bounds.",
        )

    # Convert coordinates to Martian projected meters for Euclidean distance
    sx, sy = lonlat_to_xy(start_lon, start_lat)
    ex, ey = lonlat_to_xy(end_lon, end_lat)
    direct_dist_m = ((ex - sx) ** 2 + (ey - sy) ** 2) ** 0.5

    # Linear interpolation baseline path (5 waypoints) as fallback/precursor
    steps = 5
    path = []
    for i in range(steps + 1):
        t = i / steps
        lat = start_lat + t * (end_lat - start_lat)
        lon = start_lon + t * (end_lon - start_lon)
        path.append([round(lat, 6), round(lon, 6)])

    return {
        "status": "ok",
        "agent": agent,
        "direct_distance_m": round(direct_dist_m, 1),
        "waypoints_count": len(path),
        "path": path,
        "type": "LineString",
        "coordinates": [[p[1], p[0]] for p in path],  # GeoJSON [lon, lat] format
    }
