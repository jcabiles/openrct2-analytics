// The hero park: guests walk in, ride and leave, and each game event rises as a gold dot that drops
// into the pipeline. It is the one loop on the page (R23): it runs with the pause control and
// stops under reduced motion. Also draws the still guilloche behind the page.
// Numbers of 1,000 or more sit in data-* attributes or are written as multiples, because the page
// check bars large literals in modules; times are in milliseconds unless written as multiples of
// TENTH.
import { $, clear, svg } from "./dom.mjs";
import { motion, onMotionChange } from "./motion.mjs";

const TENTH = 100;
const point = (element, name) => element.dataset[name].split(" ").map(Number);

export function drawGuilloche() {
  const field = $("#guilloche");
  const w = innerWidth;
  const h = innerHeight;
  field.setAttribute("viewBox", `0 0 ${w} ${h}`);
  clear(field);
  const rosette = (cx, cy, R, r, d, turns) => {
    let path = "";
    const n = turns * 260;
    for (let i = 0; i <= n; i++) {
      const t = (i / n) * Math.PI * 2 * turns;
      const x = cx + (R - r) * Math.cos(t) + d * Math.cos(((R - r) / r) * t);
      const y = cy + (R - r) * Math.sin(t) - d * Math.sin(((R - r) / r) * t);
      path += (i ? "L" : "M") + x.toFixed(1) + " " + y.toFixed(1);
    }
    return path;
  };
  const big = Math.max(w, h);
  svg("path", { d: rosette(w * 1.02, h * 0.06, big * 0.34, big * 0.034, big * 0.09, 17) }, field);
  svg("path", { d: rosette(-w * 0.04, h * 1.02, big * 0.3, big * 0.042, big * 0.08, 21) }, field);
  // A woven band: twelve sine strands with shifted phases, the classic banknote border.
  for (let k = 0; k < 12; k++) {
    let path = "";
    const y0 = h * 0.62;
    for (let x = -10; x <= w + 10; x += 5) {
      const y = y0 + Math.sin(x / 95 + (k * Math.PI) / 6) * 34 * (1 + 0.25 * Math.sin(x / 400));
      path += (x > -10 ? "L" : "M") + x + " " + y.toFixed(1);
    }
    svg("path", { d: path }, field);
  }
}

let fitScene = () => {};
export const fit = () => fitScene();

