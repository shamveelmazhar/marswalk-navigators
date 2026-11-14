// The Leaflet map: data layers, legend, Curiosity's path, stops and routes.
/* global L */

const LAYERS = [
  { key: "traverse", name: "Curiosity's path", sub: "The real drive through this area", kind: "vector", on: true },
  { key: "radiation", name: "Radiation", sub: "RAD dose rate where Curiosity measured it", kind: "vector", on: false },
  { key: "hazard", name: "Hazard", sub: "Go, caution or no-go from slope and roughness", kind: "image", on: true, opacity: 0.55 },
  { key: "slope", name: "Slope", sub: "How steep the ground is, over 10 m", kind: "image", on: false, opacity: 0.85 },
  { key: "thermal", name: "Night infrared", sub: "THEMIS, warm means firm rock", kind: "image", on: false, opacity: 0.8 },
  { key: "terrain", name: "Terrain", sub: "Shaded height map, HiRISE 2 m", kind: "image", on: false, opacity: 1 },
  { key: "photo", name: "Surface photo", sub: "HiRISE, 1 m per pixel", kind: "image", on: true, opacity: 1 },
];

const DOSE_RAMP = ["#ece2ff", "#c9adff", "#a37bff", "#7b4ae6", "#5527b8"];

export class MapView {
  constructor(site, grid, { onPick, onStop }) {
    this.site = site;
    this.grid = grid;
    this.onPick = onPick;
    this.onStop = onStop;
    this.layers = {};
    this.routeLayers = {};
    this.pins = [];

    const [[s, w], [n, e]] = site.layers.photo;
    const tb = site.layers.thermal;
    this.map = L.map("leaflet", {
      zoomSnap: 0.25, zoomControl: false, attributionControl: true, minZoom: 11, maxZoom: 18,
      maxBounds: L.latLngBounds(tb).pad(0.05), preferCanvas: false,
    });
    this.map.fitBounds([[s, w], [n, e]], { padding: [10, 10] });
    this.map.attributionControl.setPrefix(false);
    this.map.attributionControl.addAttribution("NASA/JPL-Caltech/Univ. of Arizona, USGS, ASU");
    L.control.zoom({ position: "topright" }).addTo(this.map);
    L.control.scale({ metric: true, imperial: false, maxWidth: 120, position: "bottomright" }).addTo(this.map);
    this.map.createPane("routes").style.zIndex = 450;

    this.buildLayers();
    this.buildLayerList();
    this.buildStops();
    this.buildReadout();
    this.map.on("click", (ev) => this.onPick([ev.latlng.lat, ev.latlng.lng]));
  }

  buildLayers() {
    for (const def of LAYERS) {
      if (def.kind === "image") {
        this.layers[def.key] = L.imageOverlay(`assets/layers/${def.key}.webp`, this.site.layers[def.key], {
          opacity: def.opacity, interactive: false, className: `ov-${def.key}`,
        });
      }
    }
    // keep the stacking order sensible no matter what is toggled
    const z = { photo: 1, terrain: 2, thermal: 3, slope: 4, hazard: 5 };
    for (const [k, v] of Object.entries(z)) this.layers[k]?.on("add", (ev) => ev.target.getElement() && (ev.target.getElement().style.zIndex = v));

    const path = this.site.traverse.map((p) => [p[0], p[1]]);
    this.layers.traverse = L.layerGroup([
      L.polyline(path, { color: "#000", weight: 5, opacity: 0.45, interactive: false }),
      L.polyline(path, { color: "#ffb27a", weight: 2, opacity: 0.95, dashArray: "1 5", lineCap: "round", interactive: false }),
    ]);

    const doseBySol = new Map(this.site.radiation.map((r) => [r.sol, r.uGy_h]));
    const vals = this.site.radiation.map((r) => r.uGy_h);
    this.doseMin = Math.min(...vals);
    this.doseMax = Math.max(...vals);
    const pts = this.site.waypoints.filter((w) => doseBySol.has(w.sol));
    this.layers.radiation = L.layerGroup(pts.map((w) => {
      const v = doseBySol.get(w.sol);
      const t = (v - this.doseMin) / (this.doseMax - this.doseMin || 1);
      return L.circleMarker([w.lat, w.lon], {
        radius: 6, weight: 1.5, color: "#0b0b0e", fillColor: DOSE_RAMP[Math.min(4, Math.floor(t * 5))], fillOpacity: 0.95,
      }).bindTooltip(`Sol ${w.sol} · ${v.toFixed(2)} µGy/h`, { className: "mw-tip", direction: "top", offset: [0, -6] });
    }));
  }

