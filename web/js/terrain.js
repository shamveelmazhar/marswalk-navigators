// Terrain grid and the in-browser route planner.
//
// The grid is the 20 m version of our elevation, slope and roughness maps
// (built by web/tools/build_web_data.py). The planner is a plain A* search
// over it, the same idea a rover's navigation software uses. When the team's
// planner API is running we ask it instead; this is the fallback so the map
// always works, even offline.

export const AGENTS = {
  astronaut: { label: "Astronaut", maxSlope: 25, maxRough: 2.0, comfortSlope: 15 },
  rover: { label: "Support rover", maxSlope: 20, maxRough: 1.5, comfortSlope: 12 },
};

export class TerrainGrid {
  constructor(meta, buffer) {
    this.w = meta.width;
    this.h = meta.height;
    this.cell = meta.cell_m;
    const [[s, w], [n, e]] = meta.bounds;
    Object.assign(this, { south: s, west: w, north: n, east: e });
    this.dLat = (n - s) / this.h;
    this.dLon = (e - w) / this.w;
    const count = this.w * this.h;
    this.elev = new Int16Array(buffer.slice(0, count * 2));
    this.slope = new Uint8Array(buffer, count * 2, count);
    this.rough = new Uint8Array(buffer, count * 3, count);
  }

  static async load(meta, url) {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`Could not load terrain grid (${res.status})`);
    return new TerrainGrid(meta, await res.arrayBuffer());
  }

  index(lat, lon) {
    const c = Math.floor((lon - this.west) / this.dLon);
    const r = Math.floor((this.north - lat) / this.dLat);
    if (c < 0 || r < 0 || c >= this.w || r >= this.h) return -1;
    return r * this.w + c;
  }

  center(i) {
    const r = Math.floor(i / this.w), c = i % this.w;
    return [this.north - (r + 0.5) * this.dLat, this.west + (c + 0.5) * this.dLon];
  }

  valid(i) {
    return i >= 0 && this.elev[i] !== -32768 && this.slope[i] !== 255 && this.rough[i] !== 255;
  }

  sample(lat, lon) {
    const i = this.index(lat, lon);
    if (!this.valid(i)) return null;
    return { elev: this.elevAt(lat, lon) ?? this.elev[i], slope: this.slope[i], rough: this.rough[i] / 10 };
  }

  // smooth height between cell centers, so profiles don't step every 20 m
  elevAt(lat, lon) {
    const fx = (lon - this.west) / this.dLon - 0.5;
    const fy = (this.north - lat) / this.dLat - 0.5;
    const c = Math.floor(fx), r = Math.floor(fy);
    if (c < 0 || r < 0 || c + 1 >= this.w || r + 1 >= this.h) return null;
    const tx = fx - c, ty = fy - r;
    const at = (rr, cc) => this.elev[rr * this.w + cc];
    const v = [at(r, c), at(r, c + 1), at(r + 1, c), at(r + 1, c + 1)];
    if (v.includes(-32768)) return null;
    return (v[0] * (1 - tx) + v[1] * tx) * (1 - ty) + (v[2] * (1 - tx) + v[3] * tx) * ty;
  }

  // 0 = go, 1 = caution, 2 = no-go, using the same limits as the hazard layer
  hazardClass(cell, limits) {
    if (cell.slope >= limits.slope_nogo || cell.rough >= limits.rough_nogo) return 2;
    if (cell.slope >= limits.slope_caution || cell.rough >= limits.rough_caution) return 1;
    return 0;
  }

  passable(i, agent) {
    return this.valid(i) && this.slope[i] <= agent.maxSlope && this.rough[i] / 10 <= agent.maxRough;
  }

  nearestPassable(i, agent, radius = 8) {
    if (this.passable(i, agent)) return i;
    const r0 = Math.floor(i / this.w), c0 = i % this.w;
    let best = -1, bestD = Infinity;
    for (let dr = -radius; dr <= radius; dr++) {
      for (let dc = -radius; dc <= radius; dc++) {
        const r = r0 + dr, c = c0 + dc;
        if (r < 0 || c < 0 || r >= this.h || c >= this.w) continue;
        const j = r * this.w + c, d = dr * dr + dc * dc;
        if (d < bestD && this.passable(j, agent)) { best = j; bestD = d; }
      }
    }
    return best;
  }

  // A* search. Each step costs its length, stretched by how steep and rough
  // the ground is, plus a little extra for every meter of climbing.
  plan(start, end, agentKey) {
    const agent = AGENTS[agentKey];
    const s = this.nearestPassable(this.index(...start), agent);
    const t = this.nearestPassable(this.index(...end), agent);
    if (s < 0 || t < 0) return { ok: false, reason: "That point is on ground this traveller can't stand on." };

    const n = this.w * this.h;
    const g = new Float64Array(n).fill(Infinity);
    const from = new Int32Array(n).fill(-1);
    const closed = new Uint8Array(n);
    const heap = new MinHeap();
    const tr = Math.floor(t / this.w), tc = t % this.w;
    const hFn = (i) => Math.hypot(Math.floor(i / this.w) - tr, (i % this.w) - tc) * this.cell;

    g[s] = 0;
    heap.push(s, hFn(s));
    const steps = [[-1, 0, 1], [1, 0, 1], [0, -1, 1], [0, 1, 1], [-1, -1, Math.SQRT2], [-1, 1, Math.SQRT2], [1, -1, Math.SQRT2], [1, 1, Math.SQRT2]];

    while (heap.size) {
      const i = heap.pop();
      if (closed[i]) continue;
      if (i === t) break;
      closed[i] = 1;
      const r = Math.floor(i / this.w), c = i % this.w;
      for (const [dr, dc, k] of steps) {
        const rr = r + dr, cc = c + dc;
        if (rr < 0 || cc < 0 || rr >= this.h || cc >= this.w) continue;
        const j = rr * this.w + cc;
        if (closed[j] || !this.passable(j, agent)) continue;
        const len = k * this.cell;
        const sl = this.slope[j] / agent.maxSlope;
        const ro = this.rough[j] / 10 / agent.maxRough;
        const climb = Math.max(0, this.elev[j] - this.elev[i]);
        const cost = len * (1 + 2.5 * sl * sl + 0.6 * ro) + 3 * climb;
        const ng = g[i] + cost;
        if (ng < g[j]) {
          g[j] = ng;
          from[j] = i;
          heap.push(j, ng + hFn(j));
        }
      }
    }
    if (from[t] < 0 && s !== t) return { ok: false, reason: "No safe way through. Try points that aren't walled in by ridges." };

    const cells = [];
    for (let i = t; i !== -1; i = from[i]) cells.push(i);
    cells.reverse();
    const latlngs = cells.map((i) => this.center(i));
    latlngs[0] = start;
    latlngs[latlngs.length - 1] = end;
    return { ok: true, latlngs: smoothPath(latlngs), source: "browser" };
  }

  // Walk along any path and sample the ground every few meters.
  profile(latlngs, every = 10) {
    const pts = [];
    let dist = 0;
    for (let k = 0; k < latlngs.length - 1; k++) {
      const [a, b] = [latlngs[k], latlngs[k + 1]];
      const seg = metersBetween(a, b);
      const n = Math.max(1, Math.round(seg / every));
      for (let j = 0; j < n; j++) {
        const f = j / n;
        const lat = a[0] + (b[0] - a[0]) * f, lon = a[1] + (b[1] - a[1]) * f;
        const cell = this.sample(lat, lon);
        if (cell) pts.push({ lat, lon, d: dist + seg * f, ...cell });
      }
      dist += seg;
    }
    const last = latlngs[latlngs.length - 1];
    const cell = this.sample(...last);
    if (cell) pts.push({ lat: last[0], lon: last[1], d: dist, ...cell });
    return pts;
  }
}

