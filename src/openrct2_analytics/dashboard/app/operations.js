// Operations: one dot per park day that regroups by date, by weather and by months since marketing.
"use strict";
(function () {
  if (!READY) return;
  const P = SCOPE.days, N = P.date.length;
  const WEATHER = { sunny: ["Sunny", "#e8a500"], partiallyCloudy: ["Partly cloudy", "#7fb7e6"], cloudy: ["Cloudy", "#a19f9d"], rain: ["Rain", "#118dff"], heavyRain: ["Heavy rain", "#12239e"], thunder: ["Thunder", "#6b007b"], snow: ["Snow", "#c8c6c4"], heavySnow: ["Heavy snow", "#8a8886"], blizzard: ["Blizzard", "#3b3a39"] };
  const CODES = [...Object.keys(WEATHER), ...P.w].filter((c, i, a) => a.indexOf(c) === i && P.w.includes(c)), WX = CODES.map(c => WEATHER[c] || [c, "#605e5c"]), W = P.w.map(c => CODES.indexOf(c));
  const yr = i => +P.date[i].slice(0, 4), mo = i => +P.date[i].slice(5, 7) - 3, since = i => P.since[i];
  const MK = ["Before the first payment", "Payment month", "1 month after", "2 months after", "3 months after", "4 months after", "5 or more months after"], mkCol = i => since(i) == null ? 0 : Math.min(6, since(i) + 1);
  const DAYS = [];
  for (let i = 0; i < N; i++) if (P.arr[i] != null) DAYS.push(i);
  let grp = "time", year = "All", month = "All", run = null, nodes = [], G = {};
  const active = i => (year === "All" || yr(i) === year) && (month === "All" || mo(i) === month);
  // March to October in calendar days: the start of each month, and its length.
  const START = [0, 31, 61, 92, 122, 153, 184, 214], LENGTH = [31, 30, 31, 30, 31, 31, 30, 31];
  const AMAX = Math.max(1, ...DAYS.map(i => P.arr[i])) * 1.05, Y = lin(0, AMAX, 306, 26), SW = 1136 / Math.max(1, YEARS.length), DS = (SW - 15) / 245;
  const SX = k => 44 + k * SW, doy = i => START[mo(i)] + (+P.date[i].slice(8)) - 1, timeX = i => SX(YEARS.indexOf(yr(i))) + doy(i) * DS;
  const mean = a => a.length ? sum(a) / a.length : null;
  function layout() {
    const out = new Map(), act = DAYS.filter(active);
    if (grp === "time") { act.forEach(i => out.set(i, { x: timeX(i), y: Y(P.arr[i]) })); return { out, cols: null } }
    const key = grp === "weather" ? i => W[i] : mkCol, labels = grp === "weather" ? WX.map(w => w[0]) : MK, cw = 1136 / labels.length, cap = Math.max(1, Math.floor((cw - 22) / 4.2)), cols = labels.map((l, c) => ({ l, cx: 44 + cw * (c + .5), days: [] }));
    act.forEach(i => cols[key(i)].days.push(i));
    cols.forEach(c => { const by = {}; c.days.forEach(i => (by[P.arr[i]] = by[P.arr[i]] || []).push(i)); Object.values(by).forEach(list => list.forEach((i, k) => { const row = Math.floor(k / cap), inRow = Math.min(cap, list.length - row * cap); out.set(i, { x: c.cx + ((k % cap) - (inRow - 1) / 2) * 4.2, y: Y(P.arr[i]) - row * 4.2 }) })); c.mean = mean(c.days.map(i => P.arr[i])) });
    return { out, cols };
  }
  function setup() {
    const s = $("dots");
    G.back = S("g", {}, s); G.dots = S("g", {}, s); G.front = S("g", {}, s);
    DAYS.forEach(i => { nodes.push(S("circle", { r: 2, fill: WX[W[i]][1], "fill-opacity": .85, "data-i": i, cx: timeX(i), cy: Y(0) }, G.dots)) });
    const tipAt = e => { const i = e.target && e.target.getAttribute ? e.target.getAttribute("data-i") : null; if (i == null) { hideTip(); return } const sc = since(+i); showTip([dayLabel(P.date[i]), plural(P.arr[i], "arrival", "arrivals") + ", " + num(P.guests[i]) + " guests in the park", WX[W[i]][0] + ", " + P.temp[i] + " °C", sc == null ? "Before the first marketing payment" : sc === 0 ? "Marketing was paid for this month" : plural(sc, "month", "months") + " after a marketing payment"], e.clientX, e.clientY) };
    s.addEventListener("mousemove", tipAt); s.addEventListener("mouseleave", hideTip);
  }
  function frame(L) {
    const b = G.back, f = G.front;
    b.replaceChildren(); f.replaceChildren();
    niceTicks(0, AMAX).forEach(v => { S("line", { x1: 44, x2: 1180, y1: Y(v), y2: Y(v), stroke: "#edebe9" }, b); S("text", { x: 38, y: Y(v) + 4, "text-anchor": "end" }, b, v) });
    S("text", { x: 6, y: 14, style: "font-size:12px;fill:#252423" }, b, "↑ Arrivals in the day");
    WX.forEach((w, k) => { const x = 1180 - (WX.length - k) * 100; S("circle", { cx: x, cy: 10, r: 4, fill: w[1] }, b); S("text", { x: x + 9, y: 14 }, b, w[0]) });
    if (!L.cols) {
      S("rect", { x: 160, y: 5, width: 12, height: 10, fill: "#f2c811", opacity: .5 }, b); S("text", { x: 177, y: 14 }, b, "month with a marketing payment, and its cost");
      YEARS.forEach((y, k) => {
        S("text", { x: SX(k) + 122 * DS, y: 344, "text-anchor": "middle", style: "font-size:12px;fill:#252423;font-weight:600" }, b, y);
        for (let m = 0; m < SEASON; m++) {
          const x0 = SX(k) + START[m] * DS, w = LENGTH[m] * DS, st = M[MI(y, m + 3)];
          S("text", { x: x0 + w / 2, y: 324, "text-anchor": "middle", style: "font-size:10px" }, b, MONTHS[m][0]);
          if (st && st.mkt > 0) { S("rect", { x: x0, y: 22, width: w, height: 288, fill: "#f2c811", opacity: .28 }, b); S("text", { x: x0 + w / 2, y: 36, "text-anchor": "middle", style: "font-size:10.5px;fill:#252423;font-weight:600" }, f, tick$(st.mkt)) }
        }
      });
      return;
    }
    L.cols.forEach(c => {
      S("text", { x: c.cx, y: 326, "text-anchor": "middle", style: "font-size:12px;fill:#252423;font-weight:600" }, b, c.l); S("text", { x: c.cx, y: 341, "text-anchor": "middle" }, b, plural(c.days.length, "day", "days"));
      if (c.mean != null) { const w = 1136 / L.cols.length / 2 - 8; S("line", { x1: c.cx - w, x2: c.cx + w, y1: Y(c.mean), y2: Y(c.mean), stroke: "#252423", "stroke-width": 2 }, f); S("text", { x: c.cx + w, y: Y(c.mean) - 5, "text-anchor": "end", style: "paint-order:stroke;stroke:#fff;stroke-width:3px;font-size:12.5px;font-weight:700;fill:#252423" }, f, c.mean.toFixed(1) + " a day") }
    });
  }
  function go(ms) {
    const L = layout(), from = nodes.map(n => [+n.getAttribute("cx"), +n.getAttribute("cy"), +(n.getAttribute("opacity") || 1)]);
    if (run) run.stop();
    frame(L); G.front.setAttribute("opacity", 0);
    // dots leave in date order, so the eye can follow the seasons into their new groups
    run = tween(ms, (e, k) => { DAYS.forEach((i, j) => { const t = L.out.get(i), p = ease(clamp((k - j / DAYS.length * .35) / .65, 0, 1)), n = nodes[j]; if (t) { n.setAttribute("cx", lerp(from[j][0], t.x, p).toFixed(1)); n.setAttribute("cy", lerp(from[j][1], t.y, p).toFixed(1)) } n.setAttribute("opacity", lerp(from[j][2], t ? 1 : 0, p).toFixed(2)) }); G.front.setAttribute("opacity", clamp((k - .7) / .3, 0, 1)) });
    [...$("grp").querySelectorAll("button")].forEach(b => b.setAttribute("aria-pressed", String(b.dataset.g === grp)));
    text(L); matrix();
  }
  function text(L) {
    const act = DAYS.filter(active), m = f => mean(act.filter(f).map(i => P.arr[i])), f = v => v.toFixed(1);
    const hot = m(i => since(i) === 1 || since(i) === 2), cold = m(i => since(i) >= 4), sun = m(i => P.w[i] === "sunny"), rain = m(i => P.w[i] === "rain" || P.w[i] === "heavyRain");
    const scope = ((month === "All" ? "" : MFULL[month] + " ") + (year === "All" ? "" : year)).trim(), p = [];
    if (hot != null && cold != null && sun != null && rain != null) {
      const clear = hot >= 2 * cold && Math.abs(sun - rain) <= 1;
      if (clear) p.push("Arrivals follow ", ["marketing"], ", not ", ["weather"], scope ? " (" + scope + "). In" : ". In");
      else p.push(scope ? scope + ": in" : "In");
      p.push(" the two months after a marketing payment the park took ", { mark: f(hot) + " arrivals a day" }, "; four or more months after, ", [f(cold)], ". Sunny days averaged ", [f(sun)], " and rainy days ", [f(rain)], ".");
    } else p.push("In ", [scope || "the period"], " the park took ", { mark: f(mean(act.map(i => P.arr[i])) || 0) + " arrivals a day" }, " over ", [plural(act.length, "day", "days")], sun != null && rain != null ? "; sunny days averaged " + f(sun) + " and rainy days " + f(rain) + "." : ". Widen the period to compare weather and marketing.");
    say($("finding"), p);
    $("dotSub").textContent = plural(act.length, "day", "days") + " with an arrivals reading, " + (scope || (YEARS.length > 1 ? YEARS[0] + " to " + YEARS[YEARS.length - 1] : String(YEARS[0])));
    $("dotDesc").textContent = "Daily guest arrivals. " + (L.cols ? L.cols.filter(c => c.mean != null).map(c => c.l + ": " + c.mean.toFixed(1) + " a day over " + plural(c.days.length, "day", "days")).join("; ") : "Shown in date order with marketing payment months shaded") + ".";
  }

  // ---- availability matrix and the age curves
  const n = M.length, RS = RIDES.slice().sort((a, b) => a.open.findIndex(v => v != null) - b.open.findIndex(v => v != null));
  const cw = Math.min(17, (570 - YEARS.length * 8) / n), CX = i => 106 + i * cw + YEARS.indexOf(M[i].y) * 8;
  function matrix() {
    const s = $("matrix"), inSel = i => (year === "All" || M[i].y === year) && (month === "All" || M[i].m - 3 === month), ly = 17 + RS.length * 14.6 + 8;
    s.replaceChildren(); s.setAttribute("viewBox", "0 0 756 " + Math.max(244, ly + 20));
    YEARS.forEach(y => S("text", { x: CX(M.findIndex(r => r.y === y)) + cw * 4, y: 11, "text-anchor": "middle", style: "font-size:11px;fill:#252423;font-weight:600" }, s, y));
    S("text", { x: 756, y: 11, "text-anchor": "end" }, s, "longest queue");
    RS.forEach((r, j) => {
      const y = 17 + j * 14.6;
      S("text", { x: 100, y: y + 10, "text-anchor": "end", style: "font-size:11px;fill:#252423" }, s, r.short);
      for (let i = 0; i < n; i++) {
        if (r.open[i] == null) continue;
        const a = r.avail[i], closed = !r.open[i] || a == null, t = closed ? 0 : clamp((100 - a) / 10, 0, 1);
        const c = S("rect", { x: CX(i), y, width: cw * .91, height: 12.6, fill: closed ? "#fff" : t < .03 ? "#d6ebff" : "#e66c37", "fill-opacity": closed || t < .03 ? 1 : .22 + .78 * t, stroke: closed ? "#c8c6c4" : "none", opacity: inSel(i) ? 1 : .3, tabindex: -1 }, s);
        bindTip(c, [r.name, lab(i) + (closed ? ": closed all month" : ": available " + a.toFixed(0) + "% of the time"), closed ? "" : "Longest queue seen " + (r.q[i] == null ? "not read" : r.q[i] + " min") + ", ride age " + r.age[i] + " months"]);
      }
      const qs = r.q.filter((v, i) => v != null && inSel(i) && r.open[i]), q = qs.length ? Math.max(...qs) : null;
      if (q != null) { S("rect", { x: 684, y: y + 2, width: q * 4, height: 8.6, fill: "#118dff" }, s); S("text", { x: 688 + q * 4, y: y + 10, style: "font-size:11px;fill:#252423" }, s, q + " min") }
    });
    [["100%", "#d6ebff", 1], ["97%", "#e66c37", .45], ["94%", "#e66c37", .69], ["90% or less", "#e66c37", 1]].forEach(([l, c, o], k) => { S("rect", { x: 106 + k * 86, y: ly, width: 15.5, height: 12, fill: c, "fill-opacity": o }, s); S("text", { x: 126 + k * 86, y: ly + 10 }, s, l) });
    S("rect", { x: 470, y: ly, width: 15.5, height: 12, fill: "#fff", stroke: "#c8c6c4" }, s); S("text", { x: 490, y: ly + 10 }, s, "closed all month");
  }
  function ageChart() {
    const s = $("age"), A = SCOPE.by_age;
    if (!A.length) { S("text", { x: 0, y: 24, style: "font-size:13px" }, s, "No ride has had an open day yet."); return }
    const oldest = A[A.length - 1], x = lin(0, Math.max(1, oldest.age), 40, 384);
    const panel = (y0, h, title, key, lo, hi, fmt, col) => {
      const y = lin(lo, hi, y0 + h, y0), pts = A.filter(d => d[key] != null);
      S("text", { x: 0, y: y0 - 8, style: "font-size:12px;fill:#252423;font-weight:600" }, s, title);
      [lo, (lo + hi) / 2, hi].forEach(v => { S("line", { x1: 40, x2: 384, y1: y(v), y2: y(v), stroke: "#edebe9" }, s); S("text", { x: 34, y: y(v) + 4, "text-anchor": "end" }, s, fmt(v)) });
      if (!pts.length) return;
      S("path", { d: pts.map((d, k) => (k ? "L" : "M") + x(d.age).toFixed(1) + " " + y(d[key]).toFixed(1)).join(""), fill: "none", stroke: col, "stroke-width": 2.5, "stroke-linejoin": "round" }, s);
      pts.forEach(d => { const c = S("circle", { cx: x(d.age), cy: y(d[key]), r: 5, fill: col, opacity: 0, tabindex: -1 }, s); bindTip(c, ["Rides aged " + plural(d.age, "month", "months"), d.riders.toFixed(1) + " riders per open day", d.avail == null ? "" : d.avail.toFixed(1) + "% available", plural(d.n, "ride-day", "ride-days")]) });
      const best = pts.reduce((a, b) => b[key] > a[key] ? b : a), last = pts[pts.length - 1];
      S("circle", { cx: x(best.age), cy: y(best[key]), r: 3.5, fill: col }, s);
      if (key !== "avail") S("text", { x: x(best.age) + 7, y: y(best[key]) - 4, style: "font-size:11.5px;font-weight:700;fill:#252423" }, s, fmt(best[key]) + " at " + plural(best.age, "month", "months"));
      S("circle", { cx: x(last.age), cy: y(last[key]), r: 3.5, fill: col }, s); S("text", { x: x(last.age), y: y(last[key]) - 8, "text-anchor": "end", style: "font-size:11.5px;font-weight:700;fill:#252423" }, s, fmt(last[key]) + " at " + last.age);
    };
    const avails = A.filter(d => d.avail != null).map(d => d.avail), alo = Math.min(99, Math.floor(Math.min(100, ...avails)));
    panel(22, 82, "Riders per open day", "riders", 0, niceMax(Math.max(1, ...A.map(d => d.riders))), v => v.toFixed(v % 1 ? 1 : 0), "#12239e");
    panel(142, 72, "Available, % of the time", "avail", alo, 100, v => v.toFixed(v % 1 ? 1 : 0) + "%", "#e66c37");
    niceTicks(0, Math.max(1, oldest.age)).forEach(v => S("text", { x: x(v), y: 228, "text-anchor": "middle" }, s, v));
    S("text", { x: 384, y: 242, "text-anchor": "end", style: "font-size:12px;fill:#252423" }, s, "Ride age in months →");
    const peak = A.reduce((a, b) => b.riders > a.riders ? b : a);
    $("ageDesc").textContent = "By ride age in months: riders per open day peak at " + peak.riders.toFixed(1) + " at " + plural(peak.age, "month", "months") + " and stand at " + oldest.riders.toFixed(1) + " at " + plural(oldest.age, "month", "months") + (oldest.avail == null ? "." : "; availability stands at " + oldest.avail.toFixed(1) + "% at " + plural(oldest.age, "month", "months") + ".");
  }
  function slicers() { chips("yrs", [["All", "All"], ...YEARS.map(v => [String(v), v])], year, v => { year = v; slicers(); go(700) }); chips("mos", [["All", "All"], ...MONTHS.map((m, k) => [m, k])], month, v => { month = v; slicers(); go(700) }) }
  $("grp").addEventListener("click", e => { const b = e.target.closest("button"); if (b) { grp = b.dataset.g; go(1100) } });
  setup(); ageChart(); slicers(); go(900);
  // Opening beat: the timeline regroups by months since marketing, the finding of this page.
  if (!REDUCED) setTimeout(() => { grp = "mkt"; go(1400) }, 1900); else { grp = "mkt"; go(0) }
})();
