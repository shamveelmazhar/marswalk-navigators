import { TerrainGrid, AGENTS } from "./terrain.js";
import { pathStats, walkBudget, driveBudget, loadCases, casesToCsv, ROVER_DEFAULTS, EVA_HOURS, SOL_HOURS } from "./physics.js";
import { lineChart } from "./charts.js";
import { chapters, initHero } from "./hero.js";
import { MapView } from "./map.js";
import { fetchRoute, fetchBriefing, apiBase } from "./api.js";

const $ = (s, root = document) => root.querySelector(s);
const fmt = (n, d = 0) => Number(n).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });

const state = {
  site: null, grid: null, map: null,
  points: [],                 // [A, B] as [lat, lon]
  agent: "astronaut",
  routes: { astronaut: null, rover: null },
  rover: { ...ROVER_DEFAULTS },
  activeStop: null,
};

initNav();
boot().catch((err) => {
  console.error(err);
  $(".route-status").textContent = "The map data didn't load. Serve this folder over http (see web/README.md) and reload.";
  $(".route-status").classList.add("warn");
});

async function boot() {
  const [site, traverse] = await Promise.all([
    fetch("data/site.json").then((r) => r.json()),
    fetch("data/traverse.json").then((r) => r.json()),
  ]);
  site.traverse = traverse;
  state.site = site;
  document.querySelectorAll('[data-stat="rad_readings"]').forEach((n) => (n.textContent = fmt(site.stats.rad_readings)));

  initHero(chapters(site.stats, state.rover));
  state.grid = await TerrainGrid.load(site.grid, "data/grid.bin");

  state.map = new MapView(site, state.grid, { onPick: pick, onStop: selectStop });
  initRoutePanel();
  initStops();
  initHazardBars();
  initRoverForm();
  drawDoseChart();
  initAiBriefing();
  $(".source-note").textContent = apiBase()
    ? `Routes come from the team planner at ${apiBase()}. If it doesn't answer, the browser works them out instead.`
    : "Routes are worked out in your browser on a 20 m terrain grid.";

  // start with a climb from Curiosity's 2022 path at the bottom of the area up to the boxwork
  const first = traverse.find((p) => state.grid.sample(p[0], p[1]));
  const mid = site.stops[Math.floor(site.stops.length / 2)];
  setPoints([[first[0], first[1]], [mid.lat, mid.lon]]);

  let resizeT;
  window.addEventListener("resize", () => {
    clearTimeout(resizeT);
    resizeT = setTimeout(() => { renderRoutePanel(); drawDoseChart(); state.map.invalidate(); }, 150);
  });
}

/* ---------- nav ---------- */
function initNav() {
  const nav = $(".nav");
  const toggle = $(".nav-toggle");
  const drawer = $("#drawer");
  const onScroll = () => nav.classList.toggle("scrolled", window.scrollY > 40);
  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();
  const setOpen = (open) => {
    toggle.setAttribute("aria-expanded", String(open));
    toggle.setAttribute("aria-label", open ? "Close menu" : "Open menu");
    drawer.hidden = !open;
    document.body.style.overflow = open ? "hidden" : "";
  };
  toggle.addEventListener("click", () => setOpen(drawer.hidden));
  drawer.addEventListener("click", (e) => { if (e.target.closest("a")) setOpen(false); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !drawer.hidden) setOpen(false); });

  // underline the section you're reading
  const links = [...document.querySelectorAll(".nav-links a")];
  const io = new IntersectionObserver((entries) => {
    for (const en of entries) {
      if (!en.isIntersecting) continue;
      links.forEach((a) => a.classList.toggle("active", a.getAttribute("href") === `#${en.target.id}`));
    }
  }, { rootMargin: "-45% 0px -50% 0px" });
  document.querySelectorAll("main > section[id]").forEach((s) => io.observe(s));
}

/* ---------- picking and planning ---------- */
function pick(arg, replaceAll) {
  if (replaceAll) return setPoints(arg);
  const pts = state.points.length >= 2 ? [arg] : [...state.points, arg];
  setPoints(pts);
}

