"""Tests for the Marswalk route planning engine."""
import math
import pytest
import numpy as np

from marswalk.planner import (
    TerrainGrid,
    MobilityProfile,
    PROFILES,
    smooth_path,
    get_default_grid,
)


def test_grid_indexing_roundtrip():
    grid = TerrainGrid(width=100, height=100, cell_m=20.0, bounds_latlon=(-5.0, 137.0, -4.0, 138.0))
    lat, lon = -4.5, 137.5
    r, c = grid.coord_to_cell(lat, lon)
    assert 0 <= r < 100
    assert 0 <= c < 100
    lat_rt, lon_rt = grid.cell_to_coord(r, c)
    assert abs(lat - lat_rt) < grid.d_lat
    assert abs(lon - lon_rt) < grid.d_lon


def test_synthetic_cliff_obstacle_detour():
    """Create a flat terrain with an impassable ridge in the center and verify A* navigates around it."""
    w, h = 50, 50
    elev = np.zeros((h, w), dtype=np.int16)
    slope = np.zeros((h, w), dtype=np.uint8)
    rough = np.zeros((h, w), dtype=np.uint8)

    # Vertical wall down the middle (col 25) from row 0 to 40 (gap at row 41..49)
    # Wall slope = 30 deg (exceeds astronaut 25 deg limit)
    slope[0:40, 25] = 30

    grid = TerrainGrid(
        width=w,
        height=h,
        cell_m=20.0,
        bounds_latlon=(-5.0, 137.0, -4.0, 138.0),
        elev=elev,
        slope=slope,
        rough=rough,
    )

    # Start on left of wall, target on right of wall
    start_lat, start_lon = grid.cell_to_coord(20, 10)
    end_lat, end_lon = grid.cell_to_coord(20, 40)

    result = grid.plan_path(start_lat, start_lon, end_lat, end_lon, agent="astronaut")
    assert result["ok"] is True
    assert result["route_distance_m"] > result["direct_distance_m"]

    # Verify path avoided the steep wall cells
    for pt in result["path"]:
        r, c = grid.coord_to_cell(pt[0], pt[1])
        if 0 <= r < h and 0 <= c < w:
            assert slope[r, c] < 25.0


def test_rover_vs_astronaut_slope_limits():
    """A slope of 18 deg is passable for astronaut (limit 25 deg) but impassable for rover (limit 15/20 deg)."""
    w, h = 30, 30
    elev = np.zeros((h, w), dtype=np.int16)
    slope = np.zeros((h, w), dtype=np.uint8)
    rough = np.zeros((h, w), dtype=np.uint8)

    # Completely block middle with 22 deg slope
    slope[:, 15] = 22

    grid = TerrainGrid(
        width=w,
        height=h,
        cell_m=20.0,
        bounds_latlon=(-5.0, 137.0, -4.0, 138.0),
        elev=elev,
        slope=slope,
        rough=rough,
    )

    start_lat, start_lon = grid.cell_to_coord(15, 5)
    end_lat, end_lon = grid.cell_to_coord(15, 25)

    # Astronaut can climb 22 deg
    astronaut_result = grid.plan_path(start_lat, start_lon, end_lat, end_lon, agent="astronaut")
    assert astronaut_result["ok"] is True

    # Rover max slope is 20 deg, so 22 deg is impassable
    rover_result = grid.plan_path(start_lat, start_lon, end_lat, end_lon, agent="rover")
    assert rover_result["ok"] is False
    assert "No safe route found" in rover_result["reason"]


def test_chaikin_path_smoothing():
    raw_coords = [[-4.80, 137.35], [-4.81, 137.35], [-4.81, 137.36], [-4.82, 137.36]]
    smoothed = smooth_path(raw_coords, rounds=2)
    assert len(smoothed) > len(raw_coords)
    # Endpoints must remain preserved
    assert smoothed[0] == raw_coords[0]
    assert smoothed[-1] == raw_coords[-1]


def test_real_gale_crater_pathfinding():
    """Test A* planner using real Gale Crater HiRISE terrain grid."""
    grid = get_default_grid()
    assert grid.w == 200
    assert grid.h == 300

    # Two points in Gale Crater boxwork valley near Curiosity drive
    start_lat = -4.800
    start_lon = 137.380
    end_lat = -4.805
    end_lon = 137.385

    result = grid.plan_path(start_lat, start_lon, end_lat, end_lon, agent="astronaut")
    assert result["ok"] is True
    assert "path" in result
    assert len(result["path"]) >= 2
    assert "coordinates" in result
    # GeoJSON coordinates format is [lon, lat]
    assert result["coordinates"][0][0] == start_lon
    assert result["coordinates"][0][1] == start_lat
    assert result["coordinates"][-1][0] == end_lon
    assert result["coordinates"][-1][1] == end_lat

    assert result["route_distance_m"] >= result["direct_distance_m"]
    assert result["max_slope_deg"] <= 25.0
    assert "elevation_gain_m" in result
    assert "elevation_loss_m" in result


def test_completely_walled_target_fails_safely():
    """Ensure impossible routes return ok=False with helpful diagnostic."""
    w, h = 20, 20
    elev = np.zeros((h, w), dtype=np.int16)
    slope = np.zeros((h, w), dtype=np.uint8)
    rough = np.zeros((h, w), dtype=np.uint8)

    # Box in target cell (10, 10) completely with 90 deg cliffs
    slope[9:12, 9] = 90
    slope[9:12, 11] = 90
    slope[9, 9:12] = 90
    slope[11, 9:12] = 90

    grid = TerrainGrid(
        width=w,
        height=h,
        cell_m=20.0,
        bounds_latlon=(-5.0, 137.0, -4.0, 138.0),
        elev=elev,
        slope=slope,
        rough=rough,
    )

    start_lat, start_lon = grid.cell_to_coord(2, 2)
    end_lat, end_lon = grid.cell_to_coord(10, 10)

    result = grid.plan_path(start_lat, start_lon, end_lat, end_lon, agent="astronaut")
    # Because target is surrounded by 90 deg, it is either impassable or has no path
    assert result["ok"] is False
