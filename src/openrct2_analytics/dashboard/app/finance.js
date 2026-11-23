// Finance: a profit bridge between any two monthly statements, then the same change ride by ride.
"use strict";
(function () {
  if (!READY) return;
  const n = M.length;
  if (n < 2) { say($("finding"), ["Only one monthly statement is in the working copy, so there is no month to compare it with yet."]); return }
  let mode = "prev", custom = null, run = null;
  const fromOf = t => mode === "custom" ? custom : mode === "yoy" ? MI(M[t].y - 1, M[t].m) : t - 1, ok = t => { const f = fromOf(t); return f >= 0 && f !== t };
  const steps = (a, b) => LINES.map(([name, key, sg]) => ({ name, key, sg, va: M[a][key], vb: M[b][key], d: (M[b][key] - M[a][key]) * sg }));
  const say$ = d => d.name.toLowerCase() + (d.sg > 0 ? (d.vb >= d.va ? " up " : " down ") : (d.vb >= d.va ? " cost up " : " cost down ")) + usd(Math.abs(d.vb - d.va));
  const top = list => list.slice().sort((x, y) => Math.abs(y.d) - Math.abs(x.d))[0];
  if (!M.some(r => MI(r.y - 1, r.m) >= 0)) $("mode").querySelector('[data-m="yoy"]').setAttribute("disabled", "");

  // ---- the strip of every month, grouped by company year
  const yearW = 756 / YEARS.length, step = Math.min(22.2, (yearW - 16) / SEASON), bw = step * .77;
  const SX = i => 4 + YEARS.indexOf(M[i].y) * yearW + (M[i].m - 3) * step, SY = lin(0, Math.max(...M.map(r => r.profit), 1) * 1.04, 86, 8), sg = [];
  function setupStrip() {
    const s = $("strip");
    M.forEach((r, i) => {
      const x = SX(i), g = S("g", { role: "button", tabindex: -1 }, s);
      S("rect", { x: x - 2, y: 2, width: bw + 4, height: 100, fill: "#fff", opacity: 0 }, g);
      const h = r.profit < 0 ? Math.min(12, Math.max(1.5, SY(r.profit) - 86)) : Math.max(1.5, 86 - SY(r.profit));
      const bar = S("rect", { x, width: bw, y: r.profit < 0 ? 86 : 86 - h, height: h }, g), cap = S("rect", { x, width: bw, y: 90, height: 3, fill: "#f2c811", opacity: 0 }, g);
      S("text", { x: x + bw / 2, y: 104, "text-anchor": "middle", style: "font-size:10px" }, g, MONTHS[r.m - 3][0]);
      if (i === 0 || M[i - 1].y !== r.y) S("text", { x: 4 + YEARS.indexOf(r.y) * yearW + (7 * step + bw) / 2, y: 116, "text-anchor": "middle", style: "font-size:11px;fill:#252423;font-weight:600" }, s, r.y);
      g.addEventListener("click", e => { if (e.shiftKey) { if (i !== to) { mode = "custom"; custom = i; render() } } else choose(i) });
      g.addEventListener("keydown", e => { const d = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0; if (d) { e.preventDefault(); let t = to + d; while (t >= 0 && t < n && !ok(t)) t += d; if (t >= 0 && t < n) { choose(t); sg[t].g.focus() } } });
      bindTip(g, () => [labF(i), "Operating profit " + usd(r.profit), "Revenue " + usd(r.rev) + ", costs " + usd(r.costs)]);
      sg.push({ g, bar, cap });
    });
    S("line", { x1: 0, x2: 756, y1: 86.5, y2: 86.5, stroke: "#c8c6c4" }, s);
    $("stripSub").textContent = plural(n, "monthly statement", "monthly statements") + "; left and right arrow keys step through them";
  }
  function paintStrip() {
    const f = fromOf(to);
    sg.forEach((o, i) => {
      const r = M[i], can = ok(i) || i === f;
      o.bar.setAttribute("fill", r.profit < 0 ? "#e66c37" : i === to ? "#12239e" : i === f ? "#118dff" : "#9fd0ff"); o.bar.setAttribute("opacity", can ? 1 : .45); o.cap.setAttribute("opacity", i === to ? 1 : 0);
      set(o.g, { tabindex: i === to ? 0 : -1, "aria-pressed": String(i === to), "aria-disabled": String(!can), "aria-label": labF(i) + ": operating profit " + usd(r.profit) + (i === f ? " (starting month)" : "") });
    });
  }

  // ---- the bridge: starting profit, one bar per statement line, ending profit
  const NB = LINES.length + 2, BS = (756 - 58) / NB, TW = BS * .774, SW = BS * .659, BX = i => 58 + i * BS, B = { bars: [], cur: null };
  function setupBridge() {
    const s = $("bridge");
    B.grid = S("g", {}, s); B.zero = S("line", { x1: 50, x2: 756, stroke: "#605e5c" }, s);
    for (let i = 0; i < NB; i++) {
      const total = i === 0 || i === NB - 1, cx = BX(i) + BS * .444;
      const o = { r: S("rect", { x: BX(i) + (total ? 4 : 8), width: total ? TW : SW, tabindex: 0 }, s), t: S("text", { x: cx, "text-anchor": "middle", style: "font-size:12px;font-weight:700;fill:#252423" }, s), c: i < NB - 1 ? S("line", { x1: BX(i) + (total ? 4 + TW : 8 + SW), x2: BX(i + 1) + (i === NB - 2 ? 4 : 8), stroke: "#605e5c", "stroke-dasharray": "2 2" }, s) : null, l1: S("text", { x: cx, y: 394, "text-anchor": "middle", style: "font-size:12px;fill:#252423" + (total ? ";font-weight:700" : "") }, s), l2: S("text", { x: cx, y: 409, "text-anchor": "middle", style: "font-size:12px;fill:" + (total ? "#605e5c" : "#252423") }, s) };
      if (!total) { o.l1.textContent = LINES[i - 1][3]; o.l2.textContent = LINES[i - 1][4] } else o.l2.textContent = "profit";
      bindTip(o.r, () => o.tip); B.bars.push(o);
    }
  }
  function bridgeTarget() {
    const a = fromOf(to), st = steps(a, to);
    let lvl = M[a].profit;
    const bars = [{ a: 0, b: lvl, kind: "total", val: usd(lvl), tip: [labF(a), "Operating profit " + usd(lvl)] }];
    st.forEach(d => {
      const what = Math.abs(d.d) < .5 ? "No change" : (d.sg < 0 ? (d.d > 0 ? "Lower cost adds " : "Higher cost takes ") : (d.d > 0 ? "Adds " : "Takes ")) + usd(Math.abs(d.d)) + (d.d > 0 ? " to profit" : " from profit");
      bars.push({ a: lvl, b: lvl + d.d, kind: d.d >= 0 ? "up" : "down", val: Math.abs(d.d) < .5 ? "$0" : plus(d.d), tip: [d.name, usd(d.va) + " in " + lab(a) + ", " + usd(d.vb) + " in " + lab(to), what] });
      lvl += d.d;
    });
    bars.push({ a: 0, b: M[to].profit, kind: "total", val: usd(M[to].profit), tip: [labF(to), "Operating profit " + usd(M[to].profit)] });
    const all = bars.flatMap(b => [b.a, b.b]), lo = Math.min(0, ...all), hi = Math.max(...all), pad = (hi - lo) * .09;
    return { bars, lo: lo < 0 ? lo - pad : 0, hi: hi + pad };
  }
  function paintBridge(st, tg) {
    const y = lin(st.lo, st.hi, 372, 8);
    B.grid.replaceChildren();
    niceTicks(tg.lo, tg.hi).forEach(v => { S("line", { x1: 50, x2: 756, y1: y(v), y2: y(v), stroke: "#edebe9" }, B.grid); S("text", { x: 44, y: y(v) + 4, "text-anchor": "end" }, B.grid, tick$(v)) });
    set(B.zero, { y1: y(0), y2: y(0) });
    st.bars.forEach((b, i) => {
      const o = B.bars[i], t = tg.bars[i], ya = y(b.a), yb = y(b.b), top = Math.min(ya, yb), h = Math.max(1.5, Math.abs(ya - yb));
      set(o.r, { y: top, height: h, fill: t.kind === "total" ? "#12239e" : t.kind === "up" ? "#118dff" : "#e66c37" });
      o.t.textContent = t.val; o.t.setAttribute("y", t.kind === "down" ? top + h + 14 : top - 5); o.tip = t.tip; o.r.setAttribute("aria-label", t.tip.join(". ")); o.r.setAttribute("role", "img");
      if (o.c) set(o.c, { y1: yb, y2: yb });
    });
  }
  function animateBridge(first) {
    const tg = bridgeTarget(), last = NB - 1, from = B.cur && !first ? B.cur : { lo: tg.lo, hi: tg.hi, bars: tg.bars.map((b, i) => ({ a: i === last ? 0 : tg.bars[0].b * (i ? 1 : 0), b: i === last ? 0 : i ? tg.bars[0].b : 0 })) };
    if (run) run.stop();
    // each bar starts a beat after the one before it, so the eye walks the bridge left to right
    run = tween(first ? 1500 : 800, (e, k) => { const st = { lo: lerp(from.lo, tg.lo, e), hi: lerp(from.hi, tg.hi, e), bars: tg.bars.map((b, i) => { const p = ease(clamp((k - i * .06) / .46, 0, 1)); return { a: lerp(from.bars[i].a, b.a, p), b: lerp(from.bars[i].b, b.b, p) } }) }; B.cur = st; paintBridge(st, tg) });
    B.bars[0].l1.textContent = lab(fromOf(to)); B.bars[last].l1.textContent = lab(to);
  }

  // ---- ride by ride, from the daily ride readings
  const mKey = i => M[i].y + "-" + String(M[i].m).padStart(2, "0");
  function tagOf(r, a, b) {
    const t = [], was = r.open[a], now = r.open[b];
    if (was == null && now != null) t.push("new this month"); else if (!was && now > 0) t.push("opened"); else if (was > 0 && !now) t.push("closed");
    if (r.reset.some(d => d > mKey(a) + "-00" && d < mKey(b) + "-99")) t.push("age reset");
    if (was > 0 && now > 0 && r.pmode[a] !== r.pmode[b] && r.pmode[a] != null && r.pmode[b] != null) t.push(usd2(r.pmode[a]).replace(".00", "") + " to " + usd2(r.pmode[b]).replace(".00", ""));
    if (now > 0 && !r.riders[a] && r.riders[b] > 0 && was > 0) t.push(sum(r.riders.slice(0, a + 1)) ? "riders returned" : "first riders");
    return t.join(", ");
  }
  const ridesBetween = (a, b) => RIDES.filter(r => r.open[a] != null || r.open[b] != null).map(r => ({ r, d: (r.profit[b] || 0) - (r.profit[a] || 0), tag: tagOf(r, a, b) })).sort((x, y) => y.d - x.d);
  function paintRides() {
    const s = $("rides"), a = fromOf(to), rows = ridesBetween(a, to), lo = Math.min(0, ...rows.map(r => r.d)), hi = Math.max(0, ...rows.map(r => r.d)), x = lin(lo, hi || 1, 108, 330), zx = x(0);
    s.replaceChildren(); s.setAttribute("viewBox", "0 0 396 " + Math.max(424, rows.length * 30 + 4));
    rows.forEach((o, i) => {
      const y = 4 + i * 30, g = S("g", { tabindex: 0, role: "img", "aria-label": o.r.name + ": " + plus(o.d) + (o.tag ? ", " + o.tag : "") }, s);
      S("rect", { x: 0, y: y - 2, width: 396, height: 28, fill: "#fff", opacity: 0 }, g);
      S("text", { x: 0, y: y + 11, style: "font-size:12px;fill:#252423" }, g, o.r.short);
      if (o.tag) S("text", { x: 0, y: y + 24, style: "font-size:11px;fill:#605e5c" }, g, o.tag);
      const bar = S("rect", { x: zx, y, width: 0, height: 13, fill: o.d >= 0 ? "#118dff" : "#e66c37" }, g), xe = x(o.d), lbl = S("text", { x: (o.d >= 0 ? xe : zx) + 5, y: y + 11, style: "font-size:12px;fill:#252423;font-weight:600", opacity: 0 }, g, Math.abs(o.d) < .5 ? "$0" : plus(o.d));
      tween(500, e => { const w = Math.abs(xe - zx) * e; set(bar, { x: o.d >= 0 ? zx : zx - w, width: Math.max(.5, w) }); lbl.setAttribute("opacity", e) });
      bindTip(g, [o.r.name, "Profit " + usd(o.r.profit[a] || 0) + " in " + lab(a) + ", " + usd(o.r.profit[to] || 0) + " in " + lab(to), "Riders " + num(o.r.riders[a] || 0) + ", then " + num(o.r.riders[to] || 0), o.tag || "No change in price or status"]);
    });
    S("line", { x1: zx, x2: zx, y1: 0, y2: rows.length * 30, stroke: "#605e5c" }, s);
    const tot = sum(rows.map(r => r.d)), stmt = (M[to].rides - M[to].running) - (M[a].rides - M[a].running);
    $("recon").textContent = "The ride bars add up to " + plus(tot) + ". The statement's own figure for ride income less running costs is " + plus(stmt) + ".";
    return rows;
  }

  // ---- the largest moves, the sentence, and the controls
  const MOVES = [];
  for (let i = 1; i < n; i++) MOVES.push({ i, d: M[i].profit - M[i - 1].profit, top: top(steps(i - 1, i)) });
  MOVES.sort((a, b) => Math.abs(b.d) - Math.abs(a.d));
  let to = MOVES[0].i;
  function paintMoves() {
    const ol = $("moves");
    if (ol.firstChild) { [...ol.querySelectorAll("button")].forEach((b, k) => b.setAttribute("aria-pressed", String(mode === "prev" && to === MOVES[k].i))); return }
    MOVES.slice(0, 5).forEach(m => { const b = H("button", { type: "button", "aria-pressed": String(mode === "prev" && to === m.i) }, H("li", {}, ol)); H("span", {}, b, lab(m.i)); H("span", { class: "amt " + (m.d >= 0 ? "up" : "down") }, b, plus(m.d)); H("span", { class: "why" }, b, say$(m.top)); b.addEventListener("click", () => { mode = "prev"; choose(m.i) }) });
  }
  function paintText(rows) {
    const a = fromOf(to), d = M[to].profit - M[a].profit, st = steps(a, to), t = top(st);
    const p = [[labF(to)], " made ", { mark: usd(M[to].profit) }, " operating profit, ", [usd(Math.abs(d)) + (d >= 0 ? " more" : " less")], " than " + labF(a) + ". "];
    if (Math.abs(t.d) > .5) {
      p.push([t.name], " accounts for ", [plus(t.d)], " of the change");
      const lead = t.d >= 0 ? rows[0] : rows[rows.length - 1];
      if (t.key === "rides" && lead && Math.sign(lead.d) === Math.sign(t.d)) p.push(", led by ", [lead.r.name], " (" + plus(lead.d) + (lead.tag ? "; " + lead.tag : "") + ").");
      else if (t.sg < 0) p.push(": " + (t.vb > t.va ? "that cost rose" : "that cost fell") + " from " + usd(t.va) + " to " + usd(t.vb) + ".");
      else p.push(".");
    }
    say($("finding"), p);
    $("bridgeTitle").textContent = "What moved operating profit from " + labF(a) + " to " + labF(to);
    $("bridgeDesc").textContent = "Bridge from " + usd(M[a].profit) + " to " + usd(M[to].profit) + ": " + st.map(x => x.name + " " + plus(x.d)).join(", ") + ".";
  }
  function choose(i) { if (i < 0) return; if (!ok(i) && mode === "custom") mode = "prev"; while (i < n && !ok(i)) i++; if (i >= n) return; to = i; render() }
  function render(first) {
    if (!ok(to)) { let t = 0; while (t < n && !ok(t)) t++; to = t < n ? t : to }
    const yearMonths = M.filter(r => r.y === M[to].y);
    chips("yrs", YEARS.map(y => [String(y), y]), M[to].y, y => choose(MI(y, M[to].m) >= 0 ? MI(y, M[to].m) : M.findIndex(r => r.y === y)));
    chips("mos", yearMonths.map(r => [MONTHS[r.m - 3], r.m]), M[to].m, m => choose(MI(M[to].y, m)));
    [...$("mode").querySelectorAll("button")].forEach(b => b.setAttribute("aria-pressed", String(b.dataset.m === mode)));
    $("modeLabel").textContent = mode === "custom" ? "Starting from " + lab(custom) + ". Start from" : "Start from";
    paintStrip(); paintMoves(); animateBridge(first); paintText(paintRides());
  }
  $("mode").addEventListener("click", e => { const b = e.target.closest("button"); if (b && !b.hasAttribute("disabled")) { mode = b.dataset.m; render() } });
  setupStrip(); setupBridge(); render(true);
})();
