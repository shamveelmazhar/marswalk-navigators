"""Tests for the Marswalk AI Route Assistant."""
import pytest
from marswalk.assistant import generate_mission_briefing, find_nearby_science_stops
from marswalk.budgets import compute_wheel_load_cases


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
        "solar_yield_wh": 170.0,
        "net_battery_balance_wh": -258.0,
    }
    load_cases = compute_wheel_load_cases(max_slope_deg=18.5, max_roughness_m=1.2)
    nearby_stops = [
        {"name": "Stop 1", "distance_to_route_m": 45.0, "elev_m": -3680.0, "sols": [4530, 4535], "photo_count": 120}
    ]

    briefing = generate_mission_briefing(route, walk_budget, drive_budget, load_cases, nearby_stops)

    assert briefing["is_go"] is True
    assert "GO FOR EVA" in briefing["status"]
    assert "briefing_markdown" in briefing
    assert "# 🔴 MARSWALK MISSION BRIEFING" in briefing["briefing_markdown"]
    assert "Life-Support" in briefing["briefing_markdown"]
    assert "Radiation" in briefing["briefing_markdown"]
    assert "Oxygen" in briefing["briefing_markdown"]
    assert "Stop 1" in briefing["briefing_markdown"]
    assert len(briefing["hazard_warnings"]) > 0
