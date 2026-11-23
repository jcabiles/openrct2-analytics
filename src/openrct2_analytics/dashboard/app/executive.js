// Executive: each company year's operating profit raced month by month against the year before.
"use strict";
(function () {
  if (!READY) return;
  // slot[y][m - 3] is the record of company month m in year y, or null: a year can start late or skip a month.
  const slot = {};
  M.forEach(r => (slot[r.y] = slot[r.y] || Array(SEASON).fill(null))[r.m - 3] = r);
  // Season positions run 1 (March) to SEASON (October): have(y) lists those with a record, end(y) is the last.
  const have = y => slot[y].flatMap((r, i) => r ? [i + 1] : []), end = y => slot[y] ? Math.max(0, ...have(y)) : 0;
  const full = y => !!slot[y] && have(y).length === SEASON;
  // The position at or before s that has a record in y, else the first one that has; next is the first at or after s.
  const near = (y, s) => have(y).filter(v => v <= s).pop() || have(y)[0], cur = (y, t) => near(y, Math.ceil(t - 1e-6));
  const next = (y, s) => have(y).find(v => v >= s) || near(y, s);
  // Running totals, one per month end up to end(y); an empty slot adds nothing.
  const cum = (y, k) => { let s = 0; return [0, ...slot[y].slice(0, end(y)).map(r => s += r ? r[k] : 0)] };
  // A running total at season position t (between two month ends), held at its last month.
  const at = (a, t) => { const n = a.length - 1; if (t >= n) return a[n]; const i = Math.floor(t); return lerp(a[i], a[i + 1], t - i) };
  const ALL = YEARS.flatMap(y => cum(y, "profit")), CLO = Math.min(0, ...ALL), CHI = Math.max(...ALL, 1) * 1.04;
  const BMAX = Math.max(...M.map(r => Math.abs(r.profit)), 1) * 1.04;
  const X = i => 52 + i * 91, Yc = lin(CLO, CHI, 262, 16), Yb = lin(0, BMAX, 376, 302), COL = { focus: "#12239e", prior: "#118dff", other: "#c8c6c4" };
  // Monthly bars grow up from 376; a loss is drawn as a short stub below the line, labelled with its value.
  const bar = v => v >= 0 ? { y: Yb(v), height: Math.max(1, 376 - Yb(v)) } : { y: 376, height: Math.max(1, Math.min(12, Yb(v) - 376)) };
  const pathTo = (a, t) => { t = Math.min(t, a.length - 1); let d = ""; for (let i = 0; i <= Math.floor(t); i++) d += (i ? "L" : "M") + X(i) + " " + Yc(a[i]).toFixed(1); if (t % 1) d += "L" + X(t).toFixed(1) + " " + Yc(at(a, t)).toFixed(1); return d };
  let Y = YEARS[YEARS.length - 1], c = end(Y), cf = 0, run = null, R = {};

  // The month end after which a closed year pulled away from the year before: the last month end,
  // from May on, where the two were within a tenth of the final gap; 0 when there is none.
  function turn(y) {
    if (!slot[y - 1] || !full(y)) return 0;
    const a = cum(y, "profit"), b = cum(y - 1, "profit"), L = a[SEASON] - at(b, SEASON);
    let k = 0;
    for (let i = 3; i < SEASON; i++) if (Math.abs(a[i] - at(b, i)) < Math.abs(L) * .1) k = i;
    return k;
  }
  // The note on the chart where the two year lines part, with the rides that started earning next.
  function noteFor(y) {
    const k = turn(y);
    if (!k) return null;
    const lines = ["End of " + MFULL[k - 1] + ": level with " + (y - 1) + "."], i = MI(y, k + 2), j = MI(y, k + 3);
    const started = j < 0 ? [] : RIDES.filter(r => exists(r, i) && !earning(r, i) && earning(r, j));
    if (started.length) {
      const count = {};
      started.forEach(r => count[r.fam] = (count[r.fam] || 0) + 1);
      const [fam, n] = Object.entries(count).sort((p, q) => q[1] - p[1])[0], [one, many] = FAMS[fam];
      lines.push(n === started.length ? "Then " + plural(n, one + " starts", many + " start") + " earning."
        : "Then " + plural(started.length, "ride starts", "rides start") + " earning, " + n + " of them " + (n === 1 ? "a " + one : many) + ".");
    }
    return { at: k, lines };
  }

  function drawRace() {
    const s = $("race");
    [...s.querySelectorAll("g")].forEach(g => g.remove());
    const g = S("g", {}, s), P = Y - 1, hasP = !!slot[P];
    niceTicks(CLO, CHI).forEach(v => { S("line", { x1: 52, x2: 780, y1: Yc(v), y2: Yc(v), stroke: "#edebe9" }, g); S("text", { x: 46, y: Yc(v) + 4, "text-anchor": "end" }, g, tick$(v)) });
    for (let i = 1; i <= SEASON; i++) { S("line", { x1: X(i), x2: X(i), y1: 16, y2: 376, stroke: "#f3f2f1" }, g); S("text", { x: X(i - .5), y: 280, "text-anchor": "middle" }, g, MONTHS[i - 1]) }
    S("line", { x1: 52, x2: 780, y1: 376, y2: 376, stroke: "#c8c6c4" }, g);
    S("text", { x: 52, y: 296, style: "font-size:11px" }, g, "Profit each month");
    // faint full-season lines for every year, then the bold "to date" lines that follow the cursor
    const ends = [];
    YEARS.forEach(y => { const a = cum(y, "profit"), role = y === Y ? "focus" : y === P ? "prior" : "other"; S("path", { d: pathTo(a, end(y)), fill: "none", stroke: COL[role], "stroke-width": 1.5, opacity: role === "other" ? 1 : .3 }, g); ends.push({ y, role, v: a[end(y)], py: Yc(a[end(y)]) }) });
    ends.sort((a, b) => a.py - b.py);
    for (let i = 1; i < ends.length; i++) if (ends[i].py - ends[i - 1].py < 15) ends[i].py = ends[i - 1].py + 15;
    ends.forEach(e => { const t = S("text", { x: 788, y: e.py + 4, style: "font-size:12px;font-weight:" + (e.role === "other" ? 400 : 700) + ";fill:" + (e.role === "focus" ? "#12239e" : e.role === "prior" ? "#0b6bcb" : "#605e5c") }, g, e.y + "  "); S("tspan", { style: "font-weight:400" }, t, usdK(e.v)) });
    R = { ribbon: S("path", { fill: "#f2c811", opacity: .38 }, g), prior: hasP ? S("path", { fill: "none", stroke: COL.prior, "stroke-width": 2.5, "stroke-linejoin": "round" }, g) : null, focus: S("path", { fill: "none", stroke: COL.focus, "stroke-width": 3.5, "stroke-linejoin": "round", "stroke-linecap": "round" }, g), bars: [] };
    slot[Y].forEach((r, i) => {
      if (!r) return;
      const cx = X(i + .5), pr = hasP ? slot[P][i] : null, b = {};
      if (pr) b.p = S("rect", { x: cx - 23, width: 21, ...bar(pr.profit), fill: COL.prior }, g);
      b.f = S("rect", { x: pr ? cx + 2 : cx - 11, width: 21, ...bar(r.profit), fill: COL.focus }, g);
      b.t = S("text", { x: cx, y: Math.min(bar(r.profit).y, pr ? bar(pr.profit).y : 376, 376) - 4, "text-anchor": "middle", style: "font-size:11px;fill:#12239e;font-weight:600" }, g, usdK(r.profit));
      if (r.mkt > 0) S("path", { d: `M${cx - 5} 388L${cx + 5} 388L${cx} 380Z`, fill: "#f2c811", stroke: "#8a6d00", "stroke-width": .75 }, g);
      R.bars[i] = b;
    });
    const n = noteFor(Y);
    R.noteAt = n ? n.at : null;
    if (n) { const a = cum(Y, "profit"), px = X(n.at), py = Yc(a[n.at]); R.note = S("g", { opacity: 0 }, g); S("line", { x1: px - 6, y1: py - 8, x2: px - 22, y2: py - 44, stroke: "#252423" }, R.note); S("circle", { cx: px, cy: py, r: 9, fill: "none", stroke: "#252423", "stroke-width": 1.5 }, R.note); n.lines.forEach((l, i) => S("text", { x: px - 18, y: py - 68 + i * 16, "text-anchor": "end", style: "font-size:13px;fill:#252423;font-weight:" + (i ? 400 : 700) }, R.note, l)) }
    R.cur = S("line", { y1: 16, y2: 376, stroke: "#605e5c", "stroke-dasharray": "3 3" }, g);
    R.dp = hasP ? S("circle", { r: 4.5, fill: "#fff", stroke: COL.prior, "stroke-width": 2.5 }, g) : null;
    R.df = S("circle", { r: 5.5, fill: COL.focus, stroke: "#fff", "stroke-width": 1.5 }, g);
    R.gap = S("g", {}, g); R.gapBox = S("rect", { height: 22, fill: "#fff", stroke: "#f2c811", "stroke-width": 1.5 }, R.gap); R.gapTxt = S("text", { y: 15, style: "font-size:12px;font-weight:700;fill:#252423" }, R.gap);
    R.handle = S("circle", { cy: 262, r: 7, fill: COL.focus, stroke: "#fff", "stroke-width": 2 }, g);
    $("raceSub").textContent = hasP ? Y + " against " + P + " at the same point in the season" : Y + ", with no earlier year to compare";
    $("raceDesc").textContent = "Running total of operating profit by month for each company year. " + YEARS.map(y => y + (full(y) ? " closed at " : " stands at ") + usd(cum(y, "profit")[end(y)]) + (full(y) ? "" : " through " + MFULL[end(y) - 1])).join("; ") + ".";
  }
  function drawCursor() {
    const t = cf, P = Y - 1, a = cum(Y, "profit"), b = slot[P] ? cum(P, "profit") : null, x = X(t), fy = Yc(at(a, t));
    R.focus.setAttribute("d", pathTo(a, t)); set(R.cur, { x1: x, x2: x }); set(R.df, { cx: x, cy: fy }); R.handle.setAttribute("cx", x);
    if (b) {
      const py = Yc(at(b, t));
      R.prior.setAttribute("d", pathTo(b, t)); set(R.dp, { cx: x, cy: py });
      let back = "";
      for (let i = Math.min(Math.floor(t), b.length - 1); i >= 0; i--) back += "L" + X(i) + " " + Yc(b[i]).toFixed(1);
      R.ribbon.setAttribute("d", t > 0 ? pathTo(a, t) + "L" + x.toFixed(1) + " " + py.toFixed(1) + back + "Z" : "");
      const gap = at(a, t) - at(b, t), label = (gap >= 0 ? "+" : "") + usdK(gap) + " vs " + P, w = label.length * 6.9 + 14, left = x > 640;
      R.gapTxt.textContent = label; R.gapBox.setAttribute("width", w); set(R.gapTxt, { x: 7 });
      R.gap.setAttribute("transform", `translate(${(left ? x - w - 12 : x + 12).toFixed(1)} ${(clamp((fy + py) / 2 - 11, 20, 236)).toFixed(1)})`); R.gap.setAttribute("opacity", t > 0 ? 1 : 0);
    } else { R.ribbon.setAttribute("d", ""); R.gap.setAttribute("opacity", 0) }
    R.bars.forEach((bar, i) => { const on = i < Math.ceil(t - 1e-6) ? 1 : .22; bar.f.setAttribute("opacity", on); if (bar.p) bar.p.setAttribute("opacity", on); bar.t.setAttribute("opacity", i === Math.ceil(t - 1e-6) - 1 ? 1 : 0) });
    if (R.note) R.note.setAttribute("opacity", clamp((t - R.noteAt) * 2, 0, 1));
    drawKpis(t); drawLead(t);
  }
  function kpiTile(label) { const d = H("div", { class: "v kpi" }, $("kpis")); H("div", { class: "l" }, d, label); const n = H("div", { class: "n" }, d), s = S("svg", { viewBox: "0 0 96 34", "aria-hidden": "true" }, d), dl = H("div", { class: "d" }, d); return { n, s, dl, l: d.firstChild } }
  const K = [];
  function drawKpis(t) {
    const P = Y - 1, hasP = !!slot[P], mi = cur(Y, t), mon = MFULL[mi - 1];
    const defs = [["Operating profit, season to date", "profit", usdK], ["Revenue, season to date", "rev", usdK], ["Guest visits, season to date", "visits", num]];
    if (!K.length) { defs.forEach(d => K.push(kpiTile(d[0]))); K.push(kpiTile("")) }
    defs.forEach(([, key, f], i) => {
      const a = cum(Y, key), v = at(a, t), k = K[i];
      k.n.textContent = f(v); spark(k.s, slot[Y].map(r => r && r[key]), mi);
      if (hasP) { const pv = at(cum(P, key), t), d = v - pv; k.dl.textContent = (d >= 0 ? "▲ " : "▼ ") + f(Math.abs(d)) + (pv > 0 ? " (" + Math.abs(d / pv * 100).toFixed(0) + "%)" : "") + (d >= 0 ? " more" : " less") + " than " + P + " to " + mon; k.dl.className = "d" + (d < 0 ? " neg" : "") } else { k.dl.textContent = "No earlier year to compare"; k.dl.className = "d flat" }
    });
    const k = K[3], cash = slot[Y][mi - 1].cash, prior = hasP ? slot[P][mi - 1] : null;
    k.l.textContent = "Cash in bank, end of " + mon; k.n.textContent = cash == null ? "–" : usdK(cash); spark(k.s, slot[Y].map(r => r && (r.cash || 0)), mi);
    if (prior && cash != null && prior.cash != null) { const d = cash - prior.cash; k.dl.textContent = (d >= 0 ? "▲ " : "▼ ") + usdK(Math.abs(d)) + (d >= 0 ? " more" : " less") + " than end of " + mon + " " + P; k.dl.className = "d" + (d < 0 ? " neg" : "") } else { k.dl.textContent = hasP && !prior ? "No " + mon + " last year to compare" : "No earlier year to compare"; k.dl.className = "d flat" }
  }
  function spark(s, vals, mi) { s.replaceChildren(); const mx = Math.max(...vals.map(Math.abs), 1); vals.forEach((v, i) => { if (v == null) return; const h = Math.max(1, Math.abs(v) / mx * 30); S("rect", { x: i * 12 + 1, y: v < 0 ? 32 : 32 - h, width: 9, height: v < 0 ? 2 : h, fill: i === mi - 1 ? "#12239e" : i < mi ? "#118dff" : "#d2d0ce" }, s) }) }
  let leadScale = null, leadRows = [];
  function setupLead() {
    const s = $("lead"), P = Y - 1, h = 12 + LINES.length * 20;
    s.replaceChildren(); leadRows = []; s.setAttribute("viewBox", "0 0 876 " + h);
    if (!slot[P]) { S("text", { x: 0, y: 24, style: "font-size:13px" }, s, Y + " was the first season, so there is no year before it to compare."); $("leadTitle").textContent = "What separates " + Y + " from the year before"; leadScale = null; return }
    let lo = 0, hi = 0;
    const series = LINES.map(([, k, sg]) => { const a = cum(Y, k), b = cum(P, k); return a.map((v, i) => (v - at(b, i)) * sg) });
    series.forEach(a => a.forEach(v => { lo = Math.min(lo, v); hi = Math.max(hi, v) }));
    const pad = (hi - lo) * .04;
    leadScale = { x: lin(lo - pad, hi + pad, 150, 800), series };
    const zx = leadScale.x(0);
    LINES.forEach(([name], i) => { const y = 6 + i * 20; S("text", { x: 140, y: y + 12, "text-anchor": "end", style: "font-size:12px;fill:#252423" }, s, name); leadRows.push({ r: S("rect", { y, height: 15 }, s), t: S("text", { y: y + 12, style: "font-size:12px;fill:#252423" }, s) }) });
    S("line", { x1: zx, x2: zx, y1: 2, y2: h - 6, stroke: "#605e5c" }, s);
  }
  function drawLead(t) {
    if (!leadScale) return;
    let total = 0;
    const zx = leadScale.x(0);
    leadScale.series.forEach((a, i) => { const v = at(a, t), x = leadScale.x(v), row = leadRows[i]; total += v; set(row.r, { x: Math.min(x, zx), width: Math.max(.5, Math.abs(x - zx)), fill: v >= 0 ? "#118dff" : "#e66c37" }); row.t.textContent = Math.abs(v) < .5 ? "$0" : plus(v); set(row.t, { x: (v >= 0 ? x : zx) + 6 }) });
    $("leadTitle").textContent = "What separates " + Y + " from " + (Y - 1) + " through " + MFULL[cur(Y, t) - 1] + ": " + plus(total, usdK);
  }
  function drawYears() {
    const s = $("years"), had = s.contains(document.activeElement), w = Math.min(66, 266 / YEARS.length);
    s.replaceChildren();
    const mx = Math.max(...YEARS.map(y => cum(y, "profit")[end(y)]), 1), h = lin(0, mx, 0, 112);
    YEARS.forEach((y, i) => {
      const v = cum(y, "profit")[end(y)], x = 10 + i * w, bw = w - 14, on = y === Y;
      const g = S("g", { class: "yearcol", tabindex: 0, role: "button", "aria-pressed": String(on), "aria-label": "Company year " + y + ", operating profit " + usd(v) + (full(y) ? "" : " through " + MFULL[end(y) - 1]) }, s);
      S("rect", { x: x - 4, y: 4, width: bw + 8, height: 164, fill: "#fff", opacity: 0 }, g);
      S("rect", { x, y: 146 - Math.max(0, h(v)), width: bw, height: Math.max(1, h(v)), fill: on ? "#12239e" : "#9fd0ff" }, g);
      S("text", { x: x + bw / 2, y: 140 - Math.max(0, h(v)), "text-anchor": "middle", style: "font-size:12px;font-weight:700;fill:" + (on ? "#12239e" : "#252423") }, g, usdK(v));
      S("text", { x: x + bw / 2, y: 163, "text-anchor": "middle", style: "font-size:12px;fill:#252423;font-weight:" + (on ? 700 : 400) }, g, y);
      if (on) S("rect", { x, y: 149, width: bw, height: 3, fill: "#f2c811" }, g);
      act(g, () => setYear(y));
      if (on && had) g.focus();
    });
  }
  function drawText() {
    const P = Y - 1, a = cum(Y, "profit"), mon = MFULL[c - 1], mx = Math.max(...slot[Y].map(r => r ? Math.abs(r.profit) : 0), 1);
    const sp = S("svg", { viewBox: "0 0 60 18", width: 60, height: 18, style: "display:inline-block;width:60px", "aria-hidden": "true" });
    slot[Y].forEach((r, i) => { if (!r) return; const h = Math.max(1, Math.abs(r.profit) / mx * 17); S("rect", { x: i * 7.5, y: 18 - h, width: 5.5, height: h, fill: i < c ? "#12239e" : "#c8c6c4" }, sp) });
    const closed = full(Y) && c === SEASON, fin = a[end(Y)];
    if (!slot[P]) {
      say($("finding"), closed ? [[String(Y)], " closed with ", { mark: usdK(fin) }, sp, " operating profit in its first season. There is no earlier year to compare."] : ["By the end of ", [mon + " " + Y], " the company had made ", { mark: usdK(a[c]) }, sp, " operating profit in its first season. There is no earlier year to compare."]);
      return;
    }
    const b = cum(P, "profit"), lead = a.map((v, i) => v - at(b, i)), L = lead[end(Y)];
    if (!closed) {
      const g = lead[c];
      say($("finding"), ["By the end of ", [mon + " " + Y], " the company had made ", { mark: usdK(a[c]) }, sp, " operating profit, ", [usdK(Math.abs(g)) + (g >= 0 ? " ahead of " : " behind ")], P + " at the same point." + (full(Y) ? " The season closed at " : ""), full(Y) ? [usdK(fin)] : "", full(Y) ? "." : ""]);
      return;
    }
    const base = at(b, SEASON);
    const parts = [[String(Y)], " closed with ", { mark: usdK(fin) }, sp, " operating profit, ", [base > 0 ? Math.abs(L / base * 100).toFixed(0) + "% " + (L >= 0 ? "more" : "less") : usdK(Math.abs(L)) + (L >= 0 ? " more" : " less")], " than " + P + ". "];
    const k = turn(Y);
    if (k) parts.push("At the end of ", [MFULL[k - 1]], " the two years were only ", [usdK(Math.abs(lead[k]))], " apart: the last ", [(SEASON - k) + " months"], " made the difference.");
    else { let pk = 1; for (let i = 2; i <= SEASON; i++) if (lead[i] > lead[pk]) pk = i; parts.push(pk < SEASON ? "Its lead was widest at the end of " : "Its lead grew through the season to ", [pk < SEASON ? MFULL[pk - 1] : usdK(L)], pk < SEASON ? ", at " : ".", pk < SEASON ? [usdK(lead[pk])] : "", pk < SEASON ? "." : "") }
    say($("finding"), parts);
  }
  // Which game year the shown company year Y is, for the shown month m: one line for a chosen park,
  // else one line per park, left blank after the name for a park not yet open in that month.
  function gameYearNote(m) {
    const one = PARK !== "all" ? DATA.parks.find(p => p.id === PARK) : DATA.parks.length === 1 ? DATA.parks[0] : null;
    const label = e => "Company year " + Y + " = game year " + e.game_year;
    if (one) return one.game_years[Y] ? label(one.game_years[Y]) : "";
    return DATA.parks.filter(p => SCOPE.park_ids.includes(p.id)).map(p => { const e = p.game_years[Y]; return p.name + ":" + (e && e.from_month <= m ? " " + label(e) : "") }).join("\n");
  }
  function settle() {
    chips("yrs", YEARS.map(y => [String(y), y]), Y, setYear);
    chips("mos", [["All", end(Y)], ...have(Y).filter(s => s < end(Y)).map(s => [MONTHS[s - 1], s])], c, v => go(v));
    $("thru").max = end(Y); $("thru").value = c; $("thruOut").textContent = MFULL[c - 1]; drawText();
    const r = slot[Y][c - 1];
    $("gameYears").textContent = gameYearNote(r.m);
    $("event").textContent = r.mkt > 0 ? "▲ " + MFULL[c - 1] + " " + Y + ": marketing campaign paid, " + usd(r.mkt) + "." : "▲ marks a month with a marketing payment.";
  }
  function go(to, ms) { if (run) run.stop(); const from = cf; to = to > c ? next(Y, to) : near(Y, to); c = to; settle(); run = tween(ms == null ? Math.max(220, Math.abs(to - from) * 160) : ms, k => { cf = lerp(from, to, k); drawCursor() }) }
  function setYear(y) { if (run) run.stop(); Y = y; c = near(Y, Math.min(c, end(Y))); cf = c; drawRace(); setupLead(); drawYears(); settle(); drawCursor() }
  function replay() {
    if (run) run.stop();
    const n = end(Y);
    cf = 0; c = n; settle(); drawCursor();
    if (REDUCED) { cf = n; drawCursor(); return }
    let t0 = null, off = false;
    run = { stop() { off = true } };
    // linear time so every month takes the same beat: half a second a month, 4 seconds for a season
    requestAnimationFrame(function f(t) { if (off) return; if (t0 == null) t0 = t; cf = Math.min(n, (t - t0) / 500); drawCursor(); if (cf < n) requestAnimationFrame(f) });
  }
  $("play").addEventListener("click", replay);
  $("thru").addEventListener("input", e => go(+e.target.value));
  onDrag($("race"), e => { const p = svgX($("race"), e), to = near(Y, clamp(Math.round((p.x - 52) / 91), 1, end(Y))); if (to !== c) go(to, 180) });
  setYear(Y);
  replay();
})();
