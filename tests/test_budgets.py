"""Tests for the Marswalk mission budgets engine."""
import math
import pytest
from marswalk.budgets import (
    tobler_walk_speed_ms,
    pandolf_metabolic_power_w,
    compute_walk_budget,
    compute_drive_budget,
    compute_wheel_load_cases,
    sample_path_profile,
    ASTRONAUT_SPECS,
    ROVER_SPECS,
    MARS_G,
    RAD_MEAN_DOSE_RATE_UGY_H,
)


def test_tobler_speed_variation_with_grade():
    """Uphill walking should be significantly slower than flat walking."""
    v_flat = tobler_walk_speed_ms(0.0)
    v_uphill = tobler_walk_speed_ms(0.20)  # 20% incline
    assert v_flat > 0.5
    assert v_uphill < v_flat
    assert v_uphill > 0.1


def test_pandolf_metabolic_power():
    """Climbing increases metabolic burn in Watts."""
    p_flat = pandolf_metabolic_power_w(speed_ms=0.8, grade=0.0)
    p_uphill = pandolf_metabolic_power_w(speed_ms=0.8, grade=0.15)
    assert p_flat > 150.0   # Baseline suited walking wattage
    assert p_uphill > p_flat


def test_compute_walk_budget():
    # 500 meter synthetic path with a 20 meter rise
    pts = [
        {"d": 0.0, "elev": -3500.0, "slope": 5.0, "rough": 0.2},
        {"d": 250.0, "elev": -3490.0, "slope": 6.0, "rough": 0.3},
        {"d": 500.0, "elev": -3480.0, "slope": 5.0, "rough": 0.2},
    ]
    budget = compute_walk_budget(pts, dose_rate_ugy_h=RAD_MEAN_DOSE_RATE_UGY_H)

    assert budget["duration_hours"] > 0.0
    assert budget["metabolic_energy_kj"] > 0.0
    assert budget["metabolic_energy_kcal"] > 0.0
    assert budget["oxygen_consumed_liters"] > 0.0
    assert budget["oxygen_consumed_kg"] > 0.0
    assert budget["suit_thermal_heat_kj"] > 0.0
    assert budget["sublimator_water_kg"] > 0.0
    assert budget["radiation_absorbed_dose_ugy"] > 0.0
    assert budget["radiation_equivalent_dose_usv"] > budget["radiation_absorbed_dose_ugy"]
    assert 0.0 < budget["eva_limit_utilization_pct"] < 100.0


def test_compute_drive_budget():
    pts = [
        {"d": 0.0, "elev": -3500.0, "slope": 5.0, "rough": 0.2},
        {"d": 200.0, "elev": -3490.0, "slope": 6.0, "rough": 0.3},
        {"d": 400.0, "elev": -3480.0, "slope": 5.0, "rough": 0.2},
    ]
    budget = compute_drive_budget(pts, rover=ROVER_SPECS)

    assert budget["duration_hours"] > 0.0
    assert budget["motion_energy_wh"] > 0.0
    assert budget["hotel_energy_wh"] > 0.0
    # Each figure is rounded to 0.1 Wh on its own, so allow that much slack.
    assert budget["total_energy_wh"] == pytest.approx(budget["motion_energy_wh"] + budget["hotel_energy_wh"], abs=0.11)
    assert budget["solar_yield_wh"] > 0.0


def test_wheel_load_cases():
    cases = compute_wheel_load_cases(max_slope_deg=18.0, max_roughness_m=0.8, rover=ROVER_SPECS)
    assert len(cases) == 5
    case_ids = [c["id"] for c in cases]
    assert case_ids == ["LC1", "LC2", "LC3", "LC4", "LC5"]

    # Exactly one case marked as worst_case
    worst_cases = [c for c in cases if c.get("worst_case")]
    assert len(worst_cases) == 1

    # LC1 parked normal weight
    w_expected = (ROVER_SPECS.mass_kg * MARS_G) / ROVER_SPECS.wheels
    assert abs(cases[0]["fz_n"] - w_expected) < 1.0

    # LC5 edge puncture pressure exists
    assert cases[4]["pressure_mpa"] is not None
    assert cases[4]["pressure_mpa"] > 0.0


def test_sample_path_profile():
    path = [[-4.800, 137.380], [-4.802, 137.382]]
    profile = sample_path_profile(
        path,
        grid_elev_func=lambda lat, lon: -3500.0,
        grid_slope_func=lambda lat, lon: 8.0,
        grid_rough_func=lambda lat, lon: 0.4,
        sampling_interval_m=20.0,
    )
    assert len(profile) >= 2
    assert profile[0]["d"] == 0.0
    assert profile[-1]["d"] > 0.0