const MARS_R = 3396190;
export function metersBetween(a, b) {
  const toRad = Math.PI / 180;
  const dLat = (b[0] - a[0]) * toRad;
  const dLon = (b[1] - a[1]) * toRad * Math.cos(((a[0] + b[0]) / 2) * toRad);
  return Math.hypot(dLat, dLon) * MARS_R;
}

// Chaikin corner cutting, so the grid staircase reads as a walked line.
function smoothPath(pts, rounds = 2) {
  let p = pts;
  for (let r = 0; r < rounds; r++) {
    if (p.length < 3) break;
    const out = [p[0]];
    for (let i = 0; i < p.length - 1; i++) {
      const [a, b] = [p[i], p[i + 1]];
      out.push([a[0] * 0.75 + b[0] * 0.25, a[1] * 0.75 + b[1] * 0.25]);
      out.push([a[0] * 0.25 + b[0] * 0.75, a[1] * 0.25 + b[1] * 0.75]);
    }
    out.push(p[p.length - 1]);
    p = out;
  }
  return p;
}

class MinHeap {
  constructor() { this.ids = []; this.keys = []; }
  get size() { return this.ids.length; }
  push(id, key) {
    const { ids, keys } = this;
    let i = ids.length;
    ids.push(id); keys.push(key);
    while (i > 0) {
      const p = (i - 1) >> 1;
      if (keys[p] <= key) break;
      ids[i] = ids[p]; keys[i] = keys[p]; i = p;
    }
    ids[i] = id; keys[i] = key;
  }
  pop() {
    const { ids, keys } = this;
    const top = ids[0];
    const id = ids.pop(), key = keys.pop();
    if (ids.length) {
      let i = 0;
      const n = ids.length;
      for (;;) {
        let m = 2 * i + 1;
        if (m >= n) break;
        if (m + 1 < n && keys[m + 1] < keys[m]) m++;
        if (keys[m] >= key) break;
        ids[i] = ids[m]; keys[i] = keys[m]; i = m;
      }
      ids[i] = id; keys[i] = key;
    }
    return top;
  }
}
