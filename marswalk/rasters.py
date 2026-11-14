"""Download just the piece of a big Mars map that we need.

The USGS keeps HiRISE and THEMIS maps as cloud-optimized GeoTIFFs, so rasterio
can read a small window over HTTP without downloading the whole file.
"""
import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.transform import from_bounds as transform_from_bounds
from rasterio.windows import from_bounds as window_from_bounds


def clip_remote_raster(url, out_path, bounds, cell_size_m, resampling=Resampling.bilinear):
    """Cut the area inside `bounds` out of a remote GeoTIFF and save it at `cell_size_m` resolution.

    Returns the clipped array. Cells with no data keep the source file's nodata value.
    """
    left, bottom, right, top = bounds
    width = int(round((right - left) / cell_size_m))
    height = int(round((top - bottom) / cell_size_m))
    with rasterio.open("/vsicurl/" + url) as src:
        window = window_from_bounds(left, bottom, right, top, src.transform)
        nodata = src.nodata if src.nodata is not None else 0
        data = src.read(
            1,
            window=window,
            out_shape=(height, width),
            resampling=resampling,
            boundless=True,
            fill_value=nodata,
        )
        profile = {
            "driver": "GTiff",
            "width": width,
            "height": height,
            "count": 1,
            "dtype": data.dtype,
            "crs": src.crs,
            "transform": transform_from_bounds(left, bottom, right, top, width, height),
            "nodata": nodata,
            "compress": "deflate",
            "tiled": True,
        }
    with rasterio.open(out_path, "w", **profile) as dst:
        dst.write(data, 1)
    return data


def read_raster(path, nodata_to_nan=True):
    """Read a single-band GeoTIFF as float, with its profile. Nodata becomes NaN."""
    with rasterio.open(path) as src:
        data = src.read(1).astype("float64")
        profile = src.profile
        if nodata_to_nan and src.nodata is not None:
            # Some products store nodata as a huge negative float, so compare loosely.
            data[np.isclose(data, src.nodata) | (data < -1e30)] = np.nan
    return data, profile


def write_like(path, data, profile):
    """Save a float map on the same grid as an existing one."""
    profile = dict(profile, dtype="float32", nodata=np.nan, count=1)
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(data.astype("float32"), 1)
