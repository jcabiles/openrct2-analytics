// Pricing: every ride price change, tested over a draggable window of days before and after it.
"use strict";
(function () {
  if (!READY) return;
  const D = SCOPE.dates, RD = SCOPE.ride_days, WINDOW = 30, WIDEST = 60, price = p => p ? usd2(p).replace(".00", "") : "free";
  function stat(mv, N) {
    const r = mv.r, side = (a, b) => { let n = 0, p = 0, c = 0; for (let j = Math.max(0, a); j < Math.min(r.price.length, b); j++) if (r.open[j] && r.profit[j] != null && r.riders[j] != null) { n++; p += r.profit[j]; c += r.riders[j] } return { n, profit: n ? p / n : 0, riders: n ? c / n : 0 } };
    const b = side(mv.j - N, mv.j), a = side(mv.j, mv.j + N);
    return { b, a, d: a.profit - b.profit };
  }
  // A price change is two prices in a row that the ride kept for at least 5 open days each; a price held for fewer days is folded into the one after it.
  const MOVES = [];
  let leftOut = 0;
  RIDES.forEach((ride, k) => {
    const r = RD[k], g = [];
    r.price.forEach((p, j) => { if (!r.open[j]) return; const L = g[g.length - 1]; if (L && L.p === p) L.n++; else g.push({ p, start: j, n: 1 }) });
    for (let i = g.length - 2; i >= 0; i--) if (g[i].n < 5) { g[i + 1].start = g[i].start; g[i + 1].n += g[i].n; g.splice(i, 1) }
    for (let i = 1; i < g.length; i++) {
      if (g[i].p === g[i - 1].p) continue;
      const mv = { ride, r, j: g[i].start, from: g[i - 1].p, to: g[i].p, day: r.first + g[i].start };
      mv.reset = ride.reset.some(d => Math.abs(D.indexOf(d) - mv.day) <= 3);
      const s = stat(mv, WINDOW);
      if (s.b.n >= 5 && s.a.n >= 5) MOVES.push(mv); else leftOut++;
    }
  });
  let N = WINDOW, sel = null, year = "All", rows = [];
  const SMAX = Math.max(1, ...MOVES.flatMap(m => [7, 14, 30, 45, 60].flatMap(n => { const s = stat(m, n); return [s.a.profit, s.b.profit] }))), STOP = Math.ceil(SMAX / 50) * 50, SX = lin(0, STOP, 226, 446);
  const shownMoves = () => MOVES.filter(m => year === "All" || D[m.day].slice(0, 4) === String(year));
  const nameOf = m => m.ride.name + " (" + price(m.from) + " to " + price(m.to) + ")";

  function buildScore() {
    const s = $("score"), ms = shownMoves().map(m => ({ m, s: stat(m, N) })).sort((a, b) => b.s.d - a.s.d), H0 = 30, RH = Math.min(48, (556 - H0) / Math.max(1, ms.length));
    s.replaceChildren(); rows = [];
    for (let v = 0; v <= STOP; v += STOP > 300 ? 100 : 50) { S("line", { x1: SX(v), x2: SX(v), y1: H0 - 6, y2: H0 + ms.length * RH, stroke: v ? "#edebe9" : "#c8c6c4" }, s); S("text", { x: SX(v), y: H0 - 12, "text-anchor": "middle" }, s, "$" + v) }
    S("text", { x: 0, y: H0 - 12, style: "font-size:11px" }, s, "Ride and price change"); S("text", { x: 566, y: H0 - 12, "text-anchor": "end", style: "font-size:11px" }, s, "Change per day");
    ms.forEach(({ m }, i) => {
      const y = H0 + i * RH, g = S("g", { role: "button", tabindex: 0 }, s), bg = S("rect", { x: 0, y: y + 1, width: 566, height: RH - 2, fill: "#fff" }, g), bar = S("rect", { x: 0, y: y + 1, width: 3, height: RH - 2, fill: "#f2c811", opacity: 0 }, g);
      S("text", { x: 10, y: y + RH / 2 - 3, style: "font-size:12.5px;fill:#252423;font-weight:600" }, g, m.ride.short); S("text", { x: 10, y: y + RH / 2 + 12, style: "font-size:11px" }, g, price(m.from) + " to " + price(m.to) + ", " + dayLabel(D[m.day]));
      if (m.reset) { S("circle", { cx: 22 + m.ride.short.length * 7.3, cy: y + RH / 2 - 7, r: 3, fill: "#f2c811", stroke: "#8a6d00", "stroke-width": .6 }, g); S("text", { x: 29 + m.ride.short.length * 7.3, y: y + RH / 2 - 3, style: "font-size:11px" }, g, "age reset") }
      const o = { m, g, bg, bar, line: S("line", { y1: y + RH / 2, y2: y + RH / 2, "stroke-width": 4, "stroke-linecap": "round" }, g), b: S("circle", { cy: y + RH / 2, r: 5.5, fill: "#fff", "stroke-width": 2 }, g), a: S("circle", { cy: y + RH / 2, r: 6 }, g), d: S("text", { x: 566, y: y + RH / 2 - 3, "text-anchor": "end", style: "font-size:12.5px;font-weight:700" }, g), sub: S("text", { x: 566, y: y + RH / 2 + 12, "text-anchor": "end", style: "font-size:11px" }, g), cur: null };
      S("line", { x1: 0, x2: 566, y1: y + RH, y2: y + RH, stroke: "#edebe9" }, g);
      act(g, () => { sel = m; paintScore(0); paintDetail() });
      bindTip(g, () => { const st = stat(m, N); return [m.ride.name + ": " + price(m.from) + " to " + price(m.to), "Before: " + usd2(st.b.profit) + " profit and " + st.b.riders.toFixed(1) + " riders a day (" + st.b.n + " open days)", "After: " + usd2(st.a.profit) + " profit and " + st.a.riders.toFixed(1) + " riders a day (" + st.a.n + " open days)", m.reset ? "The ride's age was reset within 3 days of the change" : "No age reset at the change"] });
      rows.push(o);
    });
    const ly = H0 + ms.length * RH + 14;
    S("circle", { cx: 230, cy: ly, r: 4.5, fill: "#fff", stroke: "#605e5c", "stroke-width": 2 }, s); S("text", { x: 240, y: ly + 4 }, s, "before"); S("circle", { cx: 292, cy: ly, r: 5, fill: "#605e5c" }, s); S("text", { x: 302, y: ly + 4 }, s, "after");
    if (!ms.length) S("text", { x: 0, y: 70, style: "font-size:13px" }, s, year === "All" ? "No ride has changed its price yet." : "No ride changed its price in " + year + ". Choose another year or All.");
    if (!ms.some(o => o.m === sel)) sel = ms.length ? ms[0].m : null;
    paintScore(0);
  }
  function paintScore(ms) {
    rows.forEach(o => {
      const st = stat(o.m, N), from = o.cur || { a: st.a.profit, b: st.b.profit }, up = st.d >= 0, col = up ? "#118dff" : "#e66c37";
      o.cur = { a: st.a.profit, b: st.b.profit };
      if (o.tw) o.tw.stop();
      o.tw = tween(ms, k => { const a = SX(lerp(from.a, st.a.profit, k)), b = SX(lerp(from.b, st.b.profit, k)); set(o.line, { x1: b, x2: a, stroke: col }); set(o.b, { cx: b, stroke: col }); set(o.a, { cx: a, fill: col }) });
      o.d.textContent = (st.d >= 0 ? "+" : "") + usd(st.d) + " a day"; o.d.style.fill = up ? "#0b6bcb" : "#b3460e"; o.sub.textContent = st.b.riders.toFixed(1) + " to " + st.a.riders.toFixed(1) + " riders";
      o.bar.setAttribute("opacity", o.m === sel ? 1 : 0); o.bg.setAttribute("fill", o.m === sel ? "#fff9db" : "#fff");
      set(o.g, { "aria-pressed": String(o.m === sel), "aria-label": o.m.ride.name + ", " + price(o.m.from) + " to " + price(o.m.to) + " on " + dayLabel(D[o.m.day]) + ": " + o.d.textContent });
    });
    text();
  }
  function text() {
    const ms = shownMoves().map(m => ({ m, s: stat(m, N) }));
    $("winOut").textContent = N + " days";
    $("left").textContent = "A price change counts when the ride was open at least 5 days on each side of it within " + WINDOW + " days" + (leftOut ? "; " + plural(leftOut, "change is", "changes are") + " left out by that rule." : ".");
    if (!ms.length) { say($("finding"), year === "All" ? ["No ride has changed its price yet."] : ["No ride changed its price in ", [String(year)], "."]); return }
    const cuts = ms.filter(o => o.m.to < o.m.from), down = ms.filter(o => o.s.d <= -1), paid = ms.filter(o => o.s.d >= 1), worst = ms.slice().sort((a, b) => a.s.d - b.s.d)[0], best = ms.slice().sort((a, b) => b.s.d - a.s.d)[0], helped = paid.filter(o => o.m.reset || o.s.b.riders === 0);
    const what = cuts.length === ms.length ? (ms.length === 1 ? " price cut" : " price cuts") : (ms.length === 1 ? " price change" : " price changes");
    const p = [{ mark: down.length + " of " + ms.length + what }, down.length === 1 ? " was followed by " : " were followed by ", ["lower profit per day"], " over the next ", [N + " days"], ". "];
    if (paid.length && helped.length === paid.length) p.push(paid.length === 1 ? "The one that paid came with" : "Each of the " + paid.length + " that paid came with", " an age reset or a ride nobody had been riding. ");
    if (down.length) p.push("Largest loss: ", [nameOf(worst.m)], ", ", [usd(worst.s.d) + " a day"], "."); else if (paid.length) p.push("Largest gain: ", [nameOf(best.m)], ", ", ["+" + usd(best.s.d) + " a day"], ".");
    say($("finding"), p);
  }

  // ---- one ride, day by day
  const DX = lin(-90, 90, 44, 570), G = {};
  function paintDetail() {
    const s = $("detail");
    [...s.querySelectorAll("g")].forEach(g => g.remove());
    if (!sel) { $("detTitle").textContent = "Choose a price change"; G.band = null; return }
    const g = S("g", {}, s), m = sel, r = m.r, st = stat(m, N), lo = Math.max(-90, -m.j), hi = Math.min(90, r.price.length - 1 - m.j);
    $("detTitle").textContent = m.ride.name + ": " + price(m.from) + " to " + price(m.to) + " on " + dayLabel(D[m.day]);
    G.band = S("rect", { y: 20, height: 556, fill: "#f2c811", opacity: .2 }, g); G.e1 = S("line", { y1: 20, y2: 576, stroke: "#8a6d00", "stroke-width": 1.5 }, g); G.e2 = S("line", { y1: 20, y2: 576, stroke: "#8a6d00", "stroke-width": 1.5 }, g); G.h1 = S("rect", { y: 316, width: 8, height: 22, rx: 2, fill: "#8a6d00" }, g); G.h2 = S("rect", { y: 316, width: 8, height: 22, rx: 2, fill: "#8a6d00" }, g);
    const panel = (y0, h, title, vals, max, fmt, col) => {
      const y = lin(0, max, y0 + h, y0);
      S("text", { x: 44, y: y0 - 8, style: "font-size:12px;fill:#252423;font-weight:600" }, g, title);
      [0, max / 2, max].forEach(v => { S("line", { x1: 44, x2: 570, y1: y(v), y2: y(v), stroke: v ? "#edebe9" : "#c8c6c4" }, g); S("text", { x: 38, y: y(v) + 4, "text-anchor": "end" }, g, fmt(v)) });
      for (let d = lo; d <= hi; d++) { const j = m.j + d, v = vals[j]; if (!r.open[j]) { S("rect", { x: DX(d) - 1.4, y: y0 + h + 2, width: 2.8, height: 3, fill: "#a19f9d" }, g); continue } if (v == null) continue; const yy = y(clamp(v, 0, max)); S("rect", { x: DX(d) - 1.2, y: Math.min(yy, y0 + h - 1), width: 2.4, height: Math.max(1, y0 + h - yy), fill: col, opacity: .55 }, g) }
      return y;
    };
    const pmax = Math.ceil(Math.max(m.from, m.to, 1) * 1.2), py = lin(0, pmax, 96, 36);
    S("text", { x: 44, y: 28, style: "font-size:12px;fill:#252423;font-weight:600" }, g, "Listed price");
    [0, pmax].forEach(v => { S("line", { x1: 44, x2: 570, y1: py(v), y2: py(v), stroke: v ? "#edebe9" : "#c8c6c4" }, g); S("text", { x: 38, y: py(v) + 4, "text-anchor": "end" }, g, "$" + v) });
    let d = "";
    for (let k = lo; k <= hi; k++) { const p = r.price[m.j + k]; if (p == null) continue; d += (d ? "L" : "M") + (DX(k) - 1.46).toFixed(1) + " " + py(p).toFixed(1) + "L" + (DX(k) + 1.46).toFixed(1) + " " + py(p).toFixed(1) }
    S("path", { d, fill: "none", stroke: "#252423", "stroke-width": 2 }, g);
    S("text", { x: DX(lo) + 4, y: py(m.from) - 6, style: "font-size:12px;font-weight:700;fill:#252423" }, g, price(m.from)); S("text", { x: DX(hi) - 4, y: py(m.to) - 6, "text-anchor": "end", style: "font-size:12px;font-weight:700;fill:#252423" }, g, price(m.to));
    const around = []; for (let j = Math.max(0, m.j + lo); j <= Math.min(r.price.length - 1, m.j + hi); j++) if (r.open[j] && r.riders[j] != null) around.push(j);
    const rmax = Math.max(8, Math.ceil(Math.max(0, ...around.map(j => r.riders[j])) / 8) * 8), fmax = Math.max(50, Math.ceil(Math.max(0, ...around.map(j => r.profit[j] || 0)) / 50) * 50);
    G.ry = panel(140, 170, "Riders each day", r.riders, rmax, v => v, "#12239e"); G.fy = panel(360, 170, "Profit each day", r.profit, fmax, v => "$" + v, "#12239e");
    S("text", { x: 570, y: 132, "text-anchor": "end", style: "font-size:11px" }, g, "grey marks under a chart: ride closed that day");
    [-90, -60, -30, 0, 30, 60, 90].forEach(v => { if (v < lo || v > hi) return; S("text", { x: DX(v), y: 592, "text-anchor": "middle" }, g, v ? (v > 0 ? "+" : "−") + Math.abs(v) + " days" : dayLabel(D[m.day])) });
    S("line", { x1: DX(0) - 1.4, x2: DX(0) - 1.4, y1: 20, y2: 576, stroke: "#252423", "stroke-width": 1.5, "stroke-dasharray": "4 3" }, g);
    if (m.reset) S("text", { x: DX(0) + 6, y: 112, style: "font-size:11px;fill:#252423;font-weight:600" }, g, "age reset");
    G.m = ["rb", "ra", "fb", "fa"].map(k => ({ k, l: S("line", { stroke: k[1] === "a" ? "#12239e" : "#605e5c", "stroke-width": 3 }, g), t: S("text", { style: "paint-order:stroke;stroke:#fff;stroke-width:3px;font-size:12px;font-weight:700;fill:" + (k[1] === "a" ? "#12239e" : "#252423"), "text-anchor": k[1] === "a" ? "start" : "end" }, g) }));
    G.lo = lo; G.hi = hi; paintWindow();
    $("detDesc").textContent = "Listed price, riders and profit by day for 90 days either side of the change. Over " + N + " days: profit per day " + usd2(st.b.profit) + " before, " + usd2(st.a.profit) + " after.";
  }
  function paintWindow() {
    if (!sel || !G.band) return;
    const st = stat(sel, N), a = Math.max(G.lo, -N), b = Math.min(G.hi, N - 1), x1 = DX(a) - 1.4, x2 = DX(b) + 1.4;
    set(G.band, { x: x1, width: x2 - x1 }); set(G.e1, { x1, x2: x1 }); set(G.e2, { x1: x2, x2 }); set(G.h1, { x: x1 - 4 }); set(G.h2, { x: x2 - 4 });
    G.m.forEach(o => { const riders = o.k[0] === "r", after = o.k[1] === "a", v = (after ? st.a : st.b)[riders ? "riders" : "profit"], y = (riders ? G.ry : G.fy)(v), xa = after ? DX(0) : x1, xb = after ? x2 : DX(0) - 2.8; set(o.l, { x1: xa, x2: xb, y1: y, y2: y }); o.t.textContent = riders ? v.toFixed(1) + " a day" : usd(v) + " a day"; set(o.t, { x: after ? x2 + 7 : x1 - 7, y: y + 4 }) });
  }
  function setN(n) { n = clamp(Math.round(n), 7, WIDEST); if (n === N) return; N = n; $("win").value = N; paintScore(140); paintWindow() }
  $("win").addEventListener("input", e => setN(+e.target.value));
  onDrag($("detail"), e => setN(Math.abs((svgX($("detail"), e).x - DX(0)) / (DX(1) - DX(0)))));
  function setYear(y) { year = y; chips("yrs", [["All", "All"], ...YEARS.map(v => [String(v), v])], year, setYear); buildScore(); paintDetail() }
  // Opens on the change that shows a gain over the default window and the largest loss over the
  // widest one, else on the largest loss over the default window.
  const turns = MOVES.filter(m => stat(m, WINDOW).d > 0 && stat(m, WIDEST).d < 0).sort((a, b) => stat(a, WIDEST).d - stat(b, WIDEST).d);
  sel = turns[0] || MOVES.slice().sort((a, b) => stat(a, WINDOW).d - stat(b, WINDOW).d)[0] || null;
  setYear("All");
  // Opening beat: the window grows from one week to the default, so the reader sees the verdicts settle.
  if (!REDUCED) { N = 7; $("win").value = 7; paintScore(0); paintWindow(); let n = 7; (function grow() { setTimeout(() => { n += 1; setN(n); if (n < WINDOW) grow() }, 45) })() }
})();
