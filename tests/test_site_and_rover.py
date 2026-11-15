import pytest

from marswalk import rover
from marswalk.site import GALE_BOXWORK, lonlat_to_xy, xy_to_lonlat


def test_coordinates_round_trip():
    x, y = lonlat_to_xy(137.383, -4.80)
    lon, lat = xy_to_lonlat(x, y)
    assert (lon, lat) == (pytest.approx(137.383), pytest.approx(-4.80))


def test_boxwork_stop_is_inside_the_site():
    # One of Curiosity's stops during the boxwork campaign (sol 4560).
    assert rover.inside(GALE_BOXWORK.bounds, 137.3835414, -4.79984723)
    # The landing site, 25 km away, is not.
    assert not rover.inside(GALE_BOXWORK.bounds, 137.441633, -4.589467)


def test_clip_keeps_lines_that_cross_into_the_area():
    collection = {
        "type": "FeatureCollection",
        "features": [
            {"geometry": {"type": "LineString", "coordinates": [[137.0, -4.0], [137.3835, -4.80]]}},
            {"geometry": {"type": "Point", "coordinates": [137.44, -4.59]}},
        ],
    }
    assert len(rover.clip_features(collection, GALE_BOXWORK.bounds)["features"]) == 1


def test_position_uses_the_latest_stop_before_that_sol():
    positions = {4530: (1, 1, 1), 4540: (2, 2, 2)}
    assert rover.position_on(4535, positions) == (1, 1, 1)
    assert rover.position_on(4540, positions) == (2, 2, 2)
    assert rover.position_on(4500, positions) == (None, None, None)
