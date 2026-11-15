"""Mission budgets engine for Marswalk Navigators.

Calculates life-support, metabolic, thermal, electrical, and radiation
budgets along planned routes for astronauts and support rovers in Gale Crater.
"""
import math
from typing import Dict, List, Tuple, Any, Optional
from dataclasses import dataclass

# Planetary Constants
MARS_G = 3.721       # Martian surface gravity (m/s^2)
EARTH_G = 9.807      # Terrestrial surface gravity (m/s^2)
SOL_HOURS = 24.66    # Length of a Martian solar day in hours
EVA_MAX_HOURS = 8.0  # NASA standard maximum EVA duration

# Radiation Constants (from Curiosity RAD on Mount Sharp)
RAD_MEAN_DOSE_RATE_UGY_H = 6.60   # Micrograys per hour on Mount Sharp surface
RAD_QUALITY_FACTOR = 3.0          # Average quality factor for Martian surface galactic cosmic rays (GCR)

# Spacesuit & Human Life Support (PLSS) Parameters
@dataclass(frozen=True)
class AstronautSpecs:
    body_mass_kg: float = 80.0
    suit_mass_kg: float = 70.0         # Mars-class Extravehicular Mobility Unit (EMU) + PLSS
    terrain_factor_eta: float = 1.3    # Pandolf factor for coarse, unconsolidated Martian regolith
    suit_speed_factor: float = 0.60    # Mobility restriction factor compared to unencumbered hiker
    kj_per_liter_o2: float = 20.1      # Energy yield per liter of O2 consumed (Weir equation)
    o2_density_g_per_l: float = 1.429  # Normal density of gaseous oxygen
    plss_base_power_w: float = 60.0    # PLSS avionics, fans, and water pumps electrical load
    sublimator_water_kg_per_h: float = 0.35  # Cooling water loss rate via sublimator/membrane evaporator

ASTRONAUT_SPECS = AstronautSpecs()

# Support Rover Specifications (Curiosity / Mars 2026 Support Rover Class)
@dataclass(frozen=True)
class RoverSpecs:
    mass_kg: float = 899.0
    wheels: int = 6
    wheel_radius_m: float = 0.25       # 50 cm diameter wheels
    cg_height_m: float = 0.90
    track_width_m: float = 2.30
    speed_ms: float = 0.50             # Crew-support pace (1.8 km/h), so the rover can shadow a walk within one EVA
    rolling_coeff: float = 0.15        # Rolling resistance on loose rock and sand
    drive_efficiency: float = 0.55     # Motor, gearbox, and drivetrain mechanical efficiency
    hotel_power_w: float = 120.0       # Avionics, comms, and active thermal loop power
    solar_average_w: float = 45.0      # Deployable auxiliary ~1 m² solar array daytime average output (45 W)
    solar_peak_power_w: float = 180.0  # Auxiliary horizontal solar array peak output under noon clear sky
    edge_patch_mm2: float = 400.0      # Sharp bedrock contact patch (10 mm x 40 mm)
    dynamic_factor: float = 1.50       # Dynamic shock load allowance for rock strikes

ROVER_SPECS = RoverSpecs()


def tobler_walk_speed_ms(grade: float, speed_factor: float = 0.60) -> float:
    """Tobler's hiking velocity adapted for Mars EVA spacesuit mobility.

    v(G) = 6 * exp(-3.5 * |G + 0.05|) km/h, scaled by suit resistance.
    """
    kmh = 6.0 * math.exp(-3.5 * abs(grade + 0.05))
    return (kmh / 3.6) * speed_factor