  buildLayerList() {
    const list = document.querySelector(".layer-list");
    list.innerHTML = LAYERS.map((d) => `
      <li class="layer-item${d.on ? " on" : ""}" data-key="${d.key}">
        <label class="layer-row">
          <input type="checkbox" ${d.on ? "checked" : ""} aria-describedby="sub-${d.key}">
          <span class="switch" aria-hidden="true"></span>
          <span><span class="layer-name">${d.name}</span><span class="layer-sub" id="sub-${d.key}">${d.sub}</span></span>
        </label>
        ${d.kind === "image" ? `<input class="opacity" type="range" min="0" max="1" step="0.05" value="${d.opacity}" aria-label="${d.name} opacity">` : ""}
      </li>`).join("");

    list.addEventListener("change", (e) => {
      const li = e.target.closest(".layer-item");
      if (!li || !e.target.matches('input[type="checkbox"]')) return;
      this.setLayer(li.dataset.key, e.target.checked);
    });
    list.addEventListener("input", (e) => {
      if (!e.target.matches(".opacity")) return;
      this.layers[e.target.closest(".layer-item").dataset.key].setOpacity(+e.target.value);
    });
    for (const d of LAYERS) if (d.on) this.setLayer(d.key, true);
  }

  setLayer(key, on) {
    const layer = this.layers[key];
    if (on) layer.addTo(this.map); else this.map.removeLayer(layer);
    document.querySelector(`.layer-item[data-key="${key}"]`).classList.toggle("on", on);
    if (key === "radiation" && on) this.layers.radiation.eachLayer((m) => m.bringToFront());
    this.renderLegend();
  }

  renderLegend() {
    const on = (k) => this.map.hasLayer(this.layers[k]);
    const blocks = [];
    if (on("hazard")) {
      const h = this.site.stats.hazard_share;
      blocks.push(`<div class="legend-block"><h5>Hazard, share of area</h5><ul class="legend-keys">
        <li><i style="background:var(--go)"></i>Go · ${(h[0] * 100).toFixed(0)}%</li>
        <li><i style="background:var(--caution)"></i>Caution · ${(h[1] * 100).toFixed(0)}%</li>
        <li><i style="background:var(--nogo)"></i>No-go · ${(h[2] * 100).toFixed(0)}%</li></ul></div>`);
    }
    if (on("slope")) {
      blocks.push(`<div class="legend-block"><h5>Slope</h5><div class="legend-ramp" style="background:linear-gradient(90deg,#ffecc8,#fab05a 43%,#e76028 71%,#961414)"></div>
        <div class="legend-scale"><span>0°</span><span>15°</span><span>25°</span><span>35°+</span></div></div>`);
    }
    if (on("thermal")) {
      blocks.push(`<div class="legend-block"><h5>Night infrared, relative</h5><div class="legend-ramp" style="background:linear-gradient(90deg,#0c0828,#5a146e 30%,#d2463c 60%,#faa028 85%,#fcf0aa)"></div>
        <div class="legend-scale"><span>Loose sand</span><span>Firm rock</span></div></div>`);
    }
    if (on("terrain")) {
      const s = this.site.stats;
      blocks.push(`<div class="legend-block"><h5>Height</h5><div class="legend-ramp" style="background:linear-gradient(90deg,#3c160c,#963e1e 35%,#d68048 70%,#f6d6aa)"></div>
        <div class="legend-scale"><span>${s.elev_min_m.toLocaleString()} m</span><span>${s.elev_max_m.toLocaleString()} m</span></div></div>`);
    }
    if (on("radiation")) {
      blocks.push(`<div class="legend-block"><h5>Dose rate</h5><div class="legend-ramp" style="background:linear-gradient(90deg,${DOSE_RAMP.join(",")})"></div>
        <div class="legend-scale"><span>${this.doseMin.toFixed(1)} µGy/h</span><span>${this.doseMax.toFixed(1)}</span></div></div>`);
    }
    blocks.push(`<div class="legend-block"><h5>On the map</h5><ul class="legend-keys">
      ${on("traverse") ? '<li><i class="line" style="background:#ffb27a"></i>Curiosity\'s path</li>' : ""}
      <li><i class="line" style="background:var(--route-astro)"></i>Astronaut route</li>
      <li><i class="line" style="background:var(--route-rover)"></i>Rover route</li>
      <li><i style="background:#111;border:2px solid var(--accent-2);transform:rotate(45deg) scale(.8)"></i>Science stop</li></ul></div>`);
    document.querySelector(".legend").innerHTML = blocks.join("");
  }

