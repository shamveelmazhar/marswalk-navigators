// Walk and drive budgets, and wheel load cases for FEA.
// Every assumption is a named constant here so it's easy to argue with.

export const MARS_G = 3.721;   // m/s²
export const EARTH_G = 9.807;
export const SOL_HOURS = 24.66;
export const EVA_HOURS = 8;    // a typical upper limit for one spacewalk

export const ASTRONAUT = {
  bodyKg: 80,
  suitKg: 70,          // suit and life-support backpack, a Mars-class guess
  terrainFactor: 1.3,  // Pandolf terrain factor for loose, rocky ground
  suitSpeedFactor: 0.6 // suited walking is slower than Tobler's hiker
};

export const ROVER_DEFAULTS = {
  massKg: 899,          // Curiosity's mass, used as our support-rover class
  wheels: 6,
  wheelRadiusM: 0.25,   // Curiosity's wheels are 50 cm across
  cgHeightM: 0.9,       // assumed
  trackM: 2.3,          // assumed distance between left and right wheels
  dynamicFactor: 1.5,   // assumed allowance for bumps while driving
  speedMs: 0.1,         // assumed crew-support pace (Curiosity tops out at 0.04)
  rollingCoeff: 0.15,   // assumed for loose rock and sand
  driveEfficiency: 0.55,// motors and gearboxes, assumed
  hotelW: 120,          // avionics and heaters while driving, assumed
  edgePatchMm2: 400     // a sharp rock edge loading a 10 by 40 mm strip, assumed
};

// Tobler's hiking function gives walking speed from grade; we scale it for a suit.
function walkSpeedMs(grade) {
  const kmh = 6 * Math.exp(-3.5 * Math.abs(grade + 0.05));
  return (kmh / 3.6) * ASTRONAUT.suitSpeedFactor;
}

// Pandolf's equation for the metabolic cost of walking with a load, in watts.
// It was fitted on Earth, so we scale the parts that fight gravity by g_Mars/g_Earth.
function metabolicW(speed, grade) {
  const W = ASTRONAUT.bodyKg, L = ASTRONAUT.suitKg, eta = ASTRONAUT.terrainFactor;
  const gr = MARS_G / EARTH_G;
  const G = Math.max(0, grade) * 100;
  const standing = 1.5 * W + 2 * (W + L) * (L / W) ** 2;
  const moving = eta * (W + L) * (1.5 * speed ** 2 + 0.35 * speed * G);
  return 1.5 * W + gr * (standing - 1.5 * W + moving);
}

// Summarise a sampled path (from TerrainGrid.profile) into the numbers we budget.
export function pathStats(pts) {
  let dist3d = 0, climb = 0, descent = 0, maxSlope = 0, maxRough = 0, maxGrade = 0;
  for (let i = 1; i < pts.length; i++) {
    const dx = pts[i].d - pts[i - 1].d;
    const dh = pts[i].elev - pts[i - 1].elev;
    if (dx <= 0) continue;
    dist3d += Math.hypot(dx, dh);
    if (dh > 0) climb += dh; else descent -= dh;
    maxGrade = Math.max(maxGrade, Math.abs(dh / dx));
  }
  for (const p of pts) {
    maxSlope = Math.max(maxSlope, p.slope);
    maxRough = Math.max(maxRough, p.rough);
  }
  return {
    distM: pts.length ? pts[pts.length - 1].d : 0,
    dist3dM: dist3d, climbM: climb, descentM: descent,
    maxSlopeDeg: maxSlope, maxRoughM: maxRough,
    maxGradeDeg: (Math.atan(maxGrade) * 180) / Math.PI,
    startElev: pts[0]?.elev, endElev: pts[pts.length - 1]?.elev,
  };
}

export function walkBudget(pts, doseUGyH) {
  let seconds = 0, joules = 0;
  for (let i = 1; i < pts.length; i++) {
    const dx = pts[i].d - pts[i - 1].d;
    if (dx <= 0) continue;
    const grade = (pts[i].elev - pts[i - 1].elev) / dx;
    const v = walkSpeedMs(grade);
    const dt = Math.hypot(dx, pts[i].elev - pts[i - 1].elev) / v;
    seconds += dt;
    joules += metabolicW(v, grade) * dt;
  }
  const hours = seconds / 3600;
  const kJ = joules / 1000;
  const o2L = kJ / 20.1;            // about 20 kJ of work per liter of oxygen
  return {
    hours, kJ, kcal: kJ / 4.184,
    o2Kg: (o2L * 1.429) / 1000,
    doseUGy: hours * doseUGyH,
    evaShare: hours / EVA_HOURS,
  };
}