def pandolf_metabolic_power_w(speed_ms: float, grade: float, specs: AstronautSpecs = ASTRONAUT_SPECS) -> float:
    """Pandolf's metabolic expenditure equation scaled for Martian gravity.

    Fitted on Earth and scaled for g_Mars / g_Earth for weight-dependent work.
    Returns metabolic rate in Watts (J/s).
    """
    w = specs.body_mass_kg
    l = specs.suit_mass_kg
    eta = specs.terrain_factor_eta
    gr = MARS_G / EARTH_G
    g_percent = max(0.0, grade) * 100.0

    standing = 1.5 * w + 2.0 * (w + l) * ((l / w) ** 2)
    moving = eta * (w + l) * (1.5 * (speed_ms ** 2) + 0.35 * speed_ms * g_percent)
    return 1.5 * w + gr * (standing - 1.5 * w + moving)


def compute_walk_budget(
    path_profile_points: List[Dict[str, float]],
    dose_rate_ugy_h: float = RAD_MEAN_DOSE_RATE_UGY_H,
    specs: AstronautSpecs = ASTRONAUT_SPECS,
) -> Dict[str, Any]:
    """Calculate astronaut EVA life-support, metabolic, thermal, and radiation budgets."""
    if len(path_profile_points) < 2:
        return {
            "duration_hours": 0.0,
            "duration_minutes": 0.0,
            "metabolic_energy_kj": 0.0,
            "metabolic_energy_kcal": 0.0,
            "average_metabolic_power_w": 0.0,
            "oxygen_consumed_liters": 0.0,
            "oxygen_consumed_kg": 0.0,
            "suit_thermal_heat_kj": 0.0,
            "sublimator_water_kg": 0.0,
            "radiation_absorbed_dose_ugy": 0.0,
            "radiation_equivalent_dose_usv": 0.0,
            "eva_limit_utilization_pct": 0.0,
        }

    total_seconds = 0.0
    total_joules = 0.0

    for i in range(1, len(path_profile_points)):
        p0 = path_profile_points[i - 1]
        p1 = path_profile_points[i]

        dx = p1["d"] - p0["d"]
        if dx <= 0.001:
            continue

        dz = p1["elev"] - p0["elev"]
        ds = math.hypot(dx, dz)
        grade = dz / dx

        v = tobler_walk_speed_ms(grade, specs.suit_speed_factor)
        dt = ds / max(v, 0.05)

        p_met = pandolf_metabolic_power_w(v, grade, specs)
        total_seconds += dt
        total_joules += p_met * dt

    hours = total_seconds / 3600.0
    kj = total_joules / 1000.0
    kcal = kj / 4.184
    avg_power_w = total_joules / max(total_seconds, 1.0)

    # Oxygen volume and mass (Weir equation)
    o2_liters = kj / specs.kj_per_liter_o2
    o2_kg = (o2_liters * specs.o2_density_g_per_l) / 1000.0

    # Heat rejected by suit: ~80% of human metabolic power + PLSS avionics
    suit_heat_kj = ((0.80 * avg_power_w + specs.plss_base_power_w) * total_seconds) / 1000.0
    cooling_water_kg = hours * specs.sublimator_water_kg_per_h

    # Radiation doses
    absorbed_dose_ugy = hours * dose_rate_ugy_h
    equivalent_dose_usv = absorbed_dose_ugy * RAD_QUALITY_FACTOR  # Sv = Gy * Q

    return {
        "duration_hours": round(hours, 2),
        "duration_minutes": round(hours * 60.0, 1),
        "metabolic_energy_kj": round(kj, 1),
        "metabolic_energy_kcal": round(kcal, 1),
        "average_metabolic_power_w": round(avg_power_w, 1),
        "oxygen_consumed_liters": round(o2_liters, 1),
        "oxygen_consumed_kg": round(o2_kg, 3),
        "suit_thermal_heat_kj": round(suit_heat_kj, 1),
        "sublimator_water_kg": round(cooling_water_kg, 2),
        "radiation_absorbed_dose_ugy": round(absorbed_dose_ugy, 2),
        "radiation_equivalent_dose_usv": round(equivalent_dose_usv, 2),
        "eva_limit_utilization_pct": round((hours / EVA_MAX_HOURS) * 100.0, 1),
    }


