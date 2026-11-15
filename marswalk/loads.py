"""Wheel load cases for FEA, taken from the worst terrain the rover will meet.

Curiosity's aluminum wheels were famously punctured by sharp rocks on Mount
Sharp. This module turns our terrain maps into the forces on a single wheel in
five situations a crew support rover will actually face, then does a quick hand
calculation on the wheel skin. The forces go into the FEA model (see
docs/fea-setup.md), and the hand calculation tells us roughly what answer to
expect, so we can spot a broken model.

The numbers match the "Rover load cases" section of our website (web/js/physics.js).
Every assumption is a named value in RoverSpec, so it's easy to question.

Axes for every load: x is along the direction of travel, y is sideways, and
z is into the ground (the wheel's normal load).
"""
import argparse
import csv
import json
import math
from dataclasses import asdict, dataclass

import numpy as np

MARS_G = 3.721  # m/s^2


@dataclass(frozen=True)
class RoverSpec:
    """The support rover and its wheels. Curiosity is our reference vehicle."""

    mass_kg: float = 899.0  # Curiosity's mass
    wheels: int = 6
    wheel_radius_m: float = 0.25  # Curiosity's wheels are 50 cm across
    cg_height_m: float = 0.9  # assumed
    track_m: float = 2.3  # assumed distance between left and right wheels
    dynamic_factor: float = 1.5  # assumed allowance for bumps and impacts while driving
    edge_patch_mm2: float = 400.0  # a sharp rock edge loading a 10 by 40 mm strip, assumed
    # Wheel skin, for the hand calculation. Curiosity's wheels are machined
    # 7075 aluminum with a skin about 0.75 mm thick between the treads (grousers).
    skin_thickness_mm: float = 0.75
    skin_yield_mpa: float = 435.0  # 7075-T7351, typical
    poisson: float = 0.33
    unsupported_span_mm: float = 50.0  # skin width between neighbouring grousers, assumed
    rock_tip_radius_mm: float = 2.0  # how pointed the rock is, assumed


def wheel_load_cases(max_slope_deg, max_roughness_m, rover=RoverSpec()):
    """Forces on one wheel, in newtons, for the five terrain cases.

    `max_slope_deg` and `max_roughness_m` are the worst values the rover meets
    on its route. Returns a list of dicts with fx, fy, fz and the resultant.
    """
    weight = rover.mass_kg * MARS_G
    per_wheel = weight / rover.wheels
    theta = math.radians(max_slope_deg)
    r = rover.wheel_radius_m
    df = rover.dynamic_factor
    # The roughness map can't tell a 3 m boulder from a 3 m ridge, and the rover
    # would drive around anything taller than about half a wheel anyway.
    step = min(max_roughness_m, 0.5 * r)

    cases = [
        dict(case="LC1", description="Parked on level ground", fz=per_wheel, fx=0.0, fy=0.0,
             note="Static weight shared evenly by all wheels"),
        dict(case="LC2", description=f"Climbing a {max_slope_deg:.0f} degree slope straight up",
             fz=per_wheel * math.cos(theta), fx=per_wheel * math.sin(theta), fy=0.0,
             note="Steepest slope on the route, every wheel pulling its share"),
    ]

    # Parked across the slope, weight shifts onto the downhill wheels.
    transfer = weight * math.sin(theta) * rover.cg_height_m / rover.track_m / (rover.wheels / 2)
    fz_down = per_wheel * math.cos(theta) + transfer
    cases.append(dict(case="LC3", description=f"Across a {max_slope_deg:.0f} degree slope",
                      fz=fz_down, fx=0.0, fy=fz_down * math.tan(theta),
                      note="Downhill wheel, with weight shifted toward it"))

    # To roll a wheel of radius r onto a step of height h you need a horizontal
    # push of W * sqrt(h(2r - h)) / (r - h). Then we add the impact allowance.
    push = per_wheel * math.sqrt(step * (2 * r - step)) / (r - step) if step > 0 else 0.0
    cases.append(dict(case="LC4", description=f"Driving onto a {step * 100:.0f} cm ledge",
                      fz=per_wheel * df, fx=push * df, fy=0.0,
                      note=f"Ridge edge from the roughness map, capped at half the wheel radius, times {df} for impact"))

    fz_edge = per_wheel * df * math.cos(theta)
    cases.append(dict(case="LC5", description="Sharp rock pressing into the wheel skin",
                      fz=fz_edge, fx=0.0, fy=0.0, pressure_mpa=fz_edge / rover.edge_patch_mm2,
                      note=f"Same wheel load through a {rover.edge_patch_mm2:.0f} mm^2 rock edge"))

    for c in cases:
        c["resultant"] = math.sqrt(c["fx"] ** 2 + c["fy"] ** 2 + c["fz"] ** 2)
    worst = max(cases, key=lambda c: c["resultant"])
    for c in cases:
        c["worst"] = c is worst
    return cases


def skin_hand_calc(force_n, rover=RoverSpec()):
    """A quick check of the wheel skin under a pointed rock, to sanity-check the FEA.

    Two classic textbook models:

    * Punching shear: the force spread around the edge of the rock tip, through
      the skin thickness.
    * Plate bending: the skin between two grousers treated as a simply
      supported circular plate with a load on a small central patch (Roark,
      table 11.2, case 16). This is the one that usually governs for thin skins.

    Both are rough. They tell us the order of magnitude to expect from the FEA.
    """
    t = rover.skin_thickness_mm
    r0 = rover.rock_tip_radius_mm
    a = rover.unsupported_span_mm / 2
    nu = rover.poisson
    shear_mpa = force_n / (2 * math.pi * r0 * t)
    bending_mpa = 3 * force_n / (2 * math.pi * t * t) * ((1 + nu) * math.log(a / r0) + 1)
    return {
        "punching_shear_mpa": shear_mpa,
        "plate_bending_mpa": bending_mpa,
        # Shear yield is roughly 0.577 times tensile yield (von Mises).
        "safety_factor_shear": 0.577 * rover.skin_yield_mpa / shear_mpa,
        "safety_factor_bending": rover.skin_yield_mpa / bending_mpa,
    }


