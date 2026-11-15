// A small single-series line chart in SVG, with a crosshair and tooltip.

const NS = "http://www.w3.org/2000/svg";
const el = (tag, attrs = {}, parent) => {
  const n = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  if (parent) parent.appendChild(n);
  return n;
};

function niceTicks(min, max, count = 4) {
  const span = max - min || 1;
  const step0 = span / count;
  const mag = 10 ** Math.floor(Math.log10(step0));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= step0) || step0;
  const ticks = [];
  for (let v = Math.ceil(min / step) * step; v <= max + 1e-9; v += step) ticks.push(+v.toFixed(10));
  return ticks;
}

export function lineChart(container, { xs, ys, color = "#fff", height = 160, xFmt = String, yFmt = String, tipFmt, markers = [], yPad = 0.08, area = true, lines = [], emptyText = "Nothing to show yet." }) {
  container.innerHTML = "";
  if (!xs.length) {
    container.innerHTML = `<div class="chart-empty">${emptyText}</div>`;
    return;
  }
  const W = Math.max(260, container.clientWidth || 300);
  const H = height;
  const m = { t: 10, r: 10, b: 22, l: 44 };
  const x0 = Math.min(...xs), x1 = Math.max(...xs);
  // extra series share the x values and the y axis: [{ ys, color, dash }]
  const allY = ys.concat(...lines.map((l) => l.ys));
  let y0 = Math.min(...allY), y1 = Math.max(...allY);
  const pad = (y1 - y0 || 1) * yPad;
  y0 -= pad; y1 += pad;
  const sx = (v) => m.l + ((v - x0) / (x1 - x0 || 1)) * (W - m.l - m.r);
  const sy = (v) => H - m.b - ((v - y0) / (y1 - y0 || 1)) * (H - m.t - m.b);

  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img" });
  const grid = el("g", { class: "grid" }, svg);
  const axis = el("g", { class: "axis" }, svg);
  for (const t of niceTicks(y0, y1, 4)) {
    el("line", { x1: m.l, x2: W - m.r, y1: sy(t), y2: sy(t) }, grid);
    el("text", { x: m.l - 6, y: sy(t) + 3, "text-anchor": "end" }, axis).textContent = yFmt(t);
  }
  for (const t of niceTicks(x0, x1, 5)) {
    el("text", { x: sx(t), y: H - 6, "text-anchor": "middle" }, axis).textContent = xFmt(t);
  }
  el("line", { class: "baseline", x1: m.l, x2: W - m.r, y1: H - m.b, y2: H - m.b }, svg);

  const d = xs.map((x, i) => `${i ? "L" : "M"}${sx(x).toFixed(1)},${sy(ys[i]).toFixed(1)}`).join("");
  if (area) el("path", { class: "area", d: `${d}L${sx(x1)},${H - m.b}L${sx(x0)},${H - m.b}Z`, fill: color }, svg);
  el("path", { class: "series", d, stroke: color }, svg);
  for (const l of lines) {
    const ld = xs.map((x, i) => `${i ? "L" : "M"}${sx(x).toFixed(1)},${sy(l.ys[i]).toFixed(1)}`).join("");
    el("path", { class: "series", d: ld, stroke: l.color, ...(l.dash ? { "stroke-dasharray": l.dash } : {}) }, svg);
  }

  for (const mk of markers) {
    el("circle", { class: "marker", cx: sx(mk.x), cy: sy(mk.y), r: 5, fill: mk.color || color }, svg);
  }

  const cross = el("line", { class: "cross", y1: m.t, y2: H - m.b, visibility: "hidden" }, svg);
  const dot = el("circle", { class: "hover-dot", r: 4.5, fill: color, visibility: "hidden" }, svg);
  const hit = el("rect", { x: m.l, y: 0, width: W - m.l - m.r, height: H, fill: "transparent" }, svg);
  container.appendChild(svg);
  const tip = document.createElement("div");
  tip.className = "tip";
  container.appendChild(tip);

  const move = (evt) => {
    const box = svg.getBoundingClientRect();
    const px = ((evt.clientX - box.left) / box.width) * W;
    let best = 0, bd = Infinity;
    for (let i = 0; i < xs.length; i++) {
      const dd = Math.abs(sx(xs[i]) - px);
      if (dd < bd) { bd = dd; best = i; }
    }
    const cx = sx(xs[best]), cy = sy(ys[best]);
    cross.setAttribute("x1", cx); cross.setAttribute("x2", cx);
    dot.setAttribute("cx", cx); dot.setAttribute("cy", cy);
    cross.setAttribute("visibility", "visible"); dot.setAttribute("visibility", "visible");
    tip.innerHTML = (tipFmt || ((x, y) => `${xFmt(x)} · ${yFmt(y)}`))(xs[best], ys[best], best);
    tip.style.left = `${(cx / W) * 100}%`;
    tip.style.top = `${(cy / H) * box.height}px`;
    tip.classList.add("on");
  };
  const leave = () => {
    cross.setAttribute("visibility", "hidden"); dot.setAttribute("visibility", "hidden");
    tip.classList.remove("on");
  };
  hit.addEventListener("pointermove", move);
  hit.addEventListener("pointerdown", move);
  hit.addEventListener("pointerleave", leave);
}
