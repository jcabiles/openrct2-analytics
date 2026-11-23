// Attractions: every ride's month replayed as a bubble chart, with a lane for rides that earned nothing.
"use strict";
(function () {
  if (!READY) return;
  const n = M.length, R = RIDES;
  const perRider = (r, i) => r.profit[i] / r.riders[i], perDay = (r, i) => r.riders[i] / Math.max(1, r.open[i]);
  const cells = R.flatMap(r => M.map((_, i) => [r, i])), earned = cells.filter(([r, i]) => earning(r, i));
  const top = (list, f) => Math.max(0, ...list.map(([r, i]) => f(r, i)).filter(v => isFinite(v)));
  // Scales from the data; a ride with fewer than 20 riders in a month does not stretch the profit-per-rider axis.
  const PMAX = top(earned, (r, i) => r.profit[i]) || 1, BIG = PMAX / 9;
  const steady = earned.filter(([r, i]) => r.riders[i] >= 20);
  const MODES = {
    earn: { title: "Riders against profit per rider", xl: "Riders in the month", yl: "Profit per rider", xmax: niceMax(top(earned, (r, i) => r.riders[i]) || 1), ymax: niceMax(top(steady.length ? steady : earned, perRider) || 1), yf: v => "$" + v, x: (r, i) => r.riders[i], y: perRider },
    age: { title: "Ride age against riders per day", xl: "Ride age in months", yl: "Riders per open day", xmax: niceMax(top(earned, (r, i) => r.age[i] + 1) || 1), ymax: niceMax(top(earned, perDay) || 1), yf: v => v, x: (r, i) => r.age[i], y: perDay },
  };
  let cur = n - 1, mode = "earn", pin = null, hot = null, run = null, timer = null, sortKey = "profit", sortDir = -1, G = {}, nodes = [], LS = [], shown = null;
  const PX = () => lin(0, MODES[mode].xmax, 48, 656), PY = () => lin(0, MODES[mode].ymax, 452, 44), rad = p => Math.max(4, Math.sqrt(Math.max(0, p) / PMAX) * 34);
  // Where a ride sits in month i: on the chart when it earned, in the grey lane when it existed but earned nothing.
  function place(i) {
    const x = PX(), y = PY(), m = MODES[mode], idle = R.filter(r => exists(r, i) && !earning(r, i)).length, gap = Math.min(98, 580 / Math.max(1, idle));
    let slot = 0;
    return R.map(r => { if (!exists(r, i)) return null; if (earning(r, i)) return { x: x(clamp(m.x(r, i), 0, m.xmax)), y: y(clamp(m.y(r, i), 0, m.ymax)), r: rad(r.profit[i]), lane: 0 }; return { x: 86 + (slot++) * gap, y: 516, r: 7, lane: 1 } });
  }
  function axes() {
    const g = G.axes, m = MODES[mode], x = PX(), y = PY();
    g.replaceChildren();
    niceTicks(0, m.ymax).forEach(v => { S("line", { x1: 48, x2: 656, y1: y(v), y2: y(v), stroke: "#edebe9" }, g); S("text", { x: 42, y: y(v) + 4, "text-anchor": "end" }, g, m.yf(v)) });
    niceTicks(0, m.xmax).forEach(v => { S("line", { x1: x(v), x2: x(v), y1: 44, y2: 452, stroke: "#f3f2f1" }, g); S("text", { x: x(v), y: 468, "text-anchor": "middle" }, g, v) });
    S("text", { x: 656, y: 484, "text-anchor": "end", style: "font-size:12px;fill:#252423" }, g, m.xl + " →"); S("text", { x: 48, y: 30, style: "font-size:12px;fill:#252423" }, g, "↑ " + m.yl);
    // curves of equal monthly profit: many riders at a low margin, or few at a high one
    if (mode === "earn") niceTicks(0, PMAX).filter(p => p > 0 && p < PMAX).slice(-4).forEach(p => { let d = ""; for (let v = p / m.ymax; v <= m.xmax; v += m.xmax / 100) d += (d ? "L" : "M") + x(v).toFixed(1) + " " + y(p / v).toFixed(1); S("path", { d, fill: "none", stroke: "#c8c6c4", "stroke-dasharray": "2 4" }, g); S("text", { x: 654, y: y(p / m.xmax) - 5, "text-anchor": "end", style: "font-size:10.5px" }, g, tick$(p) + " a month") });
    S("rect", { x: 0, y: 494, width: 676, height: 66, fill: "#f3f2f1" }, g);
    S("text", { x: 8, y: 510, style: "font-size:11px;fill:#252423;font-weight:600" }, g, "Earned"); S("text", { x: 8, y: 524, style: "font-size:11px;fill:#252423;font-weight:600" }, g, "nothing");
    Object.entries(FAM).filter(([k]) => R.some(r => r.fam === k)).forEach(([k, c], i) => { S("circle", { cx: 238 + i * 62, cy: 12, r: 5, fill: c }, g); S("text", { x: 247 + i * 62, y: 16 }, g, k) });
    S("text", { x: 656, y: 16, "text-anchor": "end" }, g, "bubble area = profit in the month");
    G.none = S("text", { x: 86, y: 520, style: "font-size:12px", opacity: 0 }, g, "No ride was idle this month.");
  }
  function setup() {
    const s = $("bub");
    G.axes = S("g", {}, s); G.trail = S("path", { fill: "none", stroke: "#252423", "stroke-width": 1.25, "stroke-dasharray": "1 3", "stroke-linecap": "round" }, s); G.marks = S("g", {}, s);
    R.forEach((r, k) => {
      const g = S("g", { class: "ride", tabindex: 0, role: "button" }, G.marks), c = S("circle", { r: 0, fill: FAM[r.fam], "fill-opacity": .82, stroke: "#fff", "stroke-width": 1.5 }, g), t = S("text", { style: "font-size:11px;fill:#252423" }, g, r.short);
      nodes.push({ g, c, t, p: null });
      act(g, () => setPin(pin === k ? null : k));
      g.addEventListener("mouseenter", () => setHot(k)); g.addEventListener("mouseleave", () => setHot(null)); g.addEventListener("focus", () => setHot(k)); g.addEventListener("blur", () => setHot(null));
      bindTip(g, () => tipFor(r, cur));
    });
  }
  function tipFor(r, i) {
    if (!exists(r, i)) return [r.name, "Not built yet in " + lab(i)];
    const st = !r.open[i] ? "Closed all month" : !r.riders[i] ? "Open " + r.open[i] + " days, no riders" : num(r.riders[i]) + " riders, " + usd(r.profit[i]) + " profit";
    return [r.name, lab(i) + ": " + st, (earning(r, i) ? usd2(perRider(r, i)) + " per rider, " : "") + "listed price " + usd2(r.pmode[i] != null ? r.pmode[i] : r.price[i]), "Age " + r.age[i] + " months" + (r.rating[i] != null ? ", guest rating " + r.rating[i] + "%" : "")];
  }
  // Choose a side for each visible label on the settled layout, so labels stay clear of other bubbles and of each other.
  function layout(B) {
    const boxes = [], hit = (a, b) => a[0] < b[0] + b[2] && b[0] < a[0] + a[2] && a[1] < b[1] + b[3] && b[1] < a[1] + a[3];
    LS = R.map(() => 0);
    R.map((r, j) => j).filter(j => B[j] && !B[j].lane).sort((a, b) => B[b].r - B[a].r).forEach(j => {
      const p = B[j], w = R[j].short.length * 6.4 + 4, c = [[p.x + p.r + 4, p.y - 8, w, 13], [p.x - p.r - 4 - w, p.y - 8, w, 13], [p.x - w / 2, p.y - p.r - 17, w, 13], [p.x - w / 2, p.y + p.r + 3, w, 13], [p.x - p.r, p.y - p.r - 17, w, 13], [p.x - p.r, p.y + p.r + 3, w, 13]];
      let pick = c.findIndex(b => b[0] >= 46 && b[0] + b[2] < 672 && b[1] > 40 && !boxes.some(o => hit(b, o)) && !R.some((q, i) => i !== j && B[i] && !B[i].lane && hit(b, [B[i].x - B[i].r * .8, B[i].y - B[i].r * .8, B[i].r * 1.6, B[i].r * 1.6])));
      if (pick < 0) pick = p.x > 540 ? 1 : 0;
      LS[j] = pick;
      if (R[j].profit[cur] >= BIG || pin === j || hot === j) boxes.push(c[pick]);
    });
  }
  const SIDES = [p => ({ x: p.x + p.r + 4, y: p.y + 4, "text-anchor": "start" }), p => ({ x: p.x - p.r - 4, y: p.y + 4, "text-anchor": "end" }), p => ({ x: p.x, y: p.y - p.r - 6, "text-anchor": "middle" }), p => ({ x: p.x, y: p.y + p.r + 14, "text-anchor": "middle" }), p => ({ x: p.x - p.r, y: p.y - p.r - 6, "text-anchor": "start" }), p => ({ x: p.x - p.r, y: p.y + p.r + 14, "text-anchor": "start" })];
  function paint(A, B, k) {
    R.forEach((r, j) => {
      const nd = nodes[j], a = A[j], b = B[j], p = a && b ? { x: lerp(a.x, b.x, k), y: lerp(a.y, b.y, k), r: lerp(a.r, b.r, k), lane: k < .5 ? a.lane : b.lane } : b ? { ...b, r: b.r * k } : a ? { ...a, r: a.r * (1 - k) } : null;
      nd.p = p;
      if (!p || p.r < .3) { nd.g.setAttribute("display", "none"); return }
      nd.g.removeAttribute("display");
      const on = pin === j || hot === j;
      set(nd.c, { cx: p.x.toFixed(1), cy: p.y.toFixed(1), r: p.r.toFixed(1), fill: p.lane ? "#fff" : FAM[r.fam], stroke: p.lane ? FAM[r.fam] : on ? "#252423" : "#fff", "stroke-width": p.lane || on ? 2 : 1.5 });
      nd.t.setAttribute("opacity", p.lane || on || (b && !b.lane && r.profit[cur] >= BIG) ? 1 : 0);
      set(nd.t, p.lane ? { x: p.x, y: p.y + 24, "text-anchor": "middle" } : SIDES[LS[j] || 0](p));
      nd.t.style.fontWeight = on ? 700 : 400;
    });
    if (G.none) G.none.setAttribute("opacity", B.some(b => b && b.lane) || A.some(a => a && a.lane && k < 1) ? 0 : 1);
    trail();
  }
  function trail() {
    if (pin == null) { G.trail.setAttribute("d", ""); return }
    const r = R[pin], x = PX(), y = PY(), m = MODES[mode];
    let d = "", pen = false;
    for (let i = 0; i <= cur; i++) { if (exists(r, i) && earning(r, i)) { if (i && r.age[i] < r.age[i - 1]) pen = false; d += (pen ? "L" : "M") + x(clamp(m.x(r, i), 0, m.xmax)).toFixed(1) + " " + y(clamp(m.y(r, i), 0, m.ymax)).toFixed(1); pen = true } else pen = false }
    G.trail.setAttribute("d", d);
  }
  const snap = () => nodes.map(n => n.p && n.p.r > .3 ? { ...n.p } : null);
  function moveTo(i, ms) { const A = shown ? snap() : place(i); cur = i; const B = place(i); if (run) run.stop(); texts(); shown = B; layout(B); run = tween(ms == null ? 450 : ms, k => paint(A, B, k)) }
  function setMode(m) { const A = shown ? snap() : null; mode = m; axes(); const B = place(cur); [...$("mode").querySelectorAll("button")].forEach(b => b.setAttribute("aria-pressed", String(b.dataset.m === mode))); $("bubTitle").textContent = MODES[mode].title; if (run) run.stop(); layout(B); run = tween(A ? 700 : 0, k => paint(A || B, B, k)); shown = B }
  function setPin(k) { pin = k; layout(shown); paint(shown, shown, 1); table() }
  function setHot(k) { hot = k; layout(shown); paint(shown, shown, 1); [...$("tbl").querySelectorAll("tbody tr")].forEach(tr => tr.classList.toggle("hot", +tr.dataset.k === k)) }

  // ---- table with a strip of every month's profit per ride
  const COLS = [["Ride", "name"], ["Riders", "riders"], ["Profit", "profit"], ["Per rider", "per"], ["Each month’s profit", null]];
  const step = Math.min(4.8, 150 / n), cellX = i => 1 + i * step + YEARS.indexOf(M[i].y) * 4, stripW = cellX(n - 1) + step + 2;
  function table() {
    const hr = $("tbl").querySelector("thead tr"), tb = $("tbl").querySelector("tbody"), ae = document.activeElement, fk = ae && $("tbl").contains(ae) ? ae.getAttribute("data-f") : null;
    hr.replaceChildren(); tb.replaceChildren();
    COLS.forEach(([l, k]) => { const th = H("th", { scope: "col" }, hr); if (!k) { th.textContent = l; th.style.textAlign = "left"; th.style.paddingLeft = "10px"; return } th.setAttribute("aria-sort", sortKey === k ? (sortDir < 0 ? "descending" : "ascending") : "none"); H("button", { type: "button", "data-f": "sort-" + k }, th, l).addEventListener("click", () => { sortDir = sortKey === k ? -sortDir : (k === "name" ? 1 : -1); sortKey = k; table() }) });
    const val = (r, k) => k === "name" ? r.short : !exists(r, cur) ? -1e9 : k === "per" ? (earning(r, cur) ? perRider(r, cur) : -1) : r[k][cur] || 0;
    R.map((r, k) => ({ r, k })).filter(o => exists(o.r, cur)).sort((a, b) => { const x = val(a.r, sortKey), y = val(b.r, sortKey); return (x < y ? -1 : x > y ? 1 : 0) * sortDir }).forEach(({ r, k }) => {
      const tr = H("tr", { "data-k": k, class: (pin === k ? "pinned " : "") + (earning(r, cur) ? "" : "idle") }, tb), b = H("button", { class: "pin", type: "button", "data-f": "pin-" + k, "aria-pressed": String(pin === k), title: "Pin " + r.name + " on the chart" }, H("td", {}, tr));
      H("i", { style: "background:" + FAM[r.fam] }, b); b.append(r.short);
      H("span", { class: "sub" }, b, (!r.open[cur] ? "closed, " : !r.riders[cur] ? "no riders at " : "age " + r.age[cur] + " mo, ") + usd2(r.pmode[cur] != null ? r.pmode[cur] : r.price[cur]));
      b.addEventListener("click", () => setPin(pin === k ? null : k)); tr.addEventListener("mouseenter", () => setHot(k)); tr.addEventListener("mouseleave", () => setHot(null));
      H("td", { class: "num" }, tr, num(r.riders[cur] || 0)); H("td", { class: "num" }, tr, usd(r.profit[cur] || 0)); H("td", { class: "num" }, tr, earning(r, cur) ? usd2(perRider(r, cur)) : "–");
      const s = S("svg", { viewBox: "0 0 " + stripW.toFixed(1) + " 26", role: "img", "aria-label": "Profit by month for " + r.name + ", " + usd(sum(r.profit)) + " in total", style: "width:168px;margin-left:10px" }, H("td", {}, tr));
      for (let i = 0; i < n; i++) {
        if (!exists(r, i)) continue;
        const x = cellX(i), e = earning(r, i);
        S("rect", { x: x + .5, y: 6.5, width: step * .71, height: 14, fill: e ? "#12239e" : "#fff", "fill-opacity": e ? clamp(.12 + .88 * Math.sqrt(r.profit[i] / PMAX), 0, 1) : 1, stroke: e ? "none" : r.open[i] ? "#e66c37" : "#a19f9d", "stroke-width": e ? 0 : r.open[i] ? 1.2 : .8 }, s);
        if (i === cur) S("rect", { x: x - .6, y: 23, width: step * 1.17, height: 3, fill: "#f2c811" }, s);
      }
      r.reset.forEach(d => { const i = MI(+d.slice(0, 4), +d.slice(5, 7)); if (i >= 0) S("circle", { cx: cellX(i) + step * .46, cy: 2.5, r: 2.3, fill: "#f2c811", stroke: "#8a6d00", "stroke-width": .6 }, s) });
    });
    if (fk) { const node = $("tbl").querySelector('[data-f="' + fk + '"]'); if (node) node.focus() }
    $("tblTitle").textContent = "Rides in " + labF(cur);
  }
  const started = i => i > 0 ? R.filter(r => exists(r, i) && earning(r, i) && exists(r, i - 1) && !earning(r, i - 1)).length : 0;
  function texts() {
    const live = R.filter(r => exists(r, cur)), earn = live.filter(r => earning(r, cur)), idle = live.length - earn.length, best = earn.slice().sort((a, b) => b.profit[cur] - a.profit[cur])[0], eff = earn.filter(r => r.riders[cur] >= 20).sort((a, b) => perRider(b, cur) - perRider(a, cur))[0], prev = started(cur);
    const p = ["In ", [labF(cur)], ", "];
    if (!live.length) p.push("no ride had been built yet.");
    else {
      if (best) { p.push([best.name], " earned the most (", { mark: usd(best.profit[cur]) }, ")"); if (eff && eff !== best) p.push(" and ", [eff.name], " earned the most per rider (", [usd2(perRider(eff, cur))], ")."); else if (eff) p.push(", and the most per rider (", [usd2(perRider(eff, cur))], ")."); else p.push(".") } else p.push("no ride earned anything.");
      if (idle) p.push(" ", [plural(idle, "ride", "rides")], " of " + live.length + " earned nothing."); else p.push(" Every ride earned.");
      if (prev) p.push(" ", [plural(prev, "ride", "rides")], " that earned nothing the month before started earning.");
    }
    say($("finding"), p);
    $("when").value = cur; $("whenOut").textContent = lab(cur);
    chips("yrs", YEARS.map(y => [String(y), y]), M[cur].y, y => { stop(); const i = MI(y, M[cur].m); moveTo(i >= 0 ? i : M.findIndex(r => r.y === y)) });
    chips("mos", M.filter(r => r.y === M[cur].y).map(r => [MONTHS[r.m - 3], r.m]), M[cur].m, m => { stop(); moveTo(MI(M[cur].y, m)) });
    table();
  }
  function stop() { if (timer) { clearTimeout(timer); timer = null } $("play").textContent = "Play" }
  function play() { if (timer) { stop(); return } $("play").textContent = "Pause"; const i = cur >= n - 1 ? 0 : cur + 1; moveTo(i, cur >= n - 1 ? 0 : 560); (function next() { timer = setTimeout(() => { if (cur >= n - 1) { stop(); return } moveTo(cur + 1, 560); next() }, REDUCED ? 1100 : 760) })() }
  $("play").addEventListener("click", play);
  $("when").max = n - 1;
  $("when").addEventListener("input", e => { stop(); moveTo(+e.target.value, 260) });
  $("mode").addEventListener("click", e => { const b = e.target.closest("button"); if (b) setMode(b.dataset.m) });
  $("runTitle").textContent = "Run the " + (SCOPE.parks > 1 ? "parks' " : "park's ") + plural(n, "month", "months") + ".";
  // The page opens on the month the most rides left the "earned nothing" lane (the latest on a tie): one month early, then it steps in.
  let turnMonth = 0, most = 0;
  for (let i = 1; i < n; i++) if (started(i) >= most && started(i) > 0) { most = started(i); turnMonth = i }
  setup(); setMode("earn");
  if (turnMonth) { moveTo(turnMonth - 1, 0); timer = setTimeout(() => { timer = null; moveTo(turnMonth, REDUCED ? 0 : 900) }, 900) } else moveTo(cur, 0);
})();