  buildStops() {
    this.stopMarkers = this.site.stops.map((s) => {
      const icon = L.divIcon({ className: "", html: `<div class="stop-pin" data-id="${s.id}"><span>${s.id}</span></div>`, iconSize: [18, 18], iconAnchor: [9, 9] });
      const m = L.marker([s.lat, s.lon], { icon, keyboard: true, title: `${s.name}, sol ${s.sols[0]}`, zIndexOffset: 500 }).addTo(this.map);
      m.on("click", (ev) => { L.DomEvent.stopPropagation(ev); this.onStop(s.id); });
      return m;
    });
  }

  highlightStop(id) {
    document.querySelectorAll(".stop-pin").forEach((p) => p.classList.toggle("active", +p.dataset.id === id));
  }

  flyTo(latlng, zoom = 15.5) { this.map.flyTo(latlng, zoom, { duration: 0.8 }); }

  buildReadout() {
    const box = document.querySelector(".map-readout");
    const lim = this.site.limits;
    const names = ["Go", "Caution", "No-go"];
    this.map.on("mousemove", (ev) => {
      const c = this.grid.sample(ev.latlng.lat, ev.latlng.lng);
      if (!c) { box.classList.remove("on"); return; }
      box.textContent = `${c.elev.toLocaleString()} m · slope ${c.slope}° · rough ${c.rough.toFixed(1)} m · ${names[this.grid.hazardClass(c, lim)]}`;
      box.classList.add("on");
    });
    this.map.on("mouseout", () => box.classList.remove("on"));
  }

  setPins(points) {
    this.pins.forEach((p) => p.remove());
    this.pins = points.map((p, i) => L.marker(p, {
      icon: L.divIcon({ className: "", html: `<div class="pin${i ? " end" : ""}">${i ? "B" : "A"}</div>`, iconSize: [22, 22], iconAnchor: [11, 11] }),
      draggable: true, zIndexOffset: 1000, title: i ? "End" : "Start",
    }).addTo(this.map).on("dragend", (ev) => {
      const ll = ev.target.getLatLng();
      const next = points.slice();
      next[i] = [ll.lat, ll.lng];
      this.onPick(next, true);
    }));
  }

  setRoute(agent, latlngs, active) {
    this.routeLayers[agent]?.remove();
    if (!latlngs) return;
    const color = agent === "astronaut" ? "#ffffff" : "#5ad1ff";
    this.routeLayers[agent] = L.layerGroup([
      L.polyline(latlngs, { pane: "routes", color: "#000", weight: active ? 7 : 5, opacity: active ? 0.55 : 0.35, interactive: false }),
      L.polyline(latlngs, { pane: "routes", color, weight: active ? 3.5 : 2, opacity: active ? 1 : 0.7, dashArray: active ? null : "6 6", interactive: false }),
    ]).addTo(this.map);
  }

  invalidate() { this.map.invalidateSize(); }
}