def compute_drive_budget(
    path_profile_points: List[Dict[str, float]],
    rover: RoverSpecs = ROVER_SPECS,
) -> Dict[str, Any]:
    """Calculate support rover traction energy, hotel power, duration, and solar yield."""
    if len(path_profile_points) < 2:
        return {
            "duration_hours": 0.0,
            "motion_energy_wh": 0.0,
            "hotel_energy_wh": 0.0,
            "total_energy_wh": 0.0,
            "solar_yield_wh": 0.0,
            "net_battery_balance_wh": 0.0,
        }

    m = rover.mass_kg
    total_joules = 0.0
    total_distance_m = 0.0

    for i in range(1, len(path_profile_points)):
        p0 = path_profile_points[i - 1]
        p1 = path_profile_points[i]

        dx = p1["d"] - p0["d"]
        if dx <= 0.001:
            continue

        dz = p1["elev"] - p0["elev"]
        ds = math.hypot(dx, dz)
        theta = math.atan2(dz, dx)

        # Force resisting motion: rolling friction + climbing gravity component
        f_traction = m * MARS_G * (rover.rolling_coeff * math.cos(theta) + max(0.0, math.sin(theta)))
        mech_work = (f_traction * ds) / rover.drive_efficiency
        total_joules += mech_work
        total_distance_m += ds

    hours = (total_distance_m / rover.speed_ms) / 3600.0
    motion_wh = total_joules / 3600.0
    hotel_wh = rover.hotel_power_w * hours
    total_consumed_wh = motion_wh + hotel_wh

    # Solar power generation along the route:
    # Gale Crater boxwork at 4.8°S receives ~500 W/m² peak solar irradiance.
    # An auxiliary ~1 m² deployable solar panel array averages ~45 W daytime output.
    # Assumption: Daytime traverse with clear sky and consistent solar incidence averaging 45.0 W.
    solar_yield_wh = rover.solar_average_w * hours
    net_balance_wh = solar_yield_wh - total_consumed_wh

    return {
        "duration_hours": round(hours, 2),
        "motion_energy_wh": round(motion_wh, 1),
        "hotel_energy_wh": round(hotel_wh, 1),
        "total_energy_wh": round(total_consumed_wh, 1),
        "solar_yield_wh": round(solar_yield_wh, 1),
        "net_battery_balance_wh": round(net_balance_wh, 1),
    }


