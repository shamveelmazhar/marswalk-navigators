import numpy as np
import pytest

from marswalk import terrain


def test_flat_ground_has_no_slope_or_roughness():
    flat = np.full((20, 20), -3500.0)
    assert np.allclose(terrain.slope_degrees(flat, 2.0), 0.0)
    assert np.allclose(terrain.roughness_m(flat), 0.0)


def test_ramp_gives_the_expected_angle():
    # Rises 1 m for every 2 m cell across x, which is atan(0.5), about 26.6 degrees.
    x = np.arange(30) * 1.0
    ramp = np.tile(x, (30, 1))
    slope = terrain.slope_degrees(ramp, 2.0)
    assert slope[15, 15] == pytest.approx(np.degrees(np.arctan(0.5)))


def test_smoothing_keeps_a_steady_ramp_unchanged_in_the_middle():
    x = np.arange(40) * 0.5
    ramp = np.tile(x, (40, 1))
    smooth = terrain.slope_degrees(ramp, 2.0, smooth_cells=5)
    assert smooth[20, 20] == pytest.approx(np.degrees(np.arctan(0.25)))


def test_missing_cells_stay_missing():
    z = np.zeros((10, 10))
    z[3, 4] = np.nan
    assert np.isnan(terrain.slope_degrees(z, 2.0)[3, 4])
    assert np.isnan(terrain.roughness_m(z)[3, 4])
    assert not np.isnan(terrain.roughness_m(z)[8, 8])


def test_a_single_rock_shows_up_as_rough():
    z = np.zeros((21, 21))
    z[10, 10] = 1.0
    rough = terrain.roughness_m(z, window_cells=5)
    assert rough[10, 10] > 0.1
    assert rough[0, 0] == pytest.approx(0.0)


def test_slope_summary_shares():
    slope = np.array([[5.0, 10.0], [20.0, 30.0]])
    summary = terrain.slope_summary(slope)
    assert summary["share_over_15_deg"] == 0.5
    assert summary["share_over_25_deg"] == 0.25
