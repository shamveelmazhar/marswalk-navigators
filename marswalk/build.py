"""Build the starting dataset for a site: terrain, imagery, infrared, radiation and the rover's path.

Run it from the repo root:

    python -m marswalk.build --out data/gale-boxwork

It takes a few minutes, mostly downloading. Everything lands in the output
folder, on one shared map grid, ready for the path planner.
"""
import argparse
import concurrent.futures
import csv
import json
import os

import requests
from rasterio.enums import Resampling

from . import radiation, rover, terrain
from .rasters import clip_remote_raster, read_raster, write_like
from .site import GALE_BOXWORK

SITES = {GALE_BOXWORK.name: GALE_BOXWORK}


def build_terrain(site, out):
    print("Downloading the HiRISE elevation map and photo...")
    clip_remote_raster(site.hirise_dtm_url, f"{out}/elevation_hirise_2m.tif", site.bounds, 2.0)
    clip_remote_raster(
        site.hirise_ortho_url, f"{out}/ortho_hirise_1m.tif", site.bounds, 1.0, Resampling.average
    )
    print("Working out slope and roughness...")
    elevation, profile = read_raster(f"{out}/elevation_hirise_2m.tif")
    slope_2m = terrain.slope_degrees(elevation, 2.0)
    write_like(f"{out}/slope_deg_2m.tif", slope_2m, profile)
    write_like(f"{out}/slope_deg_10m.tif", terrain.slope_degrees(elevation, 2.0, smooth_cells=5), profile)
    write_like(f"{out}/roughness_m_10m.tif", terrain.roughness_m(elevation, 5), profile)
    return terrain.slope_summary(slope_2m)


def build_infrared(site, out):
    print("Downloading the THEMIS day and night infrared maps...")
    for name, url in (("night", site.themis_night_url), ("day", site.themis_day_url)):
        clip_remote_raster(
            url, f"{out}/themis_{name}_ir_100m.tif", site.wide_bounds, 100.0, Resampling.nearest
        )


def build_rover(site, out, http):
    print("Downloading Curiosity's path, stops and photo list...")
    traverse = rover.clip_features(rover.fetch_geojson(rover.TRAVERSE_URL, http), site.bounds)
    waypoints = rover.clip_features(rover.fetch_geojson(rover.WAYPOINTS_URL, http), site.bounds)
    with open(f"{out}/curiosity_traverse.geojson", "w") as f:
        json.dump(traverse, f)
    with open(f"{out}/curiosity_waypoints.geojson", "w") as f:
        json.dump(waypoints, f)

    positions = rover.rover_position_by_sol(waypoints)
    first, last = site.campaign_sols
    images = rover.fetch_raw_images(first, last, ["NAV_LEFT_B", "MAST_LEFT", "MAST_RIGHT"], http)
    with open(f"{out}/raw_images_sols_{first}-{last}.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["sol", "camera", "date_taken_utc", "image_url", "rover_lat", "rover_lon", "rover_elev_m"])
        for img in images:
            lat, lon, elev = rover.position_on(img["sol"], positions)
            writer.writerow([img["sol"], img["camera"], img["date_taken_utc"], img["image_url"], lat, lon, elev])
    return len(traverse["features"]), len(images)


def build_radiation(site, out):
    print("Downloading RAD radiation readings (this is the slow part)...")
    files = radiation.list_rad_files(site.rad_folder)

    def one(entry):
        stem, sol = entry
        doses = radiation.fetch_sol_doses(site.rad_folder, stem)
        return [(sol, obs, d.get("B"), d.get("E")) for obs, d in sorted(doses.items())]

    rows = []
    with concurrent.futures.ThreadPoolExecutor(8) as pool:
        for sol_rows in pool.map(one, files):
            rows.extend(sol_rows)
    rows.sort()
    sols = [r[0] for r in rows]
    path = f"{out}/rad_dose_rate_sols_{min(sols)}-{max(sols)}.csv"
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["sol", "observation", "dose_rate_B_uGy_per_h", "dose_rate_E_uGy_per_h"])
        writer.writerows(rows)
    daily = radiation.daily_dose_mgy(rows)
    return len(rows), sum(daily.values()) / len(daily)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--site", default=GALE_BOXWORK.name, choices=sorted(SITES))
    parser.add_argument("--out", default=None, help="output folder (default: data/<site>)")
    parser.add_argument("--skip-radiation", action="store_true", help="skip the slow RAD download")
    args = parser.parse_args(argv)

    site = SITES[args.site]
    out = args.out or f"data/{site.name}"
    os.makedirs(out, exist_ok=True)
    http = requests.Session()

    slope = build_terrain(site, out)
    build_infrared(site, out)
    n_lines, n_images = build_rover(site, out, http)
    print(
        f"\nTerrain: median slope {slope['median_deg']:.1f} deg, "
        f"{slope['share_over_15_deg']:.0%} of the area is steeper than 15 deg."
    )
    print(f"Rover: {n_lines} path segments and {n_images} photos in the area.")
    if not args.skip_radiation:
        n_rad, mean_mgy = build_radiation(site, out)
        print(f"Radiation: {n_rad} readings, about {mean_mgy:.2f} mGy per sol on average.")
    print(f"\nDone. Everything is in {out}/")


if __name__ == "__main__":
    main()
