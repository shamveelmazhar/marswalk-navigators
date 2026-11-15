"""Where we're working, and how we turn Mars latitude and longitude into map coordinates.

All the maps we download use the same simple projection: equirectangular on a
sphere the size of Mars. That means x is just the radius times the longitude in
radians, and y is the radius times the latitude in radians. Keeping everything
on that one grid lets us stack layers without any reprojecting.
"""
import math
from dataclasses import dataclass

MARS_RADIUS_M = 3_396_190.0


def lonlat_to_xy(lon_deg, lat_deg):
    """Convert east longitude and latitude (degrees) to map x and y (meters)."""
    return MARS_RADIUS_M * math.radians(lon_deg), MARS_RADIUS_M * math.radians(lat_deg)


def xy_to_lonlat(x, y):
    """Convert map x and y (meters) back to east longitude and latitude (degrees)."""
    return math.degrees(x / MARS_RADIUS_M), math.degrees(y / MARS_RADIUS_M)


@dataclass(frozen=True)
class Site:
    """An area we plan Marswalks in, with the data products that cover it."""

    name: str
    # Map bounds of the close-up area: (left, bottom, right, top) in meters.
    bounds: tuple
    # A wider box for coarse layers like the THEMIS infrared mosaics.
    wide_bounds: tuple
    hirise_dtm_url: str
    hirise_ortho_url: str
    themis_night_url: str
    themis_day_url: str
    # Curiosity's boxwork campaign, in sols (Mars days since landing).
    campaign_sols: tuple
    # The block of RAD radiation files that covers the campaign.
    rad_folder: str


_HIRISE = (
    "https://astrogeo-ard.s3-us-west-2.amazonaws.com/mars/mro/hirise/controlled/dtm/"
    "ESP_019698_1750_ESP_019988_1750/"
)
_THEMIS = "https://astrogeo-ard.s3.us-west-2.amazonaws.com/mars/mo/themis/controlled_mosaics/"

# Mount Sharp, Gale Crater: the boxwork ridges Curiosity explored in May to July 2025.
# The close-up box is 4 km wide and 6 km tall, centered near 4.80 S, 137.38 E.
GALE_BOXWORK = Site(
    name="gale-boxwork",
    bounds=(8_141_200.0, -287_500.0, 8_145_200.0, -281_500.0),
    wide_bounds=(8_131_200.0, -299_500.0, 8_155_200.0, -269_500.0),
    hirise_dtm_url=_HIRISE + "DTEEC_019698_1750_019988_1750_U01.tif",
    hirise_ortho_url=_HIRISE + "ESP_019698_1750_RED_C_01_ORTHO.tif",
    themis_night_url=_THEMIS + "mc23_aeolis_nir/mc23_aeolis_nir.tif",
    themis_day_url=_THEMIS + "mc23_aeolis_dir/mc23_aeolis_dir.tif",
    campaign_sols=(4530, 4600),
    rad_folder="https://pds-ppi.igpp.ucla.edu/data/MSL-M-RAD-3-RDR-V1.0/DATA/SOL_04489_04612/",
)
