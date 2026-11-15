"""Turn the Mount Sharp data folder into small files the website can load.

The raw rasters are 15 to 20 MB each, which is far too heavy for a browser.
This script reads them once and writes:

  web/assets/layers/*.webp   colored map layers (photo, terrain, slope, hazard, thermal)
  web/data/grid.bin          a coarse 20 m terrain grid the in-browser route preview uses
  web/data/site.json         bounds, headline numbers, science stops, radiation by sol
  web/data/traverse.json     Curiosity's real path through the area, simplified

Run it from the repository root after `python -m marswalk.build`:

    python web/tools/build_web_data.py            # reads data/gale-boxwork
    python web/tools/build_web_data.py --data /some/other/folder
"""

import argparse
import collections
import csv
import json
import math
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image
from rasterio.enums import Resampling

MARS_RADIUS_M = 3396190.0
HERE = Path(__file__).resolve().parent
WEB = HERE.parent

# Limits we use to sort the ground into "go", "caution" and "no-go".
# A suited astronaut is comfortable below about 15 degrees and should not walk
# anything steeper than about 25. Roughness is the bumpiness over a 10 m patch.
SLOPE_CAUTION, SLOPE_NOGO = 15.0, 25.0
ROUGH_CAUTION, ROUGH_NOGO = 1.0, 2.0


def to_lonlat(x, y):
    return math.degrees(x / MARS_RADIUS_M), math.degrees(y / MARS_RADIUS_M)


def bounds_latlon(b):
    west, south = to_lonlat(b.left, b.bottom)
    east, north = to_lonlat(b.right, b.top)
    return [[south, west], [north, east]]


def read(path, width=None, height=None, resampling=Resampling.average):
    if resampling == "max":
        return read_block_max(path, width, height)
    with rasterio.open(path) as src:
        shape = (height or src.height, width or src.width)
        a = src.read(1, out_shape=shape, resampling=resampling).astype("float32")
        nodata = src.nodata
        b = src.bounds
    bad = ~np.isfinite(a)
    if nodata is not None:
        if np.isfinite(nodata):
            bad |= np.isclose(a, nodata) | (a < -1e30)
    a[bad] = np.nan
    return a, b


def read_block_max(path, width, height):
    """Downsample by taking the worst (largest) value in each block, so a steep
    patch never disappears just because the map got coarser."""
    full, b = read(path)
    fy, fx = full.shape[0] // height, full.shape[1] // width
    blocks = full[: height * fy, : width * fx].reshape(height, fy, width, fx)
    with np.errstate(all="ignore"):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            return np.nanmax(blocks, axis=(1, 3)), b


def ramp(values, stops):
    """Map 0..1 values onto a list of (position, (r, g, b)) color stops."""
    v = np.clip(np.nan_to_num(values, nan=0.0), 0, 1)
    pos = np.array([s[0] for s in stops])
    out = np.zeros(v.shape + (3,), dtype="float32")
    for c in range(3):
        out[..., c] = np.interp(v, pos, [s[1][c] for s in stops])
    return out


def save_rgba(rgb, alpha, path, quality=80):
    img = np.dstack([np.clip(np.nan_to_num(rgb), 0, 255), np.clip(np.nan_to_num(alpha), 0, 255)]).astype("uint8")
    Image.fromarray(img, "RGBA").save(path, "WEBP", quality=quality, method=6)


def hillshade(elev, cell, az=315.0, alt=40.0):
    e = np.where(np.isnan(elev), np.nanmean(elev), elev)
    dy, dx = np.gradient(e, cell)
    slope = np.arctan(np.hypot(dx, dy))
    aspect = np.arctan2(-dx, dy)
    az, alt = math.radians(az), math.radians(alt)
    hs = np.sin(alt) * np.cos(slope) + np.cos(alt) * np.sin(slope) * np.cos(az - aspect)
    return np.clip(hs, 0, 1)


