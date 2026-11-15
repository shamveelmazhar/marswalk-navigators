"""Tests for the Marswalk route planning engine."""
import json
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


def test_flat_grid_gives_straight_path():
    """On flat, featureless terrain, A* should plan a direct straight path."""
    w, h = 40, 40
    elev = np.zeros((h, w), dtype=np.int16)
    slope = np.zeros((h, w), dtype=np.uint8)
    rough = np.zeros((h, w), dtype=np.uint8)

    grid = TerrainGrid(
        width=w,
        height=h,
        cell_m=20.0,
        bounds_latlon=(-5.0, 137.0, -4.0, 138.0),
        elev=elev,
        slope=slope,
        rough=rough,
    )

    start_lat, start_lon = grid.cell_to_coord(10, 10)
    end_lat, end_lon = grid.cell_to_coord(10, 30)

    result = grid.plan_path(start_lat, start_lon, end_lat, end_lon, agent="astronaut")
    assert result["ok"] is True
    # In a straight line along the same row, route distance matches direct distance (within 0.5%)
    assert abs(result["route_distance_m"] - result["direct_distance_m"]) / result["direct_distance_m"] < 0.005
    assert result["max_slope_deg"] == 0.0


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
    """A slope of 22 deg is passable for astronaut (limit 25 deg) but impassable for rover (limit 20 deg)."""
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


def test_diagonal_moves_cannot_slip_between_blocked_cells():
    """Verify corner cutting prevention: A path cannot step diagonally between two impassable cells."""
    w, h = 10, 10
    elev = np.zeros((h, w), dtype=np.int16)
    slope = np.zeros((h, w), dtype=np.uint8)
    rough = np.zeros((h, w), dtype=np.uint8)

    # Setup a diagonal pinch point:
    # Cell (4, 5) and (5, 4) are impassable cliffs (90 deg)
    # Cell (4, 4) is passable, cell (5, 5) is passable
    # Stepping from (4, 4) to (5, 5) diagonally would slip through the two cliffs.
    # Also block around them so the only hypothetical way through would be that diagonal slip.
    slope[4, 5] = 90
    slope[5, 4] = 90
    # Block the rest of the column 4 and 5 except our pinch
    slope[0:4, 5] = 90
    slope[6:10, 4] = 90
    slope[6:10, 5] = 90
    slope[0:4, 4] = 90

    grid = TerrainGrid(
        width=w,
        height=h,
        cell_m=20.0,
        bounds_latlon=(-5.0, 137.0, -4.0, 138.0),
        elev=elev,
        slope=slope,
        rough=rough,
    )

    start_lat, start_lon = grid.cell_to_coord(5, 2)
    end_lat, end_lon = grid.cell_to_coord(5, 8)

    result = grid.plan_path(start_lat, start_lon, end_lat, end_lon, agent="astronaut")
    # Must fail because slipping diagonally between (4, 5) and (5, 4) is blocked
    assert result["ok"] is False


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
    assert result["ok"] is False
    assert "No safe route found" in result["reason"] or "impassable terrain" in result["reason"]


def test_chaikin_path_smoothing():
    raw_coords = [[-4.80, 137.35], [-4.81, 137.35], [-4.81, 137.36], [-4.82, 137.36]]
    smoothed = smooth_path(raw_coords, rounds=2)
    assert len(smoothed) > len(raw_coords)
    assert smoothed[0] == raw_coords[0]
    assert smoothed[-1] == raw_coords[-1]


def test_real_gale_crater_pathfinding_and_limits():
    """Test A* planner using real Gale Crater HiRISE terrain grid and verify no cell exceeds limit."""
    grid = get_default_grid()
    assert grid.w == 200
    assert grid.h == 300

    start_lat = -4.79383
    start_lon = 137.38965
    end_lat = -4.79630
    end_lon = 137.38799

    for agent_key in ("astronaut", "rover"):
        profile = PROFILES[agent_key]
        result = grid.plan_path(start_lat, start_lon, end_lat, end_lon, agent=agent_key)
        assert result["ok"] is True
        assert result["route_distance_m"] >= result["direct_distance_m"]
        assert result["max_slope_deg"] <= profile.max_slope_deg
        assert result["max_roughness_m"] <= profile.max_roughness_m

        # Check every point along the final path
        for pt in result["path"]:
            r, c = grid.coord_to_cell(pt[0], pt[1])
            if grid.is_in_bounds(r, c) and grid.is_valid(r, c):
                assert grid.slope[r, c] <= profile.max_slope_deg


def test_curiosity_real_stops_pass_limits():
    """Curiosity's 8 real science stops in the boxwork ridges should all pass rover limits."""
    grid = get_default_grid()
    with open("web/data/site.json", "r", encoding="utf-8") as f:
        site_data = json.load(f)

    stops = site_data.get("stops", [])
    assert len(stops) >= 6

    rover_profile = PROFILES["rover"]
    astro_profile = PROFILES["astronaut"]

    for stop in stops:
        r, c = grid.coord_to_cell(stop["lat"], stop["lon"])
        assert grid.is_valid(r, c)
        assert grid.is_passable(r, c, rover_profile), f"{stop['name']} exceeded rover limits"
        assert grid.is_passable(r, c, astro_profile), f"{stop['name']} exceeded astronaut limits"


def test_missing_grid_raises_file_not_found():
    """get_default_grid or from_binary_file must fail loudly if grid is not found."""
    with pytest.raises(FileNotFoundError):
        TerrainGrid.from_binary_file("nonexistent_path_to_grid_12345.bin")
