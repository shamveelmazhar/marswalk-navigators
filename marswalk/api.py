"""FastAPI backend service for Marswalk Navigators.

Provides endpoints for map layers, site metadata, bounds, safety limits,
path planning routes, mission budgets, and AI mission briefings
for Gale Crater / Mount Sharp on Mars.
"""
import os
import json
import time
from typing import Optional, Literal, List, Dict, Any
from fastapi import FastAPI, Query, HTTPException, status, Body
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from marswalk.site import GALE_BOXWORK, xy_to_lonlat, lonlat_to_xy, MARS_RADIUS_M
from marswalk.planner import get_default_grid, PROFILES
from marswalk.budgets import (
    compute_walk_budget,
    compute_drive_budget,
    compute_wheel_load_cases,
    sample_path_profile,
    RAD_MEAN_DOSE_RATE_UGY_H,
)
from marswalk.assistant import (
    generate_mission_briefing,
    find_nearby_science_stops,
)

APP_START_TIME = time.time()

app = FastAPI(
    title="Marswalk Navigators API",
    description="Backend service for Marswalk planning, mission budgets, and AI briefings at Mount Sharp, Gale Crater (NASA Space Apps 2026).",
    version="1.2.0",
)

# Enable CORS for frontend dashboard and local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class CustomPathRequest(BaseModel):
    path: List[List[float]] = Field(..., description="Array of [latitude, longitude] waypoints")
    agent: Optional[Literal["astronaut", "rover"]] = Field("astronaut", description="Agent type: astronaut or rover")


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


def _calculate_budgets_for_path(path_coords: List[List[float]], max_slope: float, max_rough: float):
    """Generate profile and calculate walk, drive, and wheel budgets along coordinates."""
    grid = get_default_grid()

    def elev_func(lat, lon):
        r, c = grid.coord_to_cell(lat, lon)
        if not grid.is_in_bounds(r, c) or not grid.is_valid(r, c):
            return 0.0
        return grid.get_elevation_bilinear(lat, lon) or float(grid.elev[r, c])

    def slope_func(lat, lon):
        r, c = grid.coord_to_cell(lat, lon)
        return float(grid.slope[r, c]) if grid.is_in_bounds(r, c) else 0.0

    def rough_func(lat, lon):
        r, c = grid.coord_to_cell(lat, lon)
        return (float(grid.rough[r, c]) / 10.0) if grid.is_in_bounds(r, c) else 0.0

    profile = sample_path_profile(path_coords, elev_func, slope_func, rough_func, sampling_interval_m=10.0)
    walk_b = compute_walk_budget(profile)
    drive_b = compute_drive_budget(profile)
    load_cs = compute_wheel_load_cases(max_slope, max_rough)

    return {
        "walk": walk_b,
        "drive": drive_b,
        "wheel_load_cases": load_cs,
        "profile_points_count": len(profile),
    }


@app.get("/", tags=["Health"])
def root():
    """Root entry point with service metadata and documentation links."""
    return {
        "service": "marswalk-api",
        "name": "Marswalk Navigators API",
        "version": "1.2.0",
        "status": "online",
        "documentation": "/docs",
        "endpoints": {
            "health": "/health",
            "bounds": "/bounds",
            "layers": "/layers",
            "site": "/site",
            "limits": "/limits",
            "route": "/route",
            "budget": "/budget",
            "briefing": "/briefing",
        },
    }


@app.get("/health", tags=["Health"])
def health_check():
    """Service health, uptime, and terrain grid status."""
    uptime = time.time() - APP_START_TIME
    grid_loaded = False
    try:
        grid = get_default_grid()
        grid_loaded = grid is not None and grid.elev is not None
    except Exception:
        grid_loaded = False

    return {
        "status": "ok" if grid_loaded else "degraded",
        "service": "marswalk-api",
        "version": "1.2.0",
        "uptime_seconds": round(uptime, 2),
        "site": GALE_BOXWORK.name,
        "grid_loaded": grid_loaded,
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

    astro_profile = PROFILES["astronaut"]
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
            "slope_caution_deg": astro_profile.comfort_slope_deg,
            "slope_nogo_deg": astro_profile.max_slope_deg,
            "roughness_caution_m": astro_profile.caution_roughness_m,
            "roughness_nogo_m": astro_profile.max_roughness_m,
        },
    }

    if site_data:
        base_response["stats"] = site_data.get("stats", {})
        base_response["stops"] = site_data.get("stops", [])

    return base_response


@app.get("/limits", tags=["Robotics & Safety"])
def get_limits():
    """Traversability limits and mobility profile parameters for astronauts and rovers."""
    profiles_data = {}
    for key, p in PROFILES.items():
        entry = {
            "name": p.name,
            "max_slope_deg": p.max_slope_deg,
            "caution_slope_deg": p.comfort_slope_deg,
            "max_roughness_m": p.max_roughness_m,
            "caution_roughness_m": p.caution_roughness_m,
            "nominal_speed_kmh": p.nominal_speed_kmh,
            "max_speed_kmh": p.max_speed_kmh,
            "notes": p.notes,
        }
        if p.metabolic_rate_w is not None:
            entry["metabolic_rate_w"] = p.metabolic_rate_w
        if p.solar_budget_wh_per_sol is not None:
            entry["solar_budget_wh_per_sol"] = p.solar_budget_wh_per_sol
        profiles_data[key] = entry

    return {
        "site": GALE_BOXWORK.name,
        "profiles": profiles_data,
    }


