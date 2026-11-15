"""Mission Briefing for Marswalk Navigators.

Generates an astronaut-ready mission briefing explaining waypoints,
hazards, life-support consumables, rover mechanics, and terrain constraints.
Supports optional LLM synthesis when an API key is configured in the environment,
with robust deterministic fallback to physics-backed mission templates.
"""
import os
import json
import math
import urllib.request
import urllib.error
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


def _try_llm_enhancement(prompt: str) -> Optional[str]:
    """Optional LLM enhancement reading API key from environment variable.

    Falls back cleanly to None if key is absent or request fails.
    """
    gemini_key = os.getenv("GEMINI_API_KEY")
    groq_key = os.getenv("GROQ_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")

    if not (gemini_key or groq_key or openai_key):
        return None

    try:
        if gemini_key:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={gemini_key}"
            payload = json.dumps({
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.2, "maxOutputTokens": 1000}
            }).encode("utf-8")
            req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data["candidates"][0]["content"]["parts"][0]["text"]
        elif groq_key:
            url = "https://api.groq.com/openai/v1/chat/completions"
            payload = json.dumps({
                "model": "llama-3.1-8b-instant",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 1000,
                "temperature": 0.2
            }).encode("utf-8")
            req = urllib.request.Request(url, data=payload, headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {groq_key}"
            })
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data["choices"][0]["message"]["content"]
    except Exception:
        # Graceful fallback to deterministic template
        return None
    return None