def terrain_along(points_lonlat, slope_path, rough_path):
    """Slope and roughness under a list of (lon, lat) points, read from our maps."""
    import rasterio

    from .site import lonlat_to_xy

    xy = [lonlat_to_xy(lon, lat) for lon, lat in points_lonlat]
    out = []
    for path in (slope_path, rough_path):
        with rasterio.open(path) as src:
            values = np.array([v[0] for v in src.sample(xy)], dtype="float64")
            values[(values < -1e30) | np.isnan(values)] = np.nan
            out.append(values)
    return out


def curiosity_extremes(data_dir, first_sol=None, last_sol=None, percentile=95):
    """The worst slope and roughness Curiosity met at its stops in the area.

    We use the 95th percentile rather than the single worst stop, because one
    odd cell in the elevation map shouldn't set the design load on its own.
    """
    with open(f"{data_dir}/curiosity_waypoints.geojson") as f:
        stops = json.load(f)["features"]
    pts = [
        (s["properties"]["lon"], s["properties"]["lat"])
        for s in stops
        if (first_sol is None or s["properties"]["sol"] >= first_sol)
        and (last_sol is None or s["properties"]["sol"] <= last_sol)
    ]
    slope, rough = terrain_along(pts, f"{data_dir}/slope_deg_10m.tif", f"{data_dir}/roughness_m_10m.tif")
    return {
        "stops": len(pts),
        "slope_deg": float(np.nanpercentile(slope, percentile)),
        "roughness_m": float(np.nanpercentile(rough, percentile)),
        "max_slope_deg": float(np.nanmax(slope)),
        "max_roughness_m": float(np.nanmax(rough)),
    }


def write_csv(path, cases, header_lines):
    with open(path, "w", newline="") as f:
        for line in header_lines:
            f.write(f"# {line}\n")
        writer = csv.writer(f)
        writer.writerow(["case", "description", "Fz_normal_N", "Fx_along_N", "Fy_side_N", "resultant_N", "edge_pressure_MPa"])
        for c in cases:
            writer.writerow([c["case"], c["description"], f"{c['fz']:.1f}", f"{c['fx']:.1f}", f"{c['fy']:.1f}",
                             f"{c['resultant']:.1f}", f"{c['pressure_mpa']:.2f}" if "pressure_mpa" in c else ""])


def main(argv=None):
    parser = argparse.ArgumentParser(description="Make wheel load cases for FEA from the terrain Curiosity drove over.")
    parser.add_argument("--data", default="data/gale-boxwork")
    parser.add_argument("--out", default="fea/wheel_load_cases.csv")
    parser.add_argument("--slope", type=float, help="use this slope (degrees) instead of reading the maps")
    parser.add_argument("--roughness", type=float, help="use this roughness (meters) instead of reading the maps")
    args = parser.parse_args(argv)

    rover = RoverSpec()
    if args.slope is not None and args.roughness is not None:
        slope, rough, source = args.slope, args.roughness, "values given on the command line"
    else:
        ext = curiosity_extremes(args.data)
        slope, rough = ext["slope_deg"], ext["roughness_m"]
        source = (f"95th percentile over Curiosity's {ext['stops']} stops in the area "
                  f"(single worst stop: {ext['max_slope_deg']:.1f} deg, {ext['max_roughness_m']:.2f} m)")

    cases = wheel_load_cases(slope, rough, rover)
    edge = next(c for c in cases if c["case"] == "LC5")
    check = skin_hand_calc(edge["fz"], rover)

    import os

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    write_csv(args.out, cases, [
        "Marswalk Navigators: wheel load cases, Mount Sharp boxwork",
        f"Terrain: slope {slope:.1f} deg, roughness {rough:.2f} m, from {source}",
        f"Rover: {rover.mass_kg:.0f} kg, {rover.wheels} wheels, wheel radius {rover.wheel_radius_m} m, Mars gravity {MARS_G} m/s^2",
        "Axes: x along travel, y sideways, z into the ground. Forces are on one wheel.",
    ])
    with open(os.path.splitext(args.out)[0] + "_inputs.json", "w") as f:
        json.dump({"slope_deg": slope, "roughness_m": rough, "source": source, "rover": asdict(rover),
                   "skin_hand_calc": check}, f, indent=2)

    print(f"Terrain used: slope {slope:.1f} deg, roughness {rough:.2f} m ({source})\n")
    print(f"{'Case':5} {'Description':45} {'Fz (N)':>8} {'Fx (N)':>8} {'Fy (N)':>8} {'Total (N)':>10}")
    for c in cases:
        flag = "  <- worst" if c["worst"] else ""
        print(f"{c['case']:5} {c['description']:45} {c['fz']:8.0f} {c['fx']:8.0f} {c['fy']:8.0f} {c['resultant']:10.0f}{flag}")
    print(f"\nHand check of the wheel skin under a pointed rock ({edge['fz']:.0f} N):")
    print(f"  punching shear {check['punching_shear_mpa']:.0f} MPa (safety factor {check['safety_factor_shear']:.1f})")
    print(f"  plate bending  {check['plate_bending_mpa']:.0f} MPa (safety factor {check['safety_factor_bending']:.2f})")
    if check["safety_factor_bending"] < 1:
        print("  The skin would yield, which lines up with the punctures Curiosity actually suffered.")
    print(f"\nSaved {args.out}")


if __name__ == "__main__":
    main()
