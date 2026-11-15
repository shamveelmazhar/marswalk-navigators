"""Terrain maps built from an elevation grid: how steep and how bumpy the ground is.

These feed the path planner (as costs) and the FEA work (as worst-case load
cases), so they're kept as plain numpy functions that are easy to test.
"""
import numpy as np
from scipy import ndimage


def slope_degrees(elevation, cell_size_m, smooth_cells=1):
    """Slope of the ground in degrees at each cell.

    Missing elevation values (NaN) stay missing in the result. Set smooth_cells
    above 1 to average the elevation over a small window first, which gives the
    slope a person or rover actually feels instead of every small bump.
    """
    z = np.asarray(elevation, dtype="float64")
    missing = np.isnan(z)
    if smooth_cells > 1:
        filled = np.where(missing, np.nanmean(z), z)
        z = ndimage.uniform_filter(filled, smooth_cells)
    dz_dy, dz_dx = np.gradient(z, cell_size_m)
    slope = np.degrees(np.arctan(np.hypot(dz_dx, dz_dy)))
    slope[missing] = np.nan
    return slope


def roughness_m(elevation, window_cells=5):
    """How bumpy the ground is: the spread of heights (standard deviation) in a small window, in meters.

    A tilted but smooth surface still shows some spread, so treat this as a
    simple, fast proxy. High values point to ridges, ledges and rocks.
    """
    z = np.asarray(elevation, dtype="float64")
    missing = np.isnan(z)
    filled = np.where(missing, 0.0, z)
    valid = (~missing).astype("float64")
    count = ndimage.uniform_filter(valid, window_cells)
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = ndimage.uniform_filter(filled, window_cells) / count
        mean_sq = ndimage.uniform_filter(filled * filled, window_cells) / count
        rough = np.sqrt(np.clip(mean_sq - mean * mean, 0.0, None))
    rough[missing] = np.nan
    return rough


def slope_summary(slope):
    """A few numbers that describe how hard the terrain is to cross."""
    values = slope[~np.isnan(slope)]
    return {
        "median_deg": float(np.median(values)),
        "p90_deg": float(np.percentile(values, 90)),
        "share_over_15_deg": float((values > 15).mean()),
        "share_over_25_deg": float((values > 25).mean()),
    }