let planToken = 0;
async function setPoints(points) {
  state.points = points;
  state.map.setPins(points);
  if (points.length < 2) {
    state.routes = { astronaut: null, rover: null };
    for (const a of Object.keys(AGENTS)) state.map.setRoute(a, null);
    $(".route-status").textContent = "Now click where the walk should end.";
    $(".route-status").classList.remove("warn");
    renderRoutePanel();
    return;
  }
  const token = ++planToken;
  $(".route-status").textContent = "Planning…";
  const results = {};
  for (const agent of Object.keys(AGENTS)) {
    results[agent] = (await fetchRoute(points[0], points[1], agent)) || state.grid.plan(points[0], points[1], agent);
  }
  if (token !== planToken) return; // a newer click won
  for (const agent of Object.keys(AGENTS)) {
    const r = results[agent];
    if (r.ok) {
      const pts = state.grid.profile(r.latlngs);
      r.pts = pts;
      r.stats = pathStats(pts);
    }
    state.routes[agent] = r;
  }
  drawRoutes();
  renderAll();
}

function drawRoutes() {
  for (const agent of Object.keys(AGENTS)) {
    const r = state.routes[agent];
    state.map.setRoute(agent, r?.ok ? r.latlngs : null, agent === state.agent);
  }
}

function renderAll() {
  renderRoutePanel();
  renderBudgets();
  renderFea();
}

/* ---------- route panel ---------- */
function initRoutePanel() {
  $(".seg").addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    state.agent = b.dataset.agent;
    document.querySelectorAll(".seg button").forEach((x) => x.setAttribute("aria-checked", String(x === b)));
    drawRoutes();
    renderRoutePanel();
  });
  $(".route-actions").addEventListener("click", (e) => {
    const a = e.target.closest("button")?.dataset.action;
    if (a === "swap" && state.points.length === 2) setPoints([state.points[1], state.points[0]]);
    if (a === "clear") {
      state.points = [];
      state.map.setPins([]);
      state.routes = { astronaut: null, rover: null };
      drawRoutes();
      $(".route-status").textContent = "Click the map to set a start point.";
      $(".route-status").classList.remove("warn");
      renderAll();
    }
  });
}

function renderRoutePanel() {
  const r = state.routes[state.agent];
  const status = $(".route-status");
  const kv = $(".route-kv");
  if (!r) {
    kv.innerHTML = "";
    lineChart($("#profile-chart"), { xs: [], ys: [], emptyText: "Pick two points to see the climb." });
    return;
  }
  if (!r.ok) {
    status.textContent = r.reason;
    status.classList.add("warn");
    kv.innerHTML = "";
    lineChart($("#profile-chart"), { xs: [], ys: [], emptyText: "No route to profile." });
    return;
  }
  status.classList.remove("warn");
  const s = r.stats;
  const who = AGENTS[state.agent].label.toLowerCase();
  status.textContent = `Safest ${who} route${r.source === "api" ? " from the team planner" : ""}.`;
  const rows = [
    ["Distance", `${fmt(s.distM / 1000, 2)} km`],
    ["Climb / descent", `${fmt(s.climbM)} / ${fmt(s.descentM)} m`],
    ["Steepest ground crossed", `${fmt(s.maxSlopeDeg)}°`],
    ["Roughest ground crossed", `${fmt(s.maxRoughM, 1)} m`],
  ];
  if (state.agent === "astronaut") {
    const w = walkBudget(r.pts, state.site.stats.dose_uGy_h);
    rows.push(["Walking time", hm(w.hours)]);
  } else {
    const d = driveBudget(r.pts, state.rover);
    rows.push(["Driving time", hm(d.hours)]);
  }
  kv.innerHTML = rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("");

  const step = Math.max(1, Math.floor(r.pts.length / 240));
  const pts = r.pts.filter((_, i) => i % step === 0 || i === r.pts.length - 1);
  const color = state.agent === "astronaut" ? "#f3eee8" : "#5ad1ff";
  lineChart($("#profile-chart"), {
    xs: pts.map((p) => p.d / 1000), ys: pts.map((p) => p.elev), color, height: 150,
    xFmt: (v) => `${fmt(v, v < 1 && v > 0 ? 1 : 1)} km`, yFmt: (v) => fmt(v),
    tipFmt: (x, y, i) => `${fmt(x, 2)} km · ${fmt(y)} m · ${pts[i].slope}°`,
  });
}

const hm = (h) => {
  const H = Math.floor(h), M = Math.round((h - H) * 60);
  return H ? `${H} h ${String(M).padStart(2, "0")} min` : `${M} min`;
};

