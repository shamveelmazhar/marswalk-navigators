"""Route planner engine for Marswalk Navigators.

Performs A* pathfinding over HiRISE elevation, slope, and roughness grids
for Gale Crater / Mount Sharp, with agent-specific slope limits and hazard costs.
"""
import os
import math
import heapq
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
import numpy as np

from marswalk.site import GALE_BOXWORK, xy_to_lonlat, lonlat_to_xy, MARS_RADIUS_M


@dataclass(frozen=True)
class MobilityProfile:
    """Mobility limits and cost parameters for an agent."""
    name: str
    max_slope_deg: float
    max_roughness_m: float
    comfort_slope_deg: float
    caution_roughness_m: float
    nominal_speed_kmh: float
    max_speed_kmh: float
    notes: str
    metabolic_rate_w: Optional[float] = None
    solar_budget_wh_per_sol: Optional[float] = None


PROFILES: Dict[str, MobilityProfile] = {
    "astronaut": MobilityProfile(
        name="Astronaut (EVA on foot)",
        max_slope_deg=25.0,
        max_roughness_m=2.0,
        comfort_slope_deg=15.0,
        caution_roughness_m=1.0,
        nominal_speed_kmh=3.6,
        max_speed_kmh=4.5,
        notes="Higher slope agility than wheeled rover, but strictly limited by life-support EVA duration and cumulative radiation dose.",
        metabolic_rate_w=300.0,
    ),
    "rover": MobilityProfile(
        name="Support Rover (Wheeled)",
        max_slope_deg=20.0,
        max_roughness_m=1.5,
        comfort_slope_deg=12.0,
        caution_roughness_m=0.5,
        nominal_speed_kmh=0.15,
        max_speed_kmh=0.20,
        notes="Wheel slip on steep slopes and wheel wear from sharp bedrock ridges (Gale Crater boxwork) require stricter slope and roughness ceilings.",
        solar_budget_wh_per_sol=900.0,
    ),
}

SQRT2 = math.sqrt(2.0)
# 8-connected grid steps: (delta_row, delta_col, step_cost_multiplier)
NEIGHBOR_STEPS = (
    (-1, 0, 1.0),
    (1, 0, 1.0),
    (0, -1, 1.0),
    (0, 1, 1.0),
    (-1, -1, SQRT2),
    (-1, 1, SQRT2),
    (1, -1, SQRT2),
    (1, 1, SQRT2),
)


