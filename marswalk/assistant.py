"""Mission briefing for Marswalk Navigators.

Turns a planned route and its budgets into a short written briefing: how far
the walk is, what it costs the crew member, what the support rover has to do,
what to watch out for, and which of Curiosity's stops it passes. Every line
comes straight from the numbers in budgets.py and planner.py.
"""
import math
from typing import Dict, List, Any, Optional

from marswalk.budgets import (
    compute_walk_budget,
    compute_drive_budget,
    compute_wheel_load_cases,
    ASTRONAUT_SPECS,
    ROVER_SPECS,
    EVA_MAX_HOURS,
    RAD_MEAN_DOSE_RATE_UGY_H,
)
from marswalk.planner import PROFILES


def find_nearby_science_stops(
    route_coords: List[List[float]],
    all_stops: List[Dict[str, Any]],
    proximity_threshold_m: float = 250.0,
) -> List[Dict[str, Any]]:
    """Identify Curiosity science stops situated within proximity of the planned route."""
    if not route_coords or not all_stops:
        return []

    nearby = []
    mars_r = 3_396_190.0

    for stop in all_stops:
        s_lat = stop["lat"]
        s_lon = stop["lon"]
        min_dist = float("inf")

        for r_lat, r_lon in route_coords:
            d_lat = math.radians(s_lat - r_lat)
            d_lon = math.radians(s_lon - r_lon) * math.cos(math.radians((s_lat + r_lat) / 2.0))
            dist = math.hypot(d_lat, d_lon) * mars_r
            if dist < min_dist:
                min_dist = dist

        if min_dist <= proximity_threshold_m:
            stop_copy = dict(stop)
            stop_copy["distance_to_route_m"] = round(min_dist, 1)
            nearby.append(stop_copy)

    return nearby


def _hm(hours: float) -> str:
    """Format hours as '1 h 49 min' or '35 min'."""
    total_min = int(round(hours * 60.0))
    h, m = divmod(total_min, 60)
    return f"{h} h {m:02d} min" if h else f"{m} min"