/* ---------- stops ---------- */
function initStops() {
  const rail = $(".stop-rail");
  rail.innerHTML = state.site.stops.map((s) => `
    <button class="stop-card" role="listitem" aria-pressed="false" data-id="${s.id}">
      <div class="thumb" style="background-image:url('${s.photos[0]?.url ?? ""}')"></div>
      <div class="meta"><b>${s.name}</b><span>Sol ${s.sols[0]} · ${fmt(s.elev_m)} m</span></div>
    </button>`).join("");
  rail.addEventListener("click", (e) => {
    const b = e.target.closest(".stop-card");
    if (b) selectStop(+b.dataset.id, true);
  });
}

function selectStop(id, fly = false) {
  const s = state.site.stops.find((x) => x.id === id);
  state.activeStop = id;
  document.querySelectorAll(".stop-card").forEach((c) => c.setAttribute("aria-pressed", String(+c.dataset.id === id)));
  state.map.highlightStop(id);
  if (fly) state.map.flyTo([s.lat, s.lon]);
  const cam = (c) => (c.startsWith("MAST") ? "Mastcam" : "Navcam");
  const solText = s.sols[0] === s.sols[1] ? `sol ${s.sols[0]}` : `sols ${s.sols[0]} to ${s.sols[1]}`;
  $(".stop-detail").innerHTML = `
    <div class="panel stop-panel">
      <div>
        <h3>${s.name}</h3>
        <p class="muted small">Curiosity parked here on ${solText} and took ${fmt(s.photo_count)} pictures.</p>
        <dl class="kv">
          <dt>Height</dt><dd>${fmt(s.elev_m)} m</dd>
          <dt>Rover tilt nearby</dt><dd>${fmt(s.rover_tilt_deg, 1)}°</dd>
          <dt>Dose rate those sols</dt><dd>${s.dose_uGy_h ? `${fmt(s.dose_uGy_h, 2)} µGy/h` : "not measured"}</dd>
          <dt>Position</dt><dd>${fmt(Math.abs(s.lat), 4)}° S, ${fmt(s.lon, 4)}° E</dd>
        </dl>
        <button class="btn" data-go="${s.id}">Walk here from A</button>
      </div>
      <div class="stop-photos">
        ${s.photos.map((p) => `<a href="${p.url}" target="_blank" rel="noopener" style="background-image:url('${p.url}')" aria-label="${cam(p.camera)} photo from sol ${p.sol}, opens full size"><span>${cam(p.camera)} · sol ${p.sol}</span></a>`).join("")}
      </div>
    </div>`;
  $(".stop-detail [data-go]").addEventListener("click", () => {
    const a = state.points[0] || [state.site.stops[0].lat, state.site.stops[0].lon];
    setPoints([a, [s.lat, s.lon]]);
    $("#map").scrollIntoView({ behavior: "smooth" });
  });
}

/* ---------- planning section ---------- */
function initHazardBars() {
  const h = state.site.stats.hazard_share;
  const rows = [["Go", "var(--go)", h[0]], ["Caution", "var(--caution)", h[1]], ["No-go", "var(--nogo)", h[2]]];
  $(".hazard-bars").innerHTML = `<p class="mini-title">How the study area sorts out</p>` + rows.map(([k, c, v]) => `
    <div class="hbar"><span class="lab"><i style="background:${c}"></i>${k}</span>
    <span class="track"><span class="fill" style="width:${(v * 100).toFixed(1)}%;background:${c}"></span></span>
    <span class="val">${fmt(v * 100)}%</span></div>`).join("");

  // sanity check: where did Curiosity itself actually drive?
  const counts = [0, 0, 0];
  let n = 0;
  for (const p of state.site.traverse) {
    const c = state.grid.sample(p[0], p[1]);
    if (!c) continue;
    counts[state.grid.hazardClass(c, state.site.limits)]++;
    n++;
  }
  if (n) {
    $(".check-note").textContent = `As a check, we ran Curiosity's own path through the same rules: ${fmt((counts[0] / n) * 100)}% of it sits on ground we call go, ${fmt((counts[1] / n) * 100)}% on caution and ${fmt((counts[2] / n) * 100)}% on no-go. Most of that no-go share is short ridge crossings the rover's drivers planned by hand, which is exactly the ground our planner is meant to flag.`;
  }
}

