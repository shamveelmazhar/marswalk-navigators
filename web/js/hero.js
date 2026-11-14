// The full-screen opening section: four chapters you can step through.

const fmt = (n, d = 0) => Number(n).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });

export function chapters(stats, rover) {
  const wheelN = (rover.massKg * 3.721) / rover.wheels;
  return [
    {
      tab: "Mount Sharp",
      eyebrow: "Planning the first Marswalk",
      title: "Mount Sharp",
      text: "A five kilometer mountain in the middle of Gale Crater. Its lower slopes hold a maze of rock ridges left behind by ancient groundwater, and that's where we want to send a crew on foot.",
      image: "assets/img/mount-sharp-PIA19912.jpg",
      position: "center 60%",
      stats: [
        ["Study area", fmt(stats.area_km2), "km²"],
        ["Height range", fmt(stats.relief_m), "m"],
        ["Curiosity drove here", fmt(stats.traverse_km, 1), "km"],
        ["Rover photos", fmt(stats.photos), ""],
      ],
    },
    {
      tab: "Boxwork",
      eyebrow: "Crossing the boxwork ridges",
      title: "Boxwork",
      text: "Low walls of rock criss-cross the ground here like the sides of a box. They are fascinating to a geologist and tricky to a walker: a third of the area is steeper than 15 degrees.",
      image: "assets/img/boxwork-postcard-PIA26680.jpg",
      position: "center 70%",
      stats: [
        ["Median slope", fmt(stats.slope_median_deg, 1), "°"],
        ["Steeper than 15°", fmt(stats.share_over_15 * 100), "%"],
        ["Steeper than 25°", fmt(stats.share_over_25 * 100), "%"],
        ["Max rover tilt", fmt(stats.max_rover_tilt_deg, 1), "°"],
      ],
    },
    {
      tab: "Radiation",
      eyebrow: "Keeping the crew inside the dose budget",
      title: "Radiation",
      text: "Mars has no magnetic field and a thin atmosphere, so cosmic rays reach the ground. Curiosity measured the dose right here, sol after sol, which lets us price every hour a crew spends outside.",
      image: "assets/img/rover-from-orbit-PIA21710.jpg",
      position: "center",
      stats: [
        ["Dose rate", fmt(stats.dose_uGy_h, 1), "µGy/h"],
        ["Per sol outside", fmt(stats.dose_mGy_sol, 2), "mGy"],
        ["Readings", fmt(stats.rad_readings), ""],
        ["Sols measured", `${stats.rad_sols[0]}–${stats.rad_sols[1]}`, ""],
      ],
    },
    {
      tab: "Rover",
      eyebrow: "Keeping the wheels in one piece",
      title: "Rover",
      text: "A support rover carries tools, samples and spare oxygen. Curiosity's wheels were torn up by sharp rock on this mountain, so we check the hardware against the ground before we pick a route.",
      image: "assets/img/rover-selfie-PIA19142.jpg",
      position: "center 45%",
      stats: [
        ["Rover mass", fmt(rover.massKg), "kg"],
        ["Load per wheel", fmt(wheelN), "N"],
        ["Mars gravity", "3.72", "m/s²"],
        ["Wheel diameter", fmt(rover.wheelRadiusM * 200), "cm"],
      ],
    },
  ];
}

const unit = (u) => u.replace("µ", '<span class="nu">µ</span>');
const statHtml = (s) =>
  s.map(([k, v, u]) => `<div><dt>${k}</dt><dd>${v}${u ? `<small>${unit(u)}</small>` : ""}</dd></div>`).join("");

export function initHero(list) {
  const hero = document.querySelector(".hero");
  const bg = hero.querySelector(".hero-bg");
  const tabs = hero.querySelector(".hero-tabs");
  const dots = hero.querySelector(".hero-dots");
  const q = (s) => hero.querySelector(s);
  let current = -1;
  let timer;

  // preload so the cross-fade never flashes an empty frame
  list.forEach((c) => { const i = new Image(); i.src = c.image; });

  tabs.innerHTML = list.map((c, i) => `<button role="tab" aria-selected="false" data-i="${i}">${c.tab}</button>`).join("");
  dots.innerHTML = list.map(() => "<i></i>").join("");
  document.querySelector(".mobile-stats .stat-grid").innerHTML = statHtml(list[0].stats);

  function show(i, instant = false) {
    i = (i + list.length) % list.length;
    if (i === current) return;
    const c = list[i];
    const apply = () => {
      q(".hero-eyebrow").textContent = c.eyebrow;
      q(".hero-title").textContent = c.title;
      q(".hero-text").textContent = c.text;
      q(".hero-stats").innerHTML = statHtml(c.stats);
      q(".hero-index").textContent = `${i + 1}/${list.length}`;
      bg.style.backgroundImage = `url("${c.image}")`;
      bg.style.backgroundPosition = c.position;
      bg.classList.remove("settled");
      requestAnimationFrame(() => requestAnimationFrame(() => bg.classList.add("settled")));
      bg.classList.remove("swap");
      hero.classList.remove("leaving");
    };
    tabs.querySelectorAll("button").forEach((b, k) => b.setAttribute("aria-selected", String(k === i)));
    dots.querySelectorAll("i").forEach((d, k) => d.classList.toggle("on", k === i));
    current = i;
    if (instant) return apply();
    hero.classList.add("leaving");
    bg.classList.add("swap");
    clearTimeout(timer);
    timer = setTimeout(apply, 380);
  }

  tabs.addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) show(+b.dataset.i); });
  hero.querySelectorAll(".round-btn").forEach((b) => b.addEventListener("click", () => show(current + +b.dataset.dir)));
  hero.addEventListener("keydown", (e) => {
    if (e.key === "ArrowRight") show(current + 1);
    if (e.key === "ArrowLeft") show(current - 1);
  });

  // swipe between chapters on phones
  let x0 = null;
  hero.addEventListener("touchstart", (e) => { x0 = e.touches[0].clientX; }, { passive: true });
  hero.addEventListener("touchend", (e) => {
    if (x0 === null) return;
    const dx = e.changedTouches[0].clientX - x0;
    if (Math.abs(dx) > 50) show(current + (dx < 0 ? 1 : -1));
    x0 = null;
  });

  show(0, true);
}