def compute_wheel_load_cases(
    max_slope_deg: float,
    max_roughness_m: float,
    rover: RoverSpecs = ROVER_SPECS,
) -> List[Dict[str, Any]]:
    """Compute structural FEA load cases on a single rover wheel from route terrain."""
    w_total = rover.mass_kg * MARS_G
    w0 = w_total / rover.wheels
    theta = math.radians(max_slope_deg)
    step = min(max_roughness_m, 0.5 * rover.wheel_radius_m)
    r = rover.wheel_radius_m
    df = rover.dynamic_factor

    cases = []

    # LC1: Parked level ground
    cases.append({
        "id": "LC1",
        "name": "Parked on level ground",
        "note": "Static weight evenly distributed across 6 wheels",
        "fz_n": round(w0, 1),
        "fx_n": 0.0,
        "fy_n": 0.0,
        "resultant_n": round(w0, 1),
        "pressure_mpa": None,
    })

    # LC2: Straight ascent on steepest route slope
    fz2 = w0 * math.cos(theta)
    fx2 = w0 * math.sin(theta)
    cases.append({
        "id": "LC2",
        "name": f"Ascending {max_slope_deg:.1f}° slope",
        "note": "Steepest slope on planned route, maximum tractive pull",
        "fz_n": round(fz2, 1),
        "fx_n": round(fx2, 1),
        "fy_n": 0.0,
        "resultant_n": round(math.hypot(fz2, fx2), 1),
        "pressure_mpa": None,
    })

    # LC3: Traversing across cross-slope
    lateral_transfer = (w_total * math.sin(theta) * rover.cg_height_m) / rover.track_width_m / (rover.wheels / 2)
    fz3 = w0 * math.cos(theta) + lateral_transfer
    fy3 = fz3 * math.tan(theta)
    cases.append({
        "id": "LC3",
        "name": f"Side-slope traverse {max_slope_deg:.1f}°",
        "note": "Downhill wheel bearing lateral CG load transfer",
        "fz_n": round(fz3, 1),
        "fx_n": 0.0,
        "fy_n": round(fy3, 1),
        "resultant_n": round(math.hypot(fz3, fy3), 1),
        "pressure_mpa": None,
    })

    # LC4: Driving onto rough ledge / boxwork ridge
    push = (w0 * math.sqrt(step * (2 * r - step))) / max(0.01, (r - step)) if step > 0 else 0.0
    fz4 = w0 * df
    fx4 = push * df
    cases.append({
        "id": "LC4",
        "name": f"Climbing {(step * 100):.0f} cm bedrock ledge",
        "note": f"Surface roughness ridge impact with {df}x dynamic factor",
        "fz_n": round(fz4, 1),
        "fx_n": round(fx4, 1),
        "fy_n": 0.0,
        "resultant_n": round(math.hypot(fz4, fx4), 1),
        "pressure_mpa": None,
    })

    # LC5: Point strike on sharp rock edge (Curiosity wheel puncture case)
    fz5 = w0 * df * math.cos(theta)
    pressure_mpa = fz5 / rover.edge_patch_mm2
    cases.append({
        "id": "LC5",
        "name": "Sharp rock puncture load",
        "note": f"Full dynamic wheel reaction concentrated on {rover.edge_patch_mm2:.0f} mm² rock tip",
        "fz_n": round(fz5, 1),
        "fx_n": 0.0,
        "fy_n": 0.0,
        "resultant_n": round(fz5, 1),
        "pressure_mpa": round(pressure_mpa, 2),
    })

    # Mark worst resultant case
    worst = max(cases, key=lambda c: c["resultant_n"])
    for c in cases:
        c["worst_case"] = (c["id"] == worst["id"])

    return cases


def sample_path_profile(
    path_coords: List[List[float]],
    grid_elev_func,
    grid_slope_func,
    grid_rough_func,
    sampling_interval_m: float = 10.0,
) -> List[Dict[str, float]]:
    """Sample continuous elevation, slope, and roughness along a polyline route."""
    if not path_coords:
        return []

    profile = []
    cumulative_dist = 0.0

    for i in range(len(path_coords) - 1):
        p0 = path_coords[i]
        p1 = path_coords[i + 1]

        # Mars equirectangular segment length
        d_lat = math.radians(p1[0] - p0[0])
        d_lon = math.radians(p1[1] - p0[1]) * math.cos(math.radians((p0[0] + p1[0]) / 2.0))
        seg_dist = math.hypot(d_lat, d_lon) * 3_396_190.0

        num_samples = max(1, int(round(seg_dist / sampling_interval_m)))
        for s in range(num_samples):
            fraction = s / num_samples
            lat = p0[0] + fraction * (p1[0] - p0[0])
            lon = p0[1] + fraction * (p1[1] - p0[1])
            d_curr = cumulative_dist + fraction * seg_dist

            elev = grid_elev_func(lat, lon)
            slope = grid_slope_func(lat, lon)
            rough = grid_rough_func(lat, lon)

            profile.append({
                "lat": lat,
                "lon": lon,
                "d": d_curr,
                "elev": elev,
                "slope": slope,
                "rough": rough,
            })

        cumulative_dist += seg_dist

    # Last point
    last_p = path_coords[-1]
    profile.append({
        "lat": last_p[0],
        "lon": last_p[1],
        "d": cumulative_dist,
        "elev": grid_elev_func(last_p[0], last_p[1]),
        "slope": grid_slope_func(last_p[0], last_p[1]),
        "rough": grid_rough_func(last_p[0], last_p[1]),
    })

    return profile