/* ---------- budgets ---------- */
function renderBudgets() {
  const grid = $(".budget-grid");
  const a = state.routes.astronaut, r = state.routes.rover;
  const dash = "–";
  const w = a?.ok ? walkBudget(a.pts, state.site.stats.dose_uGy_h) : null;
  const d = r?.ok ? driveBudget(r.pts, state.rover) : null;
  const items = [
    { k: "Walking time, one way", v: w ? hm(w.hours) : dash, p: `Out and back fits in one ${EVA_HOURS} hour spacewalk if this stays under half.`, meter: w && w.evaShare },
    { k: "Distance on foot", v: w ? fmt(a.stats.dist3dM / 1000, 2) : dash, u: "km", p: w ? `Including ${fmt(a.stats.climbM)} m of climbing and ${fmt(a.stats.descentM)} m down.` : "" },
    { k: "Energy burned", v: w ? fmt(w.kcal) : dash, u: "kcal", p: "Pandolf's walking equation, scaled to Mars gravity, for a person and a 70 kg suit." },
    { k: "Oxygen used", v: w ? fmt(w.o2Kg, 2) : dash, u: "kg", p: "Metabolic oxygen only. Suits carry about 0.5 to 1 kg for a full spacewalk." },
    { k: "Radiation dose", v: w ? fmt(w.doseUGy, 1) : dash, u: "µGy", p: w ? `${fmt((w.hours / SOL_HOURS) * 100, 1)}% of a full sol outside, at the ${state.site.stats.dose_uGy_h} µGy/h Curiosity measured here.` : "" },
    { k: "Rover route", v: d ? fmt(r.stats.dist3dM / 1000, 2) : dash, u: "km", p: r?.ok ? `The rover's own route. Its steepest ground is ${fmt(r.stats.maxSlopeDeg)}°.` : r ? r.reason : "" },
    { k: "Rover drive energy", v: d ? fmt(d.wh) : dash, u: "Wh", p: "Rolling resistance and climbing, through the drivetrain, plus electronics while driving." },
    { k: "Rover drive time", v: d ? hm(d.hours) : dash, p: `At ${state.rover.speedMs} m/s. Curiosity itself drives at up to 0.04 m/s.` },
  ];
  grid.innerHTML = items.map((it) => `
    <dl class="budget"><dt>${it.k}</dt><dd><div class="big">${it.v}${it.u && it.v !== dash ? `<small>${it.u.replace("µ", '<span class="nu">µ</span>')}</small>` : ""}</div>
    ${it.meter != null ? `<div class="meter${it.meter > 0.5 ? " over" : ""}" role="img" aria-label="${fmt(it.meter * 100)}% of an ${EVA_HOURS} hour spacewalk"><i style="width:${Math.min(100, it.meter * 100)}%"></i></div>` : ""}
    <p>${it.p}</p></dd></dl>`).join("");
}

function drawDoseChart() {
  const rad = state.site.radiation;
  lineChart($("#dose-chart"), {
    xs: rad.map((r) => r.sol), ys: rad.map((r) => r.uGy_h), color: "#b388ff", height: 220, yPad: 0.4,
    xFmt: (v) => `Sol ${v}`, yFmt: (v) => fmt(v, 1),
    tipFmt: (x, y, i) => `Sol ${x} · ${fmt(y, 2)} µGy/h · ${fmt(rad[i].n)} readings`,
  });
}

/* ---------- FEA ---------- */
const ROVER_FIELDS = [
  ["massKg", "Rover mass", "kg", "Curiosity is 899 kg"],
  ["wheels", "Wheels", "", ""],
  ["wheelRadiusM", "Wheel radius", "m", "Curiosity: 0.25 m"],
  ["cgHeightM", "Center of mass height", "m", "Assumed"],
  ["trackM", "Track width", "m", "Left to right wheel, assumed"],
  ["dynamicFactor", "Impact factor", "×", "Extra load for bumps"],
  ["edgePatchMm2", "Rock edge contact", "mm²", "Area a sharp edge loads"],
  ["speedMs", "Drive speed", "m/s", "Used in the budgets"],
];

function initRoverForm() {
  const form = $(".rover-form");
  form.innerHTML = `<h3 class="panel-title">Rover</h3>` + ROVER_FIELDS.map(([k, label, unit, hint]) => `
    <label>${label}
      <span class="field"><input type="number" step="any" min="0" name="${k}" value="${state.rover[k]}" inputmode="decimal">${unit ? `<span class="unit">${unit}</span>` : ""}</span>
      ${hint ? `<span class="hint">${hint}</span>` : ""}
    </label>`).join("");
  form.addEventListener("input", (e) => {
    const v = parseFloat(e.target.value);
    if (!Number.isFinite(v) || v <= 0) return;
    state.rover[e.target.name] = e.target.name === "wheels" ? Math.max(2, Math.round(v)) : v;
    renderBudgets();
    renderFea();
    if (state.agent === "rover") renderRoutePanel();
  });
  form.addEventListener("submit", (e) => e.preventDefault());
  $('[data-action="csv"]').addEventListener("click", downloadCsv);
}

