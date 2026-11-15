import math

import pytest

from marswalk.loads import MARS_G, RoverSpec, skin_hand_calc, wheel_load_cases


def by_case(cases):
    return {c["case"]: c for c in cases}


def test_level_ground_shares_the_weight_evenly():
    rover = RoverSpec()
    lc = by_case(wheel_load_cases(0, 0, rover))
    assert lc["LC1"]["fz"] == pytest.approx(rover.mass_kg * MARS_G / rover.wheels)
    # With no slope and no ledge, climbing and side-slope cases match parking.
    assert lc["LC2"]["resultant"] == pytest.approx(lc["LC1"]["fz"])
    assert lc["LC4"]["fx"] == 0


def test_climbing_splits_the_weight_into_normal_and_traction():
    lc = by_case(wheel_load_cases(30, 0))
    w0 = lc["LC1"]["fz"]
    assert lc["LC2"]["fz"] == pytest.approx(w0 * math.cos(math.radians(30)))
    assert lc["LC2"]["fx"] == pytest.approx(w0 * math.sin(math.radians(30)))
    assert lc["LC2"]["resultant"] == pytest.approx(w0)


def test_side_slope_loads_the_downhill_wheel_more():
    lc = by_case(wheel_load_cases(20, 0))
    assert lc["LC3"]["fz"] > lc["LC2"]["fz"]
    assert lc["LC3"]["fy"] > 0


def test_ledge_height_is_capped_at_half_the_wheel_radius():
    tall = by_case(wheel_load_cases(0, 5.0))["LC4"]
    half = by_case(wheel_load_cases(0, 0.125))["LC4"]
    assert tall["fx"] == pytest.approx(half["fx"])
    # Rolling onto a step of half the radius needs sqrt(3) times the wheel load, before impact.
    rover = RoverSpec()
    w0 = rover.mass_kg * MARS_G / rover.wheels
    assert half["fx"] == pytest.approx(w0 * math.sqrt(3) * rover.dynamic_factor)


def test_exactly_one_worst_case():
    cases = wheel_load_cases(25, 1.0)
    assert sum(c["worst"] for c in cases) == 1
    assert max(cases, key=lambda c: c["resultant"])["worst"]


def test_hand_calc_gets_safer_with_a_thicker_skin():
    thin = skin_hand_calc(750, RoverSpec(skin_thickness_mm=0.75))
    thick = skin_hand_calc(750, RoverSpec(skin_thickness_mm=1.5))
    assert thick["plate_bending_mpa"] == pytest.approx(thin["plate_bending_mpa"] / 4)
    assert thick["safety_factor_shear"] == pytest.approx(2 * thin["safety_factor_shear"])