def build_layers(d, out):
    layers = {}

    # HiRISE photo, 1 m pixels down to 3 m so it stays light.
    photo, b = read(d / "ortho_hirise_1m.tif", 1334, 2000)
    lo, hi = np.nanpercentile(photo, [1, 99.5])
    g = np.clip((photo - lo) / (hi - lo), 0, 1) ** 0.9 * 255
    rgb = np.dstack([g * 1.0, g * 0.93, g * 0.86])  # a faint warm tint
    save_rgba(rgb, np.where(np.isnan(photo), 0, 255), out / "photo.webp", 72)
    layers["photo"] = bounds_latlon(b)

    # Terrain: hillshade blended with a height-colored ramp.
    elev, b = read(d / "elevation_hirise_2m.tif", 1000, 1500)
    hs = hillshade(elev, 4.0)
    lo, hi = np.nanpercentile(elev, [0.5, 99.5])
    t = (elev - lo) / (hi - lo)
    color = ramp(t, [(0, (60, 22, 12)), (0.35, (150, 62, 30)), (0.7, (214, 128, 72)), (1, (246, 214, 170))])
    shade = (0.35 + 0.75 * hs)[..., None]
    save_rgba(color * shade, np.where(np.isnan(elev), 0, 255), out / "terrain.webp", 78)
    layers["terrain"] = bounds_latlon(b)

    # Slope, one hue from transparent to deep red.
    slope, b = read(d / "slope_deg_10m.tif", 1000, 1500)
    s = np.clip(slope / 35.0, 0, 1)
    color = ramp(s, [(0, (255, 236, 200)), (0.43, (250, 176, 90)), (0.71, (231, 96, 40)), (1, (150, 20, 20))])
    alpha = np.where(np.isnan(slope), 0, 60 + 190 * s)
    save_rgba(color, alpha, out / "slope.webp")
    layers["slope"] = bounds_latlon(b)

    # Hazard: go / caution / no-go from slope and roughness together.
    rough, _ = read(d / "roughness_m_10m.tif", 1000, 1500, "max")
    slope_max, _ = read(d / "slope_deg_10m.tif", 1000, 1500, "max")
    cls = np.zeros(slope.shape, "uint8")
    cls[(slope_max >= SLOPE_CAUTION) | (rough >= ROUGH_CAUTION)] = 1
    cls[(slope_max >= SLOPE_NOGO) | (rough >= ROUGH_NOGO)] = 2
    palette = np.array([(46, 196, 140), (240, 180, 40), (226, 58, 52)], "float32")
    alpha = np.where(np.isnan(slope_max), 0, np.array([70, 150, 190])[cls])
    save_rgba(palette[cls], alpha, out / "hazard.webp")
    layers["hazard"] = bounds_latlon(b)
    valid = ~np.isnan(slope_max)
    hazard_share = [float((cls[valid] == k).mean()) for k in range(3)]

    # THEMIS night infrared, wider 24 x 30 km context.
    th, tb = read(d / "themis_night_ir_100m.tif")
    th[th == 0] = np.nan
    big = np.array(Image.fromarray(np.nan_to_num(th, nan=0).astype("uint8")).resize((960, 1200), Image.BICUBIC), "float32")
    mask = np.array(Image.fromarray((~np.isnan(th)).astype("uint8") * 255).resize((960, 1200), Image.NEAREST))
    lo, hi = np.percentile(big[mask > 0], [2, 99])
    v = (big - lo) / (hi - lo)
    color = ramp(v, [(0, (12, 8, 40)), (0.3, (90, 20, 110)), (0.6, (210, 70, 60)), (0.85, (250, 160, 40)), (1, (252, 240, 170))])
    save_rgba(color, np.where(mask > 0, 210, 0), out / "thermal.webp")
    layers["thermal"] = bounds_latlon(tb)

    return layers, hazard_share


def build_grid(d, out, cell=20):
    with rasterio.open(d / "elevation_hirise_2m.tif") as src:
        w, h, b = src.width * 2 // cell, src.height * 2 // cell, src.bounds
    elev, _ = read(d / "elevation_hirise_2m.tif", w, h)
    slope, _ = read(d / "slope_deg_10m.tif", w, h, "max")
    rough, _ = read(d / "roughness_m_10m.tif", w, h, "max")
    e = np.where(np.isnan(elev), -32768, np.round(elev)).astype("<i2")
    s = np.where(np.isnan(slope), 255, np.clip(np.round(slope), 0, 90)).astype("u1")
    r = np.where(np.isnan(rough), 255, np.clip(np.round(rough * 10), 0, 254)).astype("u1")
    with open(out / "grid.bin", "wb") as f:
        f.write(e.tobytes() + s.tobytes() + r.tobytes())
    return {"width": w, "height": h, "cell_m": cell, "bounds": bounds_latlon(b),
            "layout": "int16 elevation m (-32768 = no data), then uint8 slope deg (255 = no data), then uint8 roughness in 0.1 m (255 = no data); rows run north to south"}


