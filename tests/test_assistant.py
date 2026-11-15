"""Tests for the Marswalk mission briefing."""
import pytest
from marswalk.assistant import generate_mission_briefing, find_nearby_science_stops
from marswalk.budgets import compute_wheel_load_cases
from marswalk.planner import PROFILES


def test_find_nearby_science_stops():
    # Route passing directly by Stop 1 coords (-4.79383, 137.38965)
    route_coords = [[-4.79380, 137.38960], [-4.79400, 137.38970]]
    stops = [
        {"name": "Stop 1", "lat": -4.79383, "lon": 137.38965, "elev_m": -3680.0, "sols": [4530, 4535]},
        {"name": "Distant Stop", "lat": -4.85000, "lon": 137.41000, "elev_m": -3400.0, "sols": [4600, 4610]},
    ]
    nearby = find_nearby_science_stops(route_coords, stops, proximity_threshold_m=100.0)
    assert len(nearby) == 1
    assert nearby[0]["name"] == "Stop 1"
    assert nearby[0]["distance_to_route_m"] < 50.0


def test_generate_mission_briefing_structure():
    route = {
        "agent": "astronaut",
        "route_distance_m": 850.0,
        "elevation_gain_m": 35.0,
        "elevation_loss_m": 10.0,
        "max_slope_deg": 18.5,
        "mean_slope_deg": 9.2,
        "max_roughness_m": 1.2,
        "path": [[-4.800, 137.380], [-4.805, 137.385]],
    }
    walk_budget = {
        "duration_hours": 1.45,
        "duration_minutes": 87.0,
        "metabolic_energy_kcal": 420.0,
        "metabolic_energy_kj": 1757.0,
        "average_metabolic_power_w": 336.0,
        "oxygen_consumed_liters": 87.4,
        "oxygen_consumed_kg": 0.125,
        "suit_thermal_heat_kj": 2860.0,
        "sublimator_water_kg": 0.51,
        "radiation_absorbed_dose_ugy": 9.57,
        "radiation_equivalent_dose_usv": 28.71,
        "eva_limit_utilization_pct": 18.1,
    }
    drive_budget = {
        "duration_hours": 2.36,
        "motion_energy_wh": 145.0,
        "hotel_energy_wh": 283.0,
        "total_energy_wh": 428.0,
        "solar_yield_wh": 106.2,
        "net_battery_balance_wh": -321.8,
    }
    load_cases = compute_wheel_load_cases(max_slope_deg=18.5, max_roughness_m=1.2)
    nearby_stops = [
        {"name": "Stop 1", "distance_to_route_m": 45.0, "elev_m": -3680.0, "sols": [4530, 4535], "photo_count": 120}
    ]

    briefing = generate_mission_briefing(route, walk_budget, drive_budget, load_cases, nearby_stops)

    assert briefing["is_go"] is True
    assert "GO FOR EVA" in briefing["status"]
    assert "briefing_markdown" in briefing
    assert briefing["briefing_markdown"].startswith("# Marswalk briefing")
    assert "What it costs the crew member" in briefing["briefing_markdown"]
    assert "Radiation" in briefing["briefing_markdown"]
    assert "30-day limit" in briefing["briefing_markdown"]
    assert "Oxygen" in briefing["briefing_markdown"]
    assert "Stop 1" in briefing["briefing_markdown"]
    assert len(briefing["hazard_warnings"]) > 0


def test_briefing_science_stops_title_and_blurb():
    """Verify that stops use title and blurb fields dynamically when provided."""
    route = {
        "agent": "astronaut",
        "route_distance_m": 500.0,
        "elevation_gain_m": 10.0,
        "elevation_loss_m": 5.0,
        "max_slope_deg": 10.0,
        "mean_slope_deg": 5.0,
        "max_roughness_m": 0.4,
    }
    walk_budget = {
        "duration_hours": 0.5,
        "duration_minutes": 30.0,
        "metabolic_energy_kcal": 150.0,
        "metabolic_energy_kj": 628.0,
        "average_metabolic_power_w": 348.0,
        "oxygen_consumed_liters": 31.2,
        "oxygen_consumed_kg": 0.045,
        "suit_thermal_heat_kj": 1000.0,
        "sublimator_water_kg": 0.18,
        "radiation_absorbed_dose_ugy": 3.3,
        "radiation_equivalent_dose_usv": 9.9,
        "eva_limit_utilization_pct": 6.25,
    }
    drive_budget = {
        "duration_hours": 1.0,
        "motion_energy_wh": 50.0,
        "hotel_energy_wh": 120.0,
        "total_energy_wh": 170.0,
        "solar_yield_wh": 45.0,
        "net_battery_balance_wh": -125.0,
    }
    load_cases = compute_wheel_load_cases(max_slope_deg=10.0, max_roughness_m=0.4)
    nearby_stops = [
        {
            "title": "Boxwork Ridge Spine",
            "blurb": "Prominent polygonal sulfate cementation ridge with sulfate veins.",
            "distance_to_route_m": 35.0,
            "elev_m": -3650.0,
        }
    ]

    briefing = generate_mission_briefing(route, walk_budget, drive_budget, load_cases, nearby_stops)
    assert "Boxwork Ridge Spine" in briefing["briefing_markdown"]
    assert "Prominent polygonal sulfate cementation ridge" in briefing["briefing_markdown"]
    assert briefing["nearby_science_stops"][0]["title"] == "Boxwork Ridge Spine"


def test_briefing_reads_limits_from_profiles():
    """Verify that rover vs astronaut slope limits are enforced from PROFILES."""
    # 22° slope: acceptable for astronaut (<= 25°), but unacceptable for rover (<= 20°)
    route_steep = {
        "agent": "rover",
        "route_distance_m": 500.0,
        "elevation_gain_m": 40.0,
        "elevation_loss_m": 0.0,
        "max_slope_deg": 22.0,  # Exceeds rover limit (20°)
        "mean_slope_deg": 12.0,
        "max_roughness_m": 0.5,
    }
    walk_b = {"duration_hours": 1.0, "eva_limit_utilization_pct": 12.5}
    drive_b = {"duration_hours": 1.5, "total_energy_wh": 200.0, "solar_yield_wh": 67.5, "net_battery_balance_wh": -132.5}
    load_cs = compute_wheel_load_cases(max_slope_deg=22.0, max_roughness_m=0.5)

    briefing_rover = generate_mission_briefing(route_steep, walk_b, drive_b, load_cs, [])
    assert briefing_rover["is_go"] is False
    assert "CAUTION" in briefing_rover["status"]

    # For astronaut, 22° is under 25° limit
    route_steep["agent"] = "astronaut"
    briefing_astronaut = generate_mission_briefing(route_steep, walk_b, drive_b, load_cs, [])
    assert briefing_astronaut["is_go"] is True
    assert "GO FOR EVA" in briefing_astronaut["status"]


def test_briefing_rover_note_replaces_rover_budget():
    route = {"agent": "astronaut", "route_distance_m": 500.0, "max_slope_deg": 10.0, "max_roughness_m": 0.3}
    walk_b = {"duration_hours": 0.5, "eva_limit_utilization_pct": 6.25}
    briefing = generate_mission_briefing(route, walk_b, {}, [], [], rover_note="The rover has no safe route.")
    md = briefing["briefing_markdown"]
    assert "The rover has no safe route." in md
    assert "Driving time" not in md