def generate_mission_briefing(
    route: Dict[str, Any],
    walk_budget: Dict[str, Any],
    drive_budget: Dict[str, Any],
    load_cases: List[Dict[str, Any]],
    nearby_stops: List[Dict[str, Any]],
    rover_note: Optional[str] = None,
) -> Dict[str, Any]:
    """Write a short, plain-language briefing for a planned Marswalk.

    rover_note, when given, replaces the rover paragraph. The API uses it when
    the support rover has no safe route of its own between the two points.
    """
    agent = route.get("agent", "astronaut")
    agent_profile = PROFILES.get(agent, PROFILES["astronaut"])

    dist_m = route.get("route_distance_m", 0.0)
    climb_m = route.get("elevation_gain_m", 0.0)
    descent_m = route.get("elevation_loss_m", 0.0)
    max_slope = route.get("max_slope_deg", 0.0)
    mean_slope = route.get("mean_slope_deg", 0.0)
    max_rough = route.get("max_roughness_m", 0.0)

    duration_h = walk_budget.get("duration_hours", 0.0)
    eva_pct = walk_budget.get("eva_limit_utilization_pct", 0.0)
    is_go = (
        (duration_h <= EVA_MAX_HOURS)
        and (max_slope <= agent_profile.max_slope_deg)
        and (max_rough <= agent_profile.max_roughness_m)
    )
    status_label = "GO FOR EVA" if is_go else "CAUTION / CONTINGENCY REQUIRED"

    # Things to watch, checked against the same limits the planner uses
    hazard_warnings = []
    if max_slope > agent_profile.max_slope_deg:
        hazard_warnings.append(
            f"The steepest ground is {max_slope:.1f}°, past the {agent_profile.max_slope_deg:.0f}° limit for this {agent}."
        )
    elif max_slope >= agent_profile.comfort_slope_deg:
        hazard_warnings.append(
            f"The steepest ground is {max_slope:.1f}°, above the {agent_profile.comfort_slope_deg:.0f}° that feels comfortable "
            f"(the hard limit is {agent_profile.max_slope_deg:.0f}°). Take that stretch slowly."
        )
    if max_rough >= agent_profile.caution_roughness_m:
        hazard_warnings.append(
            f"Ridges and ledges up to {max_rough:.2f} m high (we start to worry at {agent_profile.caution_roughness_m:.1f} m). "
            "Sharp boxwork edges can snag a suit and cut rover wheels."
        )
    if duration_h > EVA_MAX_HOURS / 2.0:
        hazard_warnings.append(
            f"One way takes {_hm(duration_h)}, so out and back won't fit in one {EVA_MAX_HOURS:.0f} hour spacewalk."
        )
    if not hazard_warnings:
        hazard_warnings.append("Nothing stands out. The slopes and roughness along this route are well inside the limits.")

    # Curiosity stops near the route, with the names and write-ups from the site data
    stops_summary = []
    for s in nearby_stops:
        stop_title = s.get("title") or s.get("name", "Stop")
        sols = s.get("sols") or []
        stop_blurb = (
            s.get("blurb")
            or s.get("description")
            or s.get("note")
            or (f"Curiosity parked here on sol {sols[0]}." if sols else "One of Curiosity's stops.")
        )
        stops_summary.append({
            "name": stop_title,
            "title": stop_title,
            "blurb": stop_blurb,
            "distance_m": s.get("distance_to_route_m", 0.0),
            "elevation_m": s.get("elev_m", 0.0),
            "description": f"{stop_title} ({s.get('distance_to_route_m', 0.0):.0f} m from the route): {stop_blurb}",
            "photo_count": s.get("photo_count", 0),
            "sample_photo": s.get("photos", [{}])[0].get("url") if s.get("photos") else None,
        })

    worst_lc = next((c for c in load_cases if c.get("worst_case")), load_cases[0] if load_cases else {})

    # Radiation, put next to a whole sol outside and NASA's 30-day limit
    equiv_dose_usv = walk_budget.get("radiation_equivalent_dose_usv", 0.0)
    absorbed_dose_ugy = walk_budget.get("radiation_absorbed_dose_ugy", 0.0)
    dose_pct_30d = (equiv_dose_usv / 250_000.0) * 100.0  # 250 mSv over 30 days
    sol_dose_ugy = RAD_MEAN_DOSE_RATE_UGY_H * 24.66

    md_lines = [
        "# Marswalk briefing: Mount Sharp boxwork",
        f"**Call:** {status_label} · **Who:** {agent} · **Route:** {dist_m / 1000.0:.2f} km",
        "",
        "## The walk",
        f"The route is {dist_m / 1000.0:.2f} km long, with {climb_m:.0f} m of climbing and {descent_m:.0f} m down. "
        f"The average slope is {mean_slope:.1f}° and the steepest is {max_slope:.1f}°.",
        "",
        "## What it costs the crew member (one way)",
        f"- Time: {_hm(duration_h)}, which is {eva_pct:.0f}% of an {EVA_MAX_HOURS:.0f} hour spacewalk.",
        f"- Energy: about {walk_budget.get('metabolic_energy_kcal', 0):.0f} kcal, averaging {walk_budget.get('average_metabolic_power_w', 0):.0f} W.",
        f"- Oxygen: {walk_budget.get('oxygen_consumed_kg', 0):.2f} kg ({walk_budget.get('oxygen_consumed_liters', 0):.0f} L).",
        f"- Cooling: {walk_budget.get('suit_thermal_heat_kj', 0):.0f} kJ of body heat to get rid of, "
        f"or about {walk_budget.get('sublimator_water_kg', 0):.2f} kg of cooling water.",
        f"- Radiation: {absorbed_dose_ugy:.1f} µGy ({equiv_dose_usv:.1f} µSv) at the {RAD_MEAN_DOSE_RATE_UGY_H:.1f} µGy/h Curiosity measured here. "
        f"A whole sol outside would be about {sol_dose_ugy:.0f} µGy, and this walk is {dose_pct_30d:.3f}% of NASA's 30-day limit of 250 mSv.",
        "",
        "## The support rover",
    ]
    if rover_note:
        md_lines.append(rover_note)
    else:
        md_lines.extend([
            f"- Driving time: {_hm(drive_budget.get('duration_hours', 0))}.",
            f"- Energy: {drive_budget.get('total_energy_wh', 0):.0f} Wh ({drive_budget.get('motion_energy_wh', 0):.0f} Wh to move, "
            f"{drive_budget.get('hotel_energy_wh', 0):.0f} Wh for electronics and heating). The solar panel adds about "
            f"{drive_budget.get('solar_yield_wh', 0):.0f} Wh on the way, leaving {drive_budget.get('net_battery_balance_wh', 0):.0f} Wh from the battery.",
        ])
    if worst_lc:
        md_lines.append(
            f"- Hardest load on a wheel: {worst_lc.get('id', 'LC')}, {worst_lc.get('name', '')}, about {worst_lc.get('resultant_n', 0):.0f} N."
        )

    md_lines.extend(["", "## Things to watch"])
    md_lines.extend(f"- {w}" for w in hazard_warnings)

    if stops_summary:
        md_lines.extend(["", "## Curiosity stops along the way"])
        for st in stops_summary:
            md_lines.append(f"- **{st['title']}**, {st['distance_m']:.0f} m from the route: {st['blurb']}")

    md_lines.extend([
        "",
        "## Call",
        (
            f"{status_label}, on foot without the rover. Keep voice contact with the habitat the whole way."
            if rover_note else
            f"{status_label}. Keep the rover a few meters behind the crew member on climbs steeper than "
            f"{PROFILES['rover'].comfort_slope_deg:.0f}°, and keep voice contact the whole way."
        ),
    ])

    return {
        "status": status_label,
        "is_go": is_go,
        "briefing_source": "template",
        "briefing_markdown": "\n".join(md_lines),
        "executive_summary": {
            "agent": agent,
            "route_distance_km": round(dist_m / 1000.0, 3),
            "duration_hours": duration_h,
            "elevation_gain_m": climb_m,
            "elevation_loss_m": descent_m,
            "max_slope_deg": max_slope,
            "mean_slope_deg": mean_slope,
        },
        "life_support": walk_budget,
        "rover_systems": drive_budget,
        "hazard_warnings": hazard_warnings,
        "nearby_science_stops": stops_summary,
        "worst_load_case": worst_lc,
    }