def simplify(coords, tol):
    """Plain Douglas-Peucker on lon/lat pairs."""
    if len(coords) < 3:
        return coords
    a, b = np.array(coords[0][:2]), np.array(coords[-1][:2])
    ab = b - a
    n = np.hypot(*ab) or 1e-12
    dmax, idx = 0, 0
    for i in range(1, len(coords) - 1):
        p = np.array(coords[i][:2])
        dist = abs(ab[0] * (a[1] - p[1]) - ab[1] * (a[0] - p[0])) / n
        if dist > dmax:
            dmax, idx = dist, i
    if dmax > tol:
        return simplify(coords[: idx + 1], tol)[:-1] + simplify(coords[idx:], tol)
    return [coords[0], coords[-1]]


def build_traverse(d, out):
    feats = json.load(open(d / "curiosity_traverse.geojson"))["features"]
    pts = []
    for f in feats:
        g = f["geometry"]
        lines = [g["coordinates"]] if g["type"] == "LineString" else g["coordinates"]
        for line in lines:
            for p in line:
                if not pts or pts[-1][:2] != [round(p[1], 6), round(p[0], 6)]:
                    pts.append([round(p[1], 6), round(p[0], 6), round(p[2], 1)])
    flat = [[p[1], p[0], p[2]] for p in pts]
    simple = simplify(flat, 0.000004)
    path = [[p[1], p[0], p[2]] for p in simple]
    json.dump(path, open(out / "traverse.json", "w"), separators=(",", ":"))
    length = sum(f["properties"]["Length"] for f in feats)
    return length


def radiation(d):
    per_sol = collections.defaultdict(list)
    n = 0
    for row in csv.DictReader(open(d / "rad_dose_rate_sols_4489-4612.csv")):
        v = float(row["dose_rate_E_uGy_per_h"])
        n += 1
        if v > 0.5:  # drop the handful of empty or calibration readings
            per_sol[int(row["sol"])].append(v)
    sols = sorted(per_sol)
    series = [{"sol": s, "uGy_h": round(float(np.mean(per_sol[s])), 3), "n": len(per_sol[s])} for s in sols]
    allv = [v for s in sols for v in per_sol[s]]
    return series, n, float(np.mean(allv))