def generate_mission_briefing(
    route: Dict[str, Any],
    walk_budget: Dict[str, Any],
    drive_budget: Dict[str, Any],
    load_cases: List[Dict[str, Any]],
    nearby_stops: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Generate a structured, astronaut-ready mission briefing for Marswalk planning."""
    agent = route.get("agent", "astronaut")
    agent_profile = PROFILES.get(agent, PROFILES["astronaut"])

    dist_m = route.get("route_distance_m", 0.0)
    climb_m = route.get("elevation_gain_m", 0.0)
    descent_m = route.get("elevation_loss_m", 0.0)
    max_slope = route.get("max_slope_deg", 0.0)
    mean_slope = route.get("mean_slope_deg", 0.0)
    max_rough = route.get("max_roughness_m", 0.0)

    # Operational Status using limits from PROFILES
    duration_h = walk_budget.get("duration_hours", 0.0)
    eva_pct = walk_budget.get("eva_limit_utilization_pct", 0.0)
    is_go = (
        (duration_h <= EVA_MAX_HOURS)
        and (max_slope <= agent_profile.max_slope_deg)
        and (max_rough <= agent_profile.max_roughness_m)
    )
    status_label = "GO FOR EVA" if is_go else "CAUTION / CONTINGENCY REQUIRED"

    # Hazards Summary evaluated against profile thresholds
    hazard_warnings = []
    if max_slope >= agent_profile.comfort_slope_deg:
        hazard_warnings.append(
            f"Steep incline detected: Maximum slope reaches {max_slope:.1f}° (comfort threshold is {agent_profile.comfort_slope_deg:.0f}°, profile limit is {agent_profile.max_slope_deg:.0f}°). Maintain deliberate footing and traction control."
        )
    if max_rough >= agent_profile.caution_roughness_m:
        hazard_warnings.append(
            f"Sharp ridge relief: Surface roughness peaks at {max_rough:.2f} m (caution threshold is {agent_profile.caution_roughness_m:.1f} m). Boxwork fracture fins present snag hazards for suit fabrics and puncture risks for rover wheels."
        )
    if duration_h > 6.0:
        hazard_warnings.append(
            f"Extended duration: Projected EVA time of {duration_h:.1f} hours consumes {eva_pct:.0f}% of standard 8.0-hour suit consumables ceiling."
        )
    if not hazard_warnings:
        hazard_warnings.append("Terrain gradient and roughness are benign along this traverse corridor.")

    # Dynamic Science Context: use stop title and blurb from science stops dataset
    stops_summary = []
    for s in nearby_stops:
        stop_title = s.get("title") or s.get("name", "Stop")
        stop_blurb = (
            s.get("blurb")
            or s.get("description")
            or s.get("note")
            or f"Curiosity exploration target (Sol {s.get('sols', [0])[0] if s.get('sols') else 'N/A'}) with rover imaging and radiation surveys."
        )
        stops_summary.append({
            "name": stop_title,
            "title": stop_title,
            "blurb": stop_blurb,
            "distance_m": s.get("distance_to_route_m", 0.0),
            "elevation_m": s.get("elev_m", 0.0),
            "description": f"{stop_title} ({s.get('distance_to_route_m', 0.0):.0f} m standoff): {stop_blurb}",
            "photo_count": s.get("photo_count", 0),
            "sample_photo": s.get("photos", [{}])[0].get("url") if s.get("photos") else None,
        })

    # Worst-case hardware load case
    worst_lc = next((c for c in load_cases if c.get("worst_case")), load_cases[0] if load_cases else {})

    # Radiation Dose Context relative to NASA 30-day limits & sol exposure
    equiv_dose_usv = walk_budget.get("radiation_equivalent_dose_usv", 0.0)
    absorbed_dose_ugy = walk_budget.get("radiation_absorbed_dose_ugy", 0.0)
    # NASA standard 30-day exploration dose limit is 250 mSv = 250,000 µSv.
    dose_pct_30d = (equiv_dose_usv / 250_000.0) * 100.0
    dose_pct_sol = (duration_h / 24.66) * 100.0
    rad_context_text = (
        f"{dose_pct_30d:.4f}% of NASA 30-day limit (250 mSv), "
        f"~{dose_pct_sol:.1f}% of single-sol surface allowance at {RAD_MEAN_DOSE_RATE_UGY_H:.2f} µGy/h"
    )

    # Generate Markdown Briefing Text
    md_lines = [
        f"# 🔴 MARSWALK MISSION BRIEFING — GALE CRATER / MOUNT SHARP",
        f"**Operational Status:** `{status_label}` | **Target Profile:** `{agent.upper()}` | **Route Length:** `{dist_m:.0f} m`",
        "",
        "## 1. Executive Summary",
        f"The proposed Marswalk route covers **{dist_m / 1000.0:.2f} km** of varied terrain along Mount Sharp's boxwork formation. "
        f"The route ascends **+{climb_m:.1f} m** and descends **-{descent_m:.1f} m** with an average slope of **{mean_slope:.1f}°**.",
        "",
        "## 2. Life-Support & Consumables Budget (Astronaut EVA)",
        f"- **Traverse Time:** `{duration_h:.2f} hours` ({walk_budget.get('duration_minutes', 0):.0f} min) — **{eva_pct:.1f}%** of 8.0-hour EVA ceiling.",
        f"- **Metabolic Energy:** `{walk_budget.get('metabolic_energy_kcal', 0):.0f} kcal` ({walk_budget.get('metabolic_energy_kj', 0):.0f} kJ), averaging `{walk_budget.get('average_metabolic_power_w', 0):.0f} W`.",
        f"- **Primary Oxygen (O2):** `{walk_budget.get('oxygen_consumed_liters', 0):.1f} L` ({walk_budget.get('oxygen_consumed_kg', 0):.3f} kg) consumed.",
        f"- **Suit Thermal Rejection:** `{walk_budget.get('suit_thermal_heat_kj', 0):.0f} kJ` heat load; `{walk_budget.get('sublimator_water_kg', 0):.2f} kg` cooling water needed for PLSS sublimation.",
        f"- **Surface Radiation Exposure:** `{absorbed_dose_ugy:.1f} µGy` absorbed (`{equiv_dose_usv:.1f} µSv` equivalent dose, based on Curiosity RAD measurements). {rad_context_text}.",
        "",
        "## 3. Support Rover Synergy & Mechanical Integrity",
        f"- **Drive Time:** `{drive_budget.get('duration_hours', 0):.2f} hours` at nominal pace.",
        f"- **Total Energy Consumed:** `{drive_budget.get('total_energy_wh', 0):.1f} Wh` (Motion: `{drive_budget.get('motion_energy_wh', 0):.1f} Wh`, Hotel: `{drive_budget.get('hotel_energy_wh', 0):.1f} Wh`).",
        f"- **Solar Array Yield:** `{drive_budget.get('solar_yield_wh', 0):.1f} Wh` generated along route; net balance: `{drive_budget.get('net_battery_balance_wh', 0):.1f} Wh`.",
        f"- **Peak Hardware Load Case ({worst_lc.get('id', 'LC')}):** {worst_lc.get('name', 'Peak Load')} producing resultant force of **{worst_lc.get('resultant_n', 0):.1f} N** on wheel assembly.",
        "",
        "## 4. Terrain Hazards & Flight Rules",
    ]

    for warning in hazard_warnings:
        md_lines.append(f"- ⚠️ **{warning}**")

    if stops_summary:
        md_lines.append("")
        md_lines.append("## 5. Geological Science Opportunities (Curiosity Waypoints)")
        for st in stops_summary:
            md_lines.append(f"- **{st['title']}** ({st['distance_m']:.0f} m standoff, elev {st['elevation_m']:.0f} m): {st['blurb']}")

    md_lines.extend([
        "",
        "## 6. CAPCOM Recommendation",
        f"**{status_label}.** Proceed with nominal pre-breathe protocol. Maintain voice and telemetry link between EVA-1 and support rover. Keep rover 5 to 10 meters behind astronaut on climbs exceeding 12°.",
    ])

    template_markdown = "\n".join(md_lines)

    # Check for optional LLM enhancement via environment key
    llm_markdown = _try_llm_enhancement(
        f"You are CAPCOM flight director for Marswalk. Polish this mission briefing concisely:\n\n{template_markdown}"
    )

    final_markdown = llm_markdown if llm_markdown else template_markdown
    source = "llm" if llm_markdown else "template"

    return {
        "status": status_label,
        "is_go": is_go,
        "briefing_source": source,
        "briefing_markdown": final_markdown,
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