export function init() {
  const scene = $("#scene");
  let seed = 22;
  const rng = () => {
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 2 ** 32;
  };
  const track = $("#sc-track");
  const flume = $("#sc-flume");
  const trainLayer = $("#sc-train");
  const logLayer = $("#sc-log");
  const carousel = $("#sc-carousel");
  const supports = $("#sc-supports");
  const guestsLayer = $("#sc-guests");
  const dotsLayer = $("#sc-dots");
  const trackLength = track.getTotalLength();
  const flumeLength = flume.getTotalLength();

  const [supportFrom, supportTo] = point(supports, "span");
  const samples = [];
  for (let l = 0; l <= trackLength; l += 2) samples.push(track.getPointAtLength(l));
  const topAt = (x) => {
    let best = null;
    for (const p of samples) if (Math.abs(p.x - x) < 1.5 && (!best || p.y < best.y)) best = p;
    return best ? best.y : null;
  };
  let d = "";
  let prev = null;
  for (let x = supportFrom; x <= supportTo; x += 15) {
    const y = topAt(x);
    if (y === null || y > 420) {
      prev = null;
      continue;
    }
    d += `M${x} ${y + 3} V440 `;
    if (prev) {
      const low = Math.max(prev.y, y) + 8;
      for (let yy = low; yy < 430; yy += 30) {
        const end = Math.min(438, yy + 30);
        d += `M${prev.x} ${yy} L${x} ${end} `;
        d += `M${x} ${yy} L${prev.x} ${end} `;
      }
    }
    prev = { x, y };
  }
  svg("path", { d }, supports);

  const cars = [0, 1, 2].map(() => svg("rect", { class: "s-car", width: 16, height: 9, rx: 2, x: -8, y: -9 }, trainLayer));
  const log = svg("rect", { class: "s-log", width: 20, height: 9, rx: 4, x: -10, y: -11 }, logLayer);
  const horseLayer = $("#sc-horses");
  const horses = [0, 1, 2, 3].map((i) => svg("rect", { width: 10, height: 6, rx: 2, x: 968 + i * 22, y: 420 }, horseLayer));
  const EMIT = 900;
  const ANT = { x: 665, y: 352 };
  const GATE = 745;
  const PATH_Y = 459;
  const at = (element) => {
    const [x, y] = point(element, "at");
    return { x, y };
  };
  const rides = {
    coaster: { ...at(trainLayer), load: 24 * TENTH, run: 56 * TENTH, t: 12 * TENTH, phase: "load", queue: [], cap: 4, ride: 60 * TENTH },
    carousel: { ...at(carousel), load: 20 * TENTH, run: 32 * TENTH, t: 6 * TENTH, phase: "load", queue: [], cap: 4, ride: 34 * TENTH },
    flume: { ...at(logLayer), load: 20 * TENTH, run: 46 * TENTH, t: 3 * TENTH, phase: "load", queue: [], cap: 2, ride: 48 * TENTH },
  };
  const snapshots = point(dotsLayer, "snapshots");
  const stalls = [{ x: 884, y: 410 }, { x: 928, y: 406 }];
  const office = { x: 826, y: 384 };
  const park = { guests: [], dots: [], spawnIn: 0, day: 0, dayT: 30 * TENTH };

  function emit(type, x, y) {
    if (park.dots.length > 48) return;
    const big = type === "finance_month";
    const node = svg(big ? "rect" : "circle", big ? { class: "s-dot", width: 13, height: 13, rx: 2 } : { class: "s-dot", r: 5.5 }, dotsLayer);
    const dist = Math.hypot(x - ANT.x, y - ANT.y);
    park.dots.push({ node, big, x0: x, y0: y, cx: (x + ANT.x) / 2, cy: Math.min(y, ANT.y) - 150 - dist * 0.15, t: 0, dur: EMIT * (0.75 + dist / 900), stage: "fly" });
  }
  function placeDot(dot, x, y) {
    if (dot.big) {
      dot.node.setAttribute("x", x - 6.5);
      dot.node.setAttribute("y", y - 6.5);
    } else {
      dot.node.setAttribute("cx", x);
      dot.node.setAttribute("cy", y);
    }
  }
  function spawnGuest() {
    const tone = Math.floor(rng() * 3);
    const node = svg("g", { class: "s-guest" + (tone ? " t" + (tone + 1) : "") }, guestsLayer);
    svg("rect", { x: -3.5, y: -11, width: 7, height: 11, rx: 3 }, node);
    svg("circle", { cx: 0, cy: -14.6, r: 3.4 }, node);
    park.guests.push({ node, x: -10 - rng() * 30, y: PATH_Y - 6 + rng() * 12, phase: "in", speed: 0.05 + rng() * 0.03, visits: 0, wait: 0, target: null });
  }
  const targets = ["coaster", "coaster", "carousel", "flume", "stall0", "stall1"];
  function chooseTarget(guest) {
    const key = targets[Math.floor(rng() * targets.length)];
    guest.target = key;
    guest.phase = "go";
    guest.tx = key.startsWith("stall") ? stalls[+key.slice(5)].x : rides[key].x + (rng() * 16 - 8);
  }
  function stepGuests(dt) {
    park.spawnIn -= dt;
    if (park.spawnIn <= 0 && park.guests.length < 20) {
      spawnGuest();
      park.spawnIn = 650 + rng() * 700;
    }
    for (let i = park.guests.length - 1; i >= 0; i--) {
      const g = park.guests[i];
      if (g.phase === "in") {
        g.x += g.speed * dt;
        if (g.x >= GATE) {
          emit("guest_arrived", GATE, 372);
          chooseTarget(g);
        }
      } else if (g.phase === "go") {
        g.x += Math.sign(g.tx - g.x) * g.speed * dt;
        if (Math.abs(g.tx - g.x) < 2) {
          if (g.target.startsWith("stall")) {
            g.phase = "shop";
            g.wait = 900 + rng() * 700;
          } else if (g.target === "coaster" && rng() < 0.14) {
            emit("guest_refused", g.x, 440);
            g.visits++;
            g.phase = "decide";
          } else {
            g.phase = "queue";
            rides[g.target].queue.push(g);
          }
        }
      } else if (g.phase === "shop" || g.phase === "ride") {
        g.wait -= dt;
        if (g.wait <= 0) {
          g.node.style.opacity = 1;
          g.visits++;
          g.phase = "decide";
        }
      }
      if (g.phase === "decide") {
        if (g.visits < 2 && rng() < 0.6) chooseTarget(g);
        else g.phase = "out";
      }
      if (g.phase === "out") {
        g.x -= g.speed * dt;
        if (g.x <= GATE) {
          emit("guest_left", GATE, 372);
          g.phase = "leave";
        }
      } else if (g.phase === "leave") {
        g.x -= g.speed * dt;
        if (g.x < -20) {
          g.node.remove();
          park.guests.splice(i, 1);
          continue;
        }
      }
      g.node.setAttribute("transform", `translate(${g.x.toFixed(1)} ${g.y.toFixed(1)})`);
    }
  }
  function stepRides(dt) {
    for (const ride of Object.values(rides)) {
      ride.t -= dt;
      if (ride.t <= 0) {
        if (ride.phase === "load") {
          ride.phase = "run";
          ride.t = ride.run;
          ride.elapsed = 0;
          const boarders = ride.queue.splice(0, ride.cap);
          for (const g of boarders) {
            g.phase = "ride";
            g.wait = ride.ride;
            g.node.style.opacity = 0;
          }
          for (let k = 0; k < Math.max(1, Math.min(3, boarders.length)); k++) emit("guest_boarded", ride.x + k * 8, ride.y - 10);
        } else {
          ride.phase = "load";
          ride.t = ride.load;
        }
      }
      if (ride.phase === "run") ride.elapsed += dt;
    }
    const { coaster, flume: logRide, carousel: horsesRide } = rides;
    const cu = coaster.phase === "run" ? Math.min(1, coaster.elapsed / coaster.run) : 0;
    cars.forEach((car, k) => {
      const p = track.getPointAtLength(Math.max(0, cu * trackLength + 120 - k * 18));
      car.setAttribute("transform", `translate(${p.x} ${p.y})`);
    });
    const fu = logRide.phase === "run" ? Math.min(1, logRide.elapsed / logRide.run) : 0;
    const lp = flume.getPointAtLength(fu * flumeLength);
    log.setAttribute("transform", `translate(${lp.x} ${lp.y})`);
    const spin = horsesRide.phase === "run" ? horsesRide.elapsed / 260 : 0;
    horses.forEach((horse, k) => horse.setAttribute("y", 418 + Math.sin(spin + k * 1.6) * 4));
  }
  function stepEvents(dt) {
    park.dayT -= dt;
    if (park.dayT <= 0) {
      park.dayT = 60 * TENTH;
      park.day++;
      for (let k = 0; k < snapshots.length; k += 2) emit("ride_snapshot", snapshots[k], snapshots[k + 1]);
      emit("ride_snapshot", stalls[0].x, stalls[0].y);
      emit("ride_snapshot", stalls[1].x, stalls[1].y - 20);
      emit("park_snapshot", office.x, office.y);
      if (park.day % 4 === 0) emit("finance_month", office.x + 20, office.y - 6);
    }
    for (let i = park.dots.length - 1; i >= 0; i--) {
      const dot = park.dots[i];
      dot.t += dt;
      if (dot.stage === "fly") {
        const u = Math.min(1, dot.t / dot.dur);
        const v = 1 - u;
        placeDot(dot, v * v * dot.x0 + 2 * v * u * dot.cx + u * u * ANT.x, v * v * dot.y0 + 2 * v * u * dot.cy + u * u * ANT.y);
        if (u >= 1) {
          dot.stage = "dive";
          dot.t = 0;
        }
      } else {
        const u = Math.min(1, dot.t / 420);
        placeDot(dot, ANT.x, ANT.y + u * (506 - ANT.y));
        if (u >= 1) {
          dot.node.remove();
          park.dots.splice(i, 1);
        }
      }
    }
  }
  const stepPark = (dt) => {
    stepGuests(dt);
    stepRides(dt);
    stepEvents(dt);
  };

  // Three crops of one drawing; the frame follows the drawing's own aspect so nothing is cut unplanned.
  // The wide view is the markup's own viewBox; the mid view trims 210 units off its left side.
  const { x: wx, y: wy, width: ww, height: wh } = scene.viewBox.baseVal;
  const VIEWS = { wide: [wx, wy, ww, wh], mid: [wx + 210, wy, ww - 210, wh], crop: [640, 110, 820, 396] };
  fitScene = () => {
    const width = scene.getBoundingClientRect().width;
    const mode = width >= 900 ? "wide" : width >= 560 ? "mid" : "crop";
    const [vx, vy, vw, vh] = VIEWS[mode];
    scene.setAttribute("viewBox", `${vx} ${vy} ${vw} ${vh}`);
    scene.style.aspectRatio = `${vw} / ${vh}`;
    scene.classList.toggle("is-mid", mode === "mid");
    scene.classList.toggle("is-crop", mode === "crop");
    scene.style.setProperty("--ray-x", (((ANT.x - vx) / vw) * 100).toFixed(1) + "%");
    scene.style.setProperty("--ray-y", (((ANT.y - vy) / vh) * 100).toFixed(1) + "%");
  };

  let frameId = 0;
  let last = 0;
  let visible = true;
  const running = () => motion.on && visible && !motion.reduced;
  function frame(now) {
    frameId = 0;
    const dt = Math.min(60, now - last);
    last = now;
    stepPark(dt);
    if (running()) frameId = requestAnimationFrame(frame);
  }
  function sync() {
    if (running()) {
      if (!frameId) {
        last = performance.now();
        frameId = requestAnimationFrame(frame);
      }
    } else if (frameId) {
      cancelAnimationFrame(frameId);
      frameId = 0;
    }
  }
  // Reduced motion and the first paint both start from a park that has been open a while.
  for (let t = 0; t < 160 * TENTH; t += 40) stepPark(40);
  new IntersectionObserver((entries) => {
    for (const entry of entries) visible = entry.isIntersecting;
    sync();
  }).observe(scene);
  onMotionChange(sync);
  fitScene();
}