class TerrainGrid:
    """20m resolution elevation, slope, and roughness grid over Gale Crater boxwork."""

    def __init__(
        self,
        width: int = 200,
        height: int = 300,
        cell_m: float = 20.0,
        bounds_latlon: Optional[Tuple[float, float, float, float]] = None,
        elev: Optional[np.ndarray] = None,
        slope: Optional[np.ndarray] = None,
        rough: Optional[np.ndarray] = None,
    ):
        self.w = width
        self.h = height
        self.cell_m = cell_m

        if bounds_latlon is None:
            min_lon, min_lat = xy_to_lonlat(GALE_BOXWORK.bounds[0], GALE_BOXWORK.bounds[1])
            max_lon, max_lat = xy_to_lonlat(GALE_BOXWORK.bounds[2], GALE_BOXWORK.bounds[3])
            self.south = min_lat
            self.west = min_lon
            self.north = max_lat
            self.east = max_lon
        else:
            self.south, self.west, self.north, self.east = bounds_latlon

        self.d_lat = (self.north - self.south) / self.h
        self.d_lon = (self.east - self.west) / self.w

        if elev is not None:
            self.elev = elev.reshape((self.h, self.w))
        else:
            self.elev = np.zeros((self.h, self.w), dtype=np.int16)

        if slope is not None:
            self.slope = slope.reshape((self.h, self.w))
        else:
            self.slope = np.zeros((self.h, self.w), dtype=np.uint8)

        if rough is not None:
            self.rough = rough.reshape((self.h, self.w))
        else:
            self.rough = np.zeros((self.h, self.w), dtype=np.uint8)

    @classmethod
    def from_binary_file(cls, path: str, width: int = 200, height: int = 300, cell_m: float = 20.0):
        """Load from pre-built binary grid format."""
        with open(path, "rb") as f:
            buf = f.read()
        count = width * height
        elev = np.frombuffer(buf[: count * 2], dtype=np.int16).copy()
        slope = np.frombuffer(buf[count * 2 : count * 3], dtype=np.uint8).copy()
        rough = np.frombuffer(buf[count * 3 : count * 4], dtype=np.uint8).copy()
        return cls(width=width, height=height, cell_m=cell_m, elev=elev, slope=slope, rough=rough)

    def coord_to_cell(self, lat: float, lon: float) -> Tuple[int, int]:
        """Convert Martian lat/lon to (row, col) indices."""
        c = int(math.floor((lon - self.west) / self.d_lon))
        r = int(math.floor((self.north - lat) / self.d_lat))
        return r, c

    def cell_to_coord(self, r: int, c: int) -> Tuple[float, float]:
        """Convert (row, col) indices to cell center lat/lon."""
        lat = self.north - (r + 0.5) * self.d_lat
        lon = self.west + (c + 0.5) * self.d_lon
        return lat, lon

    def is_in_bounds(self, r: int, c: int) -> bool:
        return 0 <= r < self.h and 0 <= c < self.w

    def is_valid(self, r: int, c: int) -> bool:
        """Check if cell is within grid and not masked by no-data."""
        if not self.is_in_bounds(r, c):
            return False
        return (
            self.elev[r, c] != -32768
            and self.slope[r, c] != 255
            and self.rough[r, c] != 255
        )

    def is_passable(self, r: int, c: int, profile: MobilityProfile) -> bool:
        """Check whether cell can be traversed by the given agent."""
        if not self.is_valid(r, c):
            return False
        return (
            self.slope[r, c] <= profile.max_slope_deg
            and (self.rough[r, c] / 10.0) <= profile.max_roughness_m
        )

    def find_nearest_passable(self, r0: int, c0: int, profile: MobilityProfile, radius: int = 8) -> Optional[Tuple[int, int]]:
        """Find the nearest passable cell within radius if start/end lands on cliff/obstacle."""
        if self.is_passable(r0, c0, profile):
            return r0, c0
        best = None
        best_d = float("inf")
        for dr in range(-radius, radius + 1):
            for dc in range(-radius, radius + 1):
                r, c = r0 + dr, c0 + dc
                if self.is_passable(r, c, profile):
                    d = dr * dr + dc * dc
                    if d < best_d:
                        best = (r, c)
                        best_d = d
        return best

    def get_elevation_bilinear(self, lat: float, lon: float) -> Optional[float]:
        """Sample smooth elevation at exact lat/lon using bilinear interpolation."""
        fx = (lon - self.west) / self.d_lon - 0.5
        fy = (self.north - lat) / self.d_lat - 0.5
        c = int(math.floor(fx))
        r = int(math.floor(fy))
        if c < 0 or r < 0 or c + 1 >= self.w or r + 1 >= self.h:
            return None
        tx = fx - c
        ty = fy - r
        v00 = self.elev[r, c]
        v01 = self.elev[r, c + 1]
        v10 = self.elev[r + 1, c]
        v11 = self.elev[r + 1, c + 1]
        if any(v == -32768 for v in (v00, v01, v10, v11)):
            return None
        return float((v00 * (1 - tx) + v01 * tx) * (1 - ty) + (v10 * (1 - tx) + v11 * tx) * ty)

    def plan_path(
        self,
        start_lat: float,
        start_lon: float,
        end_lat: float,
        end_lon: float,
        agent: str = "astronaut",
    ) -> Dict[str, Any]:
        """A* path planning between start and target coordinates."""
        profile = PROFILES.get(agent, PROFILES["astronaut"])

        start_r, start_c = self.coord_to_cell(start_lat, start_lon)
        end_r, end_c = self.coord_to_cell(end_lat, end_lon)

        start_node = self.find_nearest_passable(start_r, start_c, profile)
        end_node = self.find_nearest_passable(end_r, end_c, profile)

        if start_node is None or end_node is None:
            return {
                "ok": False,
                "reason": f"Start or end position is located in impassable terrain for {profile.name} (slope > {profile.max_slope_deg}° or roughness > {profile.max_roughness_m} m).",
            }

        s_r, s_c = start_node
        t_r, t_c = end_node

        # Check if coordinates were snapped
        start_is_passable = self.is_passable(start_r, start_c, profile)
        end_is_passable = self.is_passable(end_r, end_c, profile)

        snapped_start_coord = list(self.cell_to_coord(s_r, s_c))
        snapped_end_coord = list(self.cell_to_coord(t_r, t_c))

        start_snap_dist = math.hypot(start_r - s_r, start_c - s_c) * self.cell_m
        end_snap_dist = math.hypot(end_r - t_r, end_c - t_c) * self.cell_m
        is_snapped = (not start_is_passable) or (not end_is_passable)

        # Direct Euclidean distance between start and end
        sx, sy = lonlat_to_xy(start_lon, start_lat)
        ex, ey = lonlat_to_xy(end_lon, end_lat)
        direct_dist_m = math.hypot(ex - sx, ey - sy)

        # Same cell target
        if (s_r, s_c) == (t_r, t_c):
            path = [
                [start_lat, start_lon] if start_is_passable else snapped_start_coord,
                [end_lat, end_lon] if end_is_passable else snapped_end_coord,
            ]
            return {
                "ok": True,
                "path": path,
                "coordinates": [[p[1], p[0]] for p in path],
                "direct_distance_m": round(direct_dist_m, 1),
                "route_distance_m": round(direct_dist_m, 1),
                "elevation_gain_m": 0.0,
                "elevation_loss_m": 0.0,
                "min_elevation_m": float(self.elev[s_r, s_c]),
                "max_elevation_m": float(self.elev[s_r, s_c]),
                "max_slope_deg": float(self.slope[s_r, s_c]),
                "mean_slope_deg": float(self.slope[s_r, s_c]),
                "max_roughness_m": round(float(self.rough[s_r, s_c]) / 10.0, 2),
                "mean_roughness_m": round(float(self.rough[s_r, s_c]) / 10.0, 2),
                "agent": agent,
                "snapped": is_snapped,
                "snapped_start": snapped_start_coord,
                "snapped_end": snapped_end_coord,
                "snapped_start_dist_m": round(start_snap_dist, 1),
                "snapped_end_dist_m": round(end_snap_dist, 1),
            }

        # A* Search
        open_set = []
        h_start = math.hypot(s_r - t_r, s_c - t_c) * self.cell_m
        heapq.heappush(open_set, (h_start, 0.0, (s_r, s_c)))

        came_from: Dict[Tuple[int, int], Tuple[int, int]] = {}
        g_score: Dict[Tuple[int, int], float] = {(s_r, s_c): 0.0}
        closed_set = set()

        max_slope = profile.max_slope_deg
        max_rough = profile.max_roughness_m

        found = False

        while open_set:
            _, current_g, current = heapq.heappop(open_set)

            if current in closed_set:
                continue

            if current == (t_r, t_c):
                found = True
                break

            closed_set.add(current)
            r, c = current
            curr_elev = self.elev[r, c]

            for dr, dc, k in NEIGHBOR_STEPS:
                nr, nc = r + dr, c + dc

                # CORNER CUTTING PREVENTION:
                # For diagonal steps, skip if either orthogonal neighbor is impassable.
                # This prevents slipping diagonally between two cliff cells.
                if dr != 0 and dc != 0:
                    if not self.is_passable(r, nc, profile) or not self.is_passable(nr, c, profile):
                        continue

                if (nr, nc) in closed_set:
                    continue
                if not self.is_passable(nr, nc, profile):
                    continue

                step_len = k * self.cell_m
                sl = self.slope[nr, nc] / max_slope
                ro = (self.rough[nr, nc] / 10.0) / max_rough
                next_elev = self.elev[nr, nc]
                climb = max(0, int(next_elev) - int(curr_elev))

                cost = step_len * (1.0 + 2.5 * (sl ** 2) + 0.6 * ro) + 3.0 * climb
                tentative_g = current_g + cost

                if tentative_g < g_score.get((nr, nc), float("inf")):
                    came_from[(nr, nc)] = current
                    g_score[(nr, nc)] = tentative_g
                    h = math.hypot(nr - t_r, nc - t_c) * self.cell_m
                    heapq.heappush(open_set, (tentative_g + h, tentative_g, (nr, nc)))

        if not found:
            return {
                "ok": False,
                "reason": f"No safe route found for {profile.name}. Terrain between points exceeds slope limit ({profile.max_slope_deg}°) or roughness barrier.",
            }

        # Reconstruct path from target to start
        path_cells = [(t_r, t_c)]
        curr = (t_r, t_c)
        while curr in came_from:
            curr = came_from[curr]
            path_cells.append(curr)
        path_cells.reverse()

        # Convert cell centers to coordinates
        coords = [list(self.cell_to_coord(r, c)) for r, c in path_cells]
        # Only pin exact clicked points if they are actually passable,
        # otherwise begin/end at the snapped cell center to avoid crossing a cliff
        if start_is_passable:
            coords[0] = [start_lat, start_lon]
        else:
            coords[0] = snapped_start_coord

        if end_is_passable:
            coords[-1] = [end_lat, end_lon]
        else:
            coords[-1] = snapped_end_coord

        # Compute route metrics strictly from raw A*-verified cells
        metrics = self._calculate_route_metrics_from_cells(path_cells, coords)

        # Smooth path with Chaikin corner-cutting
        smoothed_coords = smooth_path(coords, rounds=2)

        # Verify that all smoothed points remain passable; fall back to raw coords if any point cuts across a cliff
        smoothed_safe = True
        for p in smoothed_coords:
            pr, pc = self.coord_to_cell(p[0], p[1])
            if not self.is_passable(pr, pc, profile):
                smoothed_safe = False
                break

        final_path = smoothed_coords if smoothed_safe else coords

        return {
            "ok": True,
            "agent": agent,
            "direct_distance_m": round(direct_dist_m, 1),
            "route_distance_m": round(metrics["total_dist_m"], 1),
            "elevation_gain_m": round(metrics["elev_gain_m"], 1),
            "elevation_loss_m": round(metrics["elev_loss_m"], 1),
            "min_elevation_m": round(metrics["min_elev_m"], 1),
            "max_elevation_m": round(metrics["max_elev_m"], 1),
            "max_slope_deg": round(metrics["max_slope_deg"], 1),
            "mean_slope_deg": round(metrics["mean_slope_deg"], 1),
            "max_roughness_m": round(metrics["max_roughness_m"], 2),
            "mean_roughness_m": round(metrics["mean_roughness_m"], 2),
            "path": final_path,
            "type": "LineString",
            "coordinates": [[p[1], p[0]] for p in final_path],
            "snapped": is_snapped,
            "snapped_start": snapped_start_coord,
            "snapped_end": snapped_end_coord,
            "snapped_start_dist_m": round(start_snap_dist, 1),
            "snapped_end_dist_m": round(end_snap_dist, 1),
        }

    def _calculate_route_metrics_from_cells(
        self,
        path_cells: List[Tuple[int, int]],
        path_coords: List[List[float]],
    ) -> Dict[str, float]:
        """Compute metrics strictly from the verified cells traversed by A*."""
        total_dist = 0.0
        elev_gain = 0.0
        elev_loss = 0.0

        for i in range(len(path_coords) - 1):
            p1 = path_coords[i]
            p2 = path_coords[i + 1]
            d_lat = math.radians(p2[0] - p1[0])
            d_lon = math.radians(p2[1] - p1[1]) * math.cos(math.radians((p1[0] + p2[0]) / 2.0))
            total_dist += math.hypot(d_lat, d_lon) * MARS_RADIUS_M

        elevations = [float(self.elev[r, c]) for r, c in path_cells]
        slopes = [float(self.slope[r, c]) for r, c in path_cells]
        roughnesses = [float(self.rough[r, c]) / 10.0 for r, c in path_cells]

        for i in range(len(elevations) - 1):
            dz = elevations[i + 1] - elevations[i]
            if dz > 0:
                elev_gain += dz
            else:
                elev_loss += abs(dz)

        return {
            "total_dist_m": total_dist,
            "elev_gain_m": elev_gain,
            "elev_loss_m": elev_loss,
            "min_elev_m": min(elevations) if elevations else 0.0,
            "max_elev_m": max(elevations) if elevations else 0.0,
            "max_slope_deg": max(slopes) if slopes else 0.0,
            "mean_slope_deg": (sum(slopes) / len(slopes)) if slopes else 0.0,
            "max_roughness_m": max(roughnesses) if roughnesses else 0.0,
            "mean_roughness_m": (sum(roughnesses) / len(roughnesses)) if roughnesses else 0.0,
        }