@app.get("/route", tags=["Routing"])
def plan_route(
    start_lat: float = Query(..., description="Starting latitude in Martian degrees"),
    start_lon: float = Query(..., description="Starting longitude in Martian degrees"),
    end_lat: float = Query(..., description="Target latitude in Martian degrees"),
    end_lon: float = Query(..., description="Target longitude in Martian degrees"),
    agent: Literal["astronaut", "rover"] = Query("astronaut", description="Agent type: astronaut or rover"),
    include_budget: bool = Query(True, description="Whether to include mission life-support and rover budgets"),
):
    """Path planning query endpoint finding the safest path using A* over DEM, slope, and roughness."""
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

    grid = get_default_grid()
    result = grid.plan_path(
        start_lat=start_lat,
        start_lon=start_lon,
        end_lat=end_lat,
        end_lon=end_lon,
        agent=agent,
    )

    if not result.get("ok"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.get("reason", "The planner found no safe route."),
        )

    result["source"] = "api"

    if include_budget and "path" in result:
        budgets = _calculate_budgets_for_path(
            result["path"],
            result.get("max_slope_deg", 0.0),
            result.get("max_roughness_m", 0.0),
        )
        result["budget"] = budgets

    return result


@app.get("/budget", tags=["Mission Budgets"])
def get_mission_budget(
    start_lat: float = Query(..., description="Starting latitude in Martian degrees"),
    start_lon: float = Query(..., description="Starting longitude in Martian degrees"),
    end_lat: float = Query(..., description="Target latitude in Martian degrees"),
    end_lon: float = Query(..., description="Target longitude in Martian degrees"),
    agent: Literal["astronaut", "rover"] = Query("astronaut", description="Agent type: astronaut or rover"),
):
    """Calculate detailed life-support, energy, suit thermal, rover power, and radiation budgets for a route."""
    route_res = plan_route(
        start_lat=start_lat,
        start_lon=start_lon,
        end_lat=end_lat,
        end_lon=end_lon,
        agent=agent,
        include_budget=True,
    )
    return {
        "ok": True,
        "agent": agent,
        "route_summary": {
            "distance_m": route_res.get("route_distance_m"),
            "direct_distance_m": route_res.get("direct_distance_m"),
            "elevation_gain_m": route_res.get("elevation_gain_m"),
            "elevation_loss_m": route_res.get("elevation_loss_m"),
            "max_slope_deg": route_res.get("max_slope_deg"),
            "mean_slope_deg": route_res.get("mean_slope_deg"),
            "max_roughness_m": route_res.get("max_roughness_m"),
        },
        "budget": route_res.get("budget"),
    }


@app.post("/budget", tags=["Mission Budgets"])
def compute_custom_budget(body: CustomPathRequest):
    """Compute mission budgets for an arbitrary polyline route [[lat, lon], ...]."""
    if len(body.path) < 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least 2 coordinate waypoints are required to compute a mission budget.",
        )

    grid = get_default_grid()
    slopes = []
    roughnesses = []
    for lat, lon in body.path:
        r, c = grid.coord_to_cell(lat, lon)
        if grid.is_in_bounds(r, c) and grid.is_valid(r, c):
            slopes.append(float(grid.slope[r, c]))
            roughnesses.append(float(grid.rough[r, c]) / 10.0)

    max_slope = max(slopes) if slopes else 10.0
    max_rough = max(roughnesses) if roughnesses else 0.5

    budgets = _calculate_budgets_for_path(body.path, max_slope, max_rough)
    return {
        "ok": True,
        "agent": body.agent,
        "waypoints_count": len(body.path),
        "budget": budgets,
    }


@app.get("/briefing", tags=["AI Assistant"])
def get_mission_briefing(
    start_lat: float = Query(..., description="Starting latitude in Martian degrees"),
    start_lon: float = Query(..., description="Starting longitude in Martian degrees"),
    end_lat: float = Query(..., description="Target latitude in Martian degrees"),
    end_lon: float = Query(..., description="Target longitude in Martian degrees"),
    agent: Literal["astronaut", "rover"] = Query("astronaut", description="Agent type: astronaut or rover"),
):
    """Generate an astronaut-ready mission briefing with terrain hazards, PLSS budgets, and science stops."""
    route_res = plan_route(
        start_lat=start_lat,
        start_lon=start_lon,
        end_lat=end_lat,
        end_lon=end_lon,
        agent=agent,
        include_budget=True,
    )

    budget_data = route_res.get("budget", {})
    walk_b = budget_data.get("walk", {})
    drive_b = budget_data.get("drive", {})
    load_cs = budget_data.get("wheel_load_cases", [])

    site_data = _load_site_json() or {}
    all_stops = site_data.get("stops", [])
    nearby_stops = find_nearby_science_stops(route_res.get("path", []), all_stops, proximity_threshold_m=400.0)

    briefing = generate_mission_briefing(
        route=route_res,
        walk_budget=walk_b,
        drive_budget=drive_b,
        load_cases=load_cs,
        nearby_stops=nearby_stops,
    )

    briefing["route"] = {
        "direct_distance_m": route_res.get("direct_distance_m"),
        "route_distance_m": route_res.get("route_distance_m"),
        "path": route_res.get("path"),
    }
    return briefing