function feaInputs() {
  const r = state.routes.rover;
  return r?.ok ? r.stats : null;
}

function renderFea() {
  const table = $(".fea-table");
  const stats = feaInputs();
  const note = $(".fea-note");
  if (!stats) {
    table.innerHTML = "";
    note.textContent = "Plan a route on the map to get load cases for it.";
    return;
  }
  const cases = loadCases(stats, state.rover);
  table.innerHTML = `
    <thead><tr><th>Case</th><th>Normal F<sub>z</sub></th><th>Along F<sub>x</sub></th><th>Side F<sub>y</sub></th><th>Total</th><th>Edge pressure</th></tr></thead>
    <tbody>${cases.map((c) => `
      <tr class="${c.worst ? "worst" : ""}">
        <td><b>${c.id} · ${c.name}</b><span>${c.note}</span></td>
        <td>${fmt(c.fz)} N</td><td>${fmt(c.fx)} N</td><td>${fmt(c.fy)} N</td><td><b>${fmt(c.total)} N</b></td>
        <td>${c.pressureMPa ? `${fmt(c.pressureMPa, 2)} MPa` : "–"}</td>
      </tr>`).join("")}</tbody>`;
  const worst = cases.find((c) => c.worst);
  note.textContent = `Worst ground on the rover's route: ${fmt(stats.maxSlopeDeg)}° slope and ${fmt(stats.maxRoughM, 1)} m of roughness. The highlighted row, ${worst.id}, is the one to run first in Ansys or SolidWorks. Apply it at the contact patch with the hub fixed.`;
}

function downloadCsv() {
  const stats = feaInputs();
  if (!stats) return;
  const csv = casesToCsv(loadCases(stats, state.rover), stats, state.rover);
  const url = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
  const a = Object.assign(document.createElement("a"), { href: url, download: "marswalk-wheel-load-cases.csv" });
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}


/* ---------- AI mission briefing ---------- */
function initAiBriefing() {
  const btn = $("#btn-ai-briefing");
  const out = $("#ai-briefing-output");
  if (!btn || !out) return;

  btn.addEventListener("click", async () => {
    if (state.points.length < 2) {
      out.style.display = "block";
      out.innerHTML = `<span style="color:#ffb74d;">⚠️ Please click start and target points on the map first to plan a route before generating a mission briefing.</span>`;
      return;
    }

    btn.disabled = true;
    btn.textContent = "Synthesizing Briefing...";
    out.style.display = "block";
    out.innerHTML = `<span class="muted">Contacting Marswalk AI Route Assistant...</span>`;

    const briefing = await fetchBriefing(state.points[0], state.points[1], state.agent);
    btn.disabled = false;
    btn.textContent = "Generate Mission Briefing";

    if (briefing && briefing.briefing_markdown) {
      out.innerHTML = briefing.briefing_markdown
        .replace(/^# (.*$)/gim, '<h2 style="color:#ffab91; margin:0.5rem 0;">$1</h2>')
        .replace(/^## (.*$)/gim, '<h3 style="color:#ffe082; margin:0.75rem 0 0.25rem;">$1</h3>')
        .replace(/\*\*(.*?)\*\*/gim, '<b>$1</b>')
        .replace(/`(.*?)`/gim, '<code style="background:rgba(255,255,255,0.1); padding:2px 4px; border-radius:3px;">$1</code>');
    } else {
      const a = state.routes.astronaut;
      const dist = a?.ok ? (a.stats.dist3dM / 1000).toFixed(2) : "–";
      const slope = a?.ok ? a.stats.maxSlopeDeg.toFixed(1) : "–";
      out.innerHTML = `
        <h3 style="color:#ffab91; margin:0 0 0.5rem;">🔴 Mission Briefing (Browser Fallback)</h3>
        <p><b>Status:</b> GO FOR EVA | <b>Traverse:</b> ${dist} km</p>
        <p><b>Terrain & Hazards:</b> Maximum route slope is <b>${slope}°</b>. Boxwork ridge crests require deliberate footing. Life-support consumables and rover traction remain within safe EVA margins.</p>
        <p class="muted small">Tip: Connect the hosted FastAPI backend to enable real-time server-side AI flight briefings.</p>
      `;
    }
  });
}