def smooth_path(pts: List[List[float]], rounds: int = 2) -> List[List[float]]:
    """Chaikin's corner-cutting algorithm for path smoothing."""
    p = pts
    for _ in range(rounds):
        if len(p) < 3:
            break
        out = [p[0]]
        for i in range(len(p) - 1):
            a, b = p[i], p[i + 1]
            out.append([a[0] * 0.75 + b[0] * 0.25, a[1] * 0.75 + b[1] * 0.25])
            out.append([a[0] * 0.25 + b[0] * 0.75, a[1] * 0.25 + b[1] * 0.75])
        out.append(p[-1])
        p = out
    return p


# Lazy-loaded default grid singleton
_DEFAULT_GRID: Optional[TerrainGrid] = None


def get_default_grid() -> TerrainGrid:
    """Retrieve or initialize the default Gale Crater boxwork terrain grid.

    Raises FileNotFoundError loudly if the grid data is missing.
    """
    global _DEFAULT_GRID
    if _DEFAULT_GRID is not None:
        return _DEFAULT_GRID

    search_paths = [
        os.path.join(os.path.dirname(__file__), "..", "web", "data", "grid.bin"),
        os.path.join("web", "data", "grid.bin"),
        os.path.join("data", "grid.bin"),
    ]
    for path in search_paths:
        if os.path.isfile(path):
            _DEFAULT_GRID = TerrainGrid.from_binary_file(path)
            return _DEFAULT_GRID

    raise FileNotFoundError(
        "Terrain grid binary file 'grid.bin' not found. "
        "Please ensure 'web/data/grid.bin' exists or run 'python -m web.tools.build_web_data'."
    )