def science_stops(d, waypoints, dose_by_sol, count=8):
    rows = list(csv.DictReader(open(d / "raw_images_sols_4530-4600.csv")))
    groups = collections.OrderedDict()
    for r in rows:
        key = (round(float(r["rover_lat"]), 5), round(float(r["rover_lon"]), 5))
        groups.setdefault(key, []).append(r)
    def score(kv):
        names = [x["image_url"].rsplit("/", 1)[-1] for x in kv[1] if x["camera"].startswith("MAST")]
        return (-sum("E0" in n[-14:] for n in names), -len(names))

    ranked = sorted(groups.items(), key=score)
    picked, used_sols = [], set()
    for (lat, lon), imgs in ranked:
        sol = int(imgs[0]["sol"])
        if any(abs(sol - s) < 4 for s in used_sols):
            continue
        used_sols.add(sol)
        picked.append(((lat, lon), imgs))
        if len(picked) == count:
            break
    picked.sort(key=lambda kv: int(kv[1][0]["sol"]))

    stops = []
    for i, ((lat, lon), imgs) in enumerate(picked, 1):
        # Mastcam "E" products are already color-processed; "C" ones are raw
        # Bayer frames that look like a checkerboard, so they only fill gaps.
        mast = [x for x in imgs if x["camera"].startswith("MAST")]
        processed = [x for x in mast if "E0" in x["image_url"].rsplit("/", 1)[-1][-14:]]
        mast = processed + [x for x in mast if x not in processed and x["camera"] == "MAST_LEFT"]
        nav = [x for x in imgs if x["camera"].startswith("NAV")]
        pool = processed if len(processed) >= 4 else mast
        chosen = pool[:: max(1, len(pool) // 4)][:4]
        if len(chosen) < 4:
            chosen += [x for x in mast if x not in chosen][: 4 - len(chosen)]
        chosen += nav[:: max(1, len(nav) // 2)][:2]
        near = min(waypoints, key=lambda w: (w["lat"] - lat) ** 2 + (w["lon"] - lon) ** 2)
        sols = sorted({int(x["sol"]) for x in imgs})
        dose = [dose_by_sol[s] for s in sols if s in dose_by_sol]
        stops.append({
            "id": i,
            "name": f"Stop {i}",
            "lat": lat, "lon": lon,
            "elev_m": round(float(imgs[0]["rover_elev_m"]), 1),
            "sols": [sols[0], sols[-1]],
            "photo_count": len(imgs),
            "rover_tilt_deg": near["tilt"],
            "dose_uGy_h": round(float(np.mean(dose)), 2) if dose else None,
            "photos": [{"url": x["image_url"], "camera": x["camera"], "sol": int(x["sol"]), "taken": x["date_taken_utc"]} for x in chosen],
        })
    return stops, len(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data", default="data/gale-boxwork")
    args = ap.parse_args()
    d = Path(args.data)
    layers_dir = WEB / "assets" / "layers"
    data_dir = WEB / "data"
    layers_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)

    layers, hazard_share = build_layers(d, layers_dir)
    grid = build_grid(d, data_dir)
    traverse_m = build_traverse(d, data_dir)
    series, rad_n, mean_uGy_h = radiation(d)
    dose_by_sol = {s["sol"]: s["uGy_h"] for s in series}

    wps = [f["properties"] for f in json.load(open(d / "curiosity_waypoints.geojson"))["features"]]
    waypoints = [{"lat": w["lat"], "lon": w["lon"], "sol": w["sol"], "elev": w["elev_geoid"], "tilt": w["tilt"]} for w in wps]
    stops, photo_total = science_stops(d, waypoints, dose_by_sol)

    elev, _ = read(d / "elevation_hirise_2m.tif", 1000, 1500)
    slope, _ = read(d / "slope_deg_10m.tif", 1000, 1500)
    sv = slope[~np.isnan(slope)]
    lo, hi = np.nanpercentile(elev, [0.1, 99.9])

    sol_len_h = 24.66
    site = {
        "name": "Mount Sharp boxwork, Gale Crater",
        "center": [-4.80, 137.38],
        "layers": layers,
        "grid": grid,
        "limits": {"slope_caution": SLOPE_CAUTION, "slope_nogo": SLOPE_NOGO,
                   "rough_caution": ROUGH_CAUTION, "rough_nogo": ROUGH_NOGO},
        "stats": {
            "area_km2": 24,
            "relief_m": round(float(hi - lo)),
            "elev_min_m": round(float(lo)), "elev_max_m": round(float(hi)),
            "slope_median_deg": round(float(np.median(sv)), 1),
            "share_over_15": round(float((sv > 15).mean()), 3),
            "share_over_25": round(float((sv > 25).mean()), 3),
            "hazard_share": [round(x, 3) for x in hazard_share],
            "traverse_km": round(traverse_m / 1000, 2),
            "waypoints": len(waypoints),
            "max_rover_tilt_deg": max(w["tilt"] for w in waypoints),
            "photos": photo_total,
            "rad_readings": rad_n,
            "dose_uGy_h": round(mean_uGy_h, 2),
            "dose_mGy_sol": round(mean_uGy_h * sol_len_h / 1000, 3),
            "rad_sols": [series[0]["sol"], series[-1]["sol"]],
        },
        "radiation": series,
        "waypoints": waypoints,
        "stops": stops,
    }
    json.dump(site, open(data_dir / "site.json", "w"), separators=(",", ":"))
    print(json.dumps(site["stats"], indent=2))


if __name__ == "__main__":
    main()