export function driveBudget(pts, rover) {
  const m = rover.massKg;
  let joules = 0, metres = 0;
  for (let i = 1; i < pts.length; i++) {
    const dx = pts[i].d - pts[i - 1].d;
    if (dx <= 0) continue;
    const dh = pts[i].elev - pts[i - 1].elev;
    const ds = Math.hypot(dx, dh);
    const th = Math.atan2(dh, dx);
    const force = m * MARS_G * (rover.rollingCoeff * Math.cos(th) + Math.max(0, Math.sin(th)));
    joules += (force * ds) / rover.driveEfficiency;
    metres += ds;
  }
  const hours = metres / rover.speedMs / 3600;
  const wh = joules / 3600 + rover.hotelW * hours;
  return { hours, wh };
}

// Loads on one wheel for each terrain case, in newtons.
// x is along the direction of travel, y is sideways, z is into the ground.
export function loadCases(stats, rover) {
  const { massKg: m, wheels: n, wheelRadiusM: r, cgHeightM: h, trackM: b, dynamicFactor: df } = rover;
  const W = m * MARS_G;
  const w0 = W / n;
  const th = (stats.maxSlopeDeg * Math.PI) / 180;
  const step = Math.min(stats.maxRoughM, 0.5 * r);
  const cases = [];

  cases.push({ id: "LC1", name: "Parked on level ground", note: "Static weight shared evenly",
    fz: w0, fx: 0, fy: 0 });

  cases.push({ id: "LC2", name: `Climbing ${stats.maxSlopeDeg.toFixed(0)}° straight up`, note: "Steepest slope on the route, all wheels pulling",
    fz: w0 * Math.cos(th), fx: w0 * Math.sin(th), fy: 0 });

  const transfer = (W * Math.sin(th) * h) / b / (n / 2);
  const fzDown = w0 * Math.cos(th) + transfer;
  cases.push({ id: "LC3", name: `Across a ${stats.maxSlopeDeg.toFixed(0)}° slope`, note: "Downhill wheel, weight shifts toward it",
    fz: fzDown, fx: 0, fy: fzDown * Math.tan(th) });

  const push = step > 0 ? (w0 * Math.sqrt(step * (2 * r - step))) / (r - step) : 0;
  cases.push({ id: "LC4", name: `Driving onto a ${(step * 100).toFixed(0)} cm ledge`, note: `Ridge edge from roughness, capped at half the wheel radius, ×${df} for impact`,
    fz: w0 * df, fx: push * df, fy: 0 });

  const fzEdge = w0 * df * Math.cos(th);
  cases.push({ id: "LC5", name: "Sharp rock under the skin", note: `Same wheel load through a ${rover.edgePatchMm2} mm² rock edge`,
    fz: fzEdge, fx: 0, fy: 0, pressureMPa: fzEdge / rover.edgePatchMm2 });

  for (const c of cases) c.total = Math.hypot(c.fx, c.fy, c.fz);
  const worst = cases.reduce((a, c) => (c.total > a.total ? c : a));
  worst.worst = true;
  return cases;
}

export function casesToCsv(cases, stats, rover) {
  const head = "case,description,Fz_normal_N,Fx_along_N,Fy_side_N,resultant_N,edge_pressure_MPa";
  const rows = cases.map((c) => [c.id, `"${c.name}"`, c.fz.toFixed(1), c.fx.toFixed(1), c.fy.toFixed(1), c.total.toFixed(1), c.pressureMPa?.toFixed(2) ?? ""].join(","));
  const meta = [
    `# Marswalk Navigators wheel load cases, Mount Sharp boxwork`,
    `# rover mass ${rover.massKg} kg, ${rover.wheels} wheels, wheel radius ${rover.wheelRadiusM} m, Mars gravity ${MARS_G} m/s^2`,
    `# route: ${(stats.distM / 1000).toFixed(2)} km, steepest slope ${stats.maxSlopeDeg.toFixed(1)} deg, roughest ground ${stats.maxRoughM.toFixed(1)} m`,
  ];
  return [...meta, head, ...rows].join("\n");
}
