// Optional link to the team's route-planner API (FastAPI).
//
// Point the page at it with ?api=http://localhost:8000 in the URL, or by
// setting window.MARSWALK_API before the scripts load. Without it, or if the
// call fails, the map plans routes in the browser instead.
//
// Expected endpoint:
//   GET {api}/route?start_lat=..&start_lon=..&end_lat=..&end_lon=..&agent=astronaut|rover
// Answer with either a GeoJSON LineString (Feature or bare geometry, [lon, lat] pairs)
// or {"path": [[lat, lon], ...]}. Return 4xx with {"detail": "..."} when there is no route.

export function apiBase() {
  const fromUrl = new URLSearchParams(location.search).get("api");
  return (fromUrl || window.MARSWALK_API || "").replace(/\/$/, "") || null;
}

export async function fetchRoute(start, end, agent) {
  const base = apiBase();
  if (!base) return null;
  const q = new URLSearchParams({ start_lat: start[0], start_lon: start[1], end_lat: end[0], end_lon: end[1], agent });
  try {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), 8000);
    const res = await fetch(`${base}/route?${q}`, { signal: ctrl.signal });
    clearTimeout(t);
    const body = await res.json().catch(() => ({}));
    if (res.status >= 400 && res.status < 500) return { ok: false, reason: body.detail || "The planner found no safe route.", source: "api" };
    if (!res.ok) return null;
    const latlngs = toLatLngs(body);
    return latlngs ? { ok: true, latlngs, source: "api" } : null;
  } catch {
    return null; // planner offline, fall back quietly
  }
}

export async function fetchBriefing(start, end, agent = "astronaut") {
  const base = apiBase();
  if (!base) return null;
  const q = new URLSearchParams({ start_lat: start[0], start_lon: start[1], end_lat: end[0], end_lon: end[1], agent });
  try {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), 8000);
    const res = await fetch(`${base}/briefing?${q}`, { signal: ctrl.signal });
    clearTimeout(t);
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

function toLatLngs(body) {
  if (Array.isArray(body?.path)) return body.path.map((p) => [p[0], p[1]]);
  const geom = body?.type === "Feature" ? body.geometry : body;
  if (geom?.type === "LineString") return geom.coordinates.map((c) => [c[1], c[0]]);
  return null;
}
