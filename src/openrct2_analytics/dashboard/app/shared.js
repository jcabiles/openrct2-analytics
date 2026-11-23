// Shared by the five pages: drawing helpers, number formats, the report shell (park slicer, page
// tabs, sample note) and access to window.DASHBOARD, which the server writes to data.js per build.
"use strict";
const $ = id => document.getElementById(id), NS = "http://www.w3.org/2000/svg";
function mk(e, a, p, t) { for (const k in a) if (a[k] != null) e.setAttribute(k, a[k]); if (t != null) e.textContent = t; if (p) p.appendChild(e); return e }
const S = (tag, a, p, t) => mk(document.createElementNS(NS, tag), a, p, t), H = (tag, a, p, t) => mk(document.createElement(tag), a, p, t);
const set = (e, a) => { for (const k in a) e.setAttribute(k, a[k]); return e };
// A company year is the game's season, March to October; position i of a year is MONTHS[i].
const SEASON = 8, MONTHS = ["Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct"], MFULL = ["March", "April", "May", "June", "July", "August", "September", "October"];
const MN = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const usd = v => (v < 0 ? "−$" : "$") + Math.abs(Math.round(v)).toLocaleString("en-US");
const usdK = v => (v < 0 ? "−$" : "$") + (Math.abs(v) / 1000).toFixed(1) + "K";
const usd2 = v => (v < 0 ? "−$" : "$") + Math.abs(v).toFixed(2);
const plus = (v, f) => (v >= 0 ? "+" : "") + (f || usd)(v);
const num = v => Math.round(v).toLocaleString("en-US");
const tick$ = v => v === 0 ? "$0" : Math.abs(v) >= 1000 ? (v < 0 ? "−$" : "$") + +(Math.abs(v) / 1000).toFixed(1) + "K" : usd(v);
const lin = (d0, d1, r0, r1) => v => r0 + (v - d0) / ((d1 - d0) || 1) * (r1 - r0), lerp = (a, b, t) => a + (b - a) * t, clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const sum = a => a.reduce((s, v) => s + (v || 0), 0);
const plural = (n, one, many) => n + " " + (n === 1 ? one : many);
const REDUCED = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const ease = t => 1 - Math.pow(1 - t, 3);
// Round steps for an axis from lo to hi: about five ticks at 1, 2, 2.5 or 5 times a power of ten.
function niceStep(lo, hi) { const raw = Math.max(hi - lo, 1e-9) / 5, p = Math.pow(10, Math.floor(Math.log10(raw))); return [1, 2, 2.5, 5, 10].map(m => m * p).find(v => v >= raw) }
function niceTicks(lo, hi) { const st = niceStep(lo, hi), out = []; for (let v = Math.ceil(lo / st) * st; v <= hi + st * 1e-9; v += st) out.push(+v.toFixed(6)); return out }
const niceMax = (hi, lo) => { const st = niceStep(lo || 0, hi); return Math.max(st, Math.ceil(hi / st) * st) };
// One tween helper for every animation; with reduced motion it jumps to the end state.
function tween(ms, fn, done) { if (REDUCED || ms <= 0) { fn(1, 1); if (done) done(); return { stop() { } } } let t0 = null, off = false; function f(t) { if (off) return; if (t0 == null) t0 = t; const k = Math.min(1, (t - t0) / ms); fn(ease(k), k); if (k < 1) requestAnimationFrame(f); else if (done) done() } requestAnimationFrame(f); return { stop() { off = true } } }
// Sentence builder: strings are plain, [text] is bold, {mark:text} is the highlighted figure, DOM nodes pass through.
function say(el, parts) { el.replaceChildren(); for (const p of parts) { if (typeof p === "string") el.append(p); else if (Array.isArray(p)) H("b", {}, el, p[0]); else if (p && p.mark != null) H("mark", {}, el, p.mark); else if (p) el.appendChild(p) } }
const tipEl = H("div", { class: "tip", role: "status", hidden: "" }, document.body);
function showTip(lines, x, y) { tipEl.replaceChildren(); lines.filter(l => l).forEach((l, i) => H(i ? "span" : "b", {}, tipEl, l)); tipEl.hidden = false; const w = tipEl.offsetWidth || 200, h = tipEl.offsetHeight || 60; tipEl.style.left = clamp(x + 14, 4, window.innerWidth - w - 4) + "px"; tipEl.style.top = clamp(y + 14, 4, window.innerHeight - h - 4) + "px" }
function hideTip() { tipEl.hidden = true }
function bindTip(el, lines) { const get = () => typeof lines === "function" ? lines() : lines, at = e => showTip(get(), e.clientX, e.clientY); el.addEventListener("mouseenter", at); el.addEventListener("mousemove", at); el.addEventListener("mouseleave", hideTip); el.addEventListener("focus", () => { const r = el.getBoundingClientRect(); showTip(get(), r.left + r.width / 2, r.top + r.height / 2) }); el.addEventListener("blur", hideTip) }
// Chips are rebuilt on every state change; keyboard focus is handed to the pressed chip so it is never lost.
function chips(id, items, cur, pick) { const c = $(id), had = c.contains(document.activeElement); c.replaceChildren(); items.forEach(([label, val]) => { const b = H("button", { type: "button", "aria-pressed": String(val === cur) }, c, label); b.addEventListener("click", () => pick(val)); if (had && val === cur) b.focus() }) }
// Pointer position inside an SVG, in viewBox units.
function svgX(svg, e) { const r = svg.getBoundingClientRect(), vb = svg.getAttribute("viewBox").split(" ").map(Number); return { x: vb[0] + (e.clientX - r.left) / r.width * vb[2], y: vb[1] + (e.clientY - r.top) / r.height * vb[3] } }
function act(el, fn) { el.addEventListener("click", fn); el.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fn(e) } }) }
// Drag across an SVG: fn receives each pointer event while the button is held.
function onDrag(svg, fn) { let on = false; svg.addEventListener("pointerdown", e => { on = true; svg.setPointerCapture(e.pointerId); fn(e) }); svg.addEventListener("pointermove", e => { if (on) fn(e) }); svg.addEventListener("pointerup", () => on = false); svg.addEventListener("pointercancel", () => on = false) }

// ---- data: one scope of window.DASHBOARD, chosen by the address only. A park ID counts only when it
// is the id of a real park with a scope of its own (a lone company park has none); anything else (a missing value, "all", a scope name) is the all-parks view,
// where ?sandbox=shown picks the scope that includes the Sandbox parks and anything else leaves them out.
const DATA = window.DASHBOARD, QUERY = new URLSearchParams(window.location.search), ASKED = QUERY.get("park");
const PARK = DATA.parks.some(p => p.id === ASKED) && DATA.scopes[ASKED] ? ASKED : "all";
const INCLUDED = PARK === "all" && QUERY.get("sandbox") === "shown" && !!DATA.scopes.with_sandbox;
const SCOPE = PARK !== "all" ? DATA.scopes[PARK] : INCLUDED ? DATA.scopes.with_sandbox : DATA.scopes.all, M = SCOPE.months, RIDES = SCOPE.rides;
const YEARS = [...new Set(M.map(r => r.y))];
const MINDEX = new Map(M.map((r, i) => [r.y * 100 + r.m, i]));
const MI = (y, m) => MINDEX.has(y * 100 + m) ? MINDEX.get(y * 100 + m) : -1;
const lab = i => MONTHS[M[i].m - 3] + " " + M[i].y, labF = i => MFULL[M[i].m - 3] + " " + M[i].y;
const dayLabel = d => +d.slice(8) + " " + MN[+d.slice(5, 7) - 1] + " " + d.slice(0, 4);
// Income and cost lines of the monthly statement; entrance fees appear only when a park charged them.
const LINES = [["Ride income", "rides", 1, "Ride", "income"], ["Entrance fees", "entrance", 1, "Entrance", "fees"], ["Food and drink", "food", 1, "Food and", "drink"], ["Merchandise", "merch", 1, "Merchan-", "dise"], ["Staff wages", "staff", -1, "Staff", "wages"], ["Marketing", "mkt", -1, "Marketing", ""], ["Stock", "stock", -1, "Stock", ""], ["Ride running", "running", -1, "Ride", "running"], ["Research", "research", -1, "Research", ""]].filter(l => l[1] !== "entrance" || M.some(r => r.entrance));
const FAM = { Coaster: "#12239e", Thrill: "#e66c37", Gentle: "#6b007b", Water: "#118dff", Other: "#605e5c" };
const FAMS = { Coaster: ["coaster", "coasters"], Thrill: ["thrill ride", "thrill rides"], Gentle: ["gentle ride", "gentle rides"], Water: ["water ride", "water rides"], Other: ["other ride", "other rides"] };
const exists = (r, i) => i >= 0 && r.n[i] != null, earning = (r, i) => i >= 0 && r.riders[i] > 0 && r.profit[i] > 0;
const SAMPLE = "Sample: " + plural(SCOPE.parks, "park", "parks") + ", one player, " + num(SCOPE.days.date.length) + " game days. Observational.";

// ---- the report shell
const PAGES = [["executive.html", "Executive"], ["finance.html", "Finance"], ["attractions.html", "Attractions"], ["pricing.html", "Pricing"], ["operations.html", "Operations"]];
// The address of a view: a park view carries only its park, the all-parks view carries sandbox=shown when included.
const viewQuery = (park, included) => park !== "all" ? "?park=" + encodeURIComponent(park) : included ? "?sandbox=shown" : "";
function shell() {
  const here = window.location.pathname.split("/").pop() || "executive.html", query = viewQuery(PARK, INCLUDED);
  const tabs = document.querySelector(".tabs");
  PAGES.forEach(([file, name]) => { const a = H("a", { href: file + query }, tabs, name); if (file === here || (here === "index.html" && file === PAGES[0][0])) a.setAttribute("aria-current", "page") });
  if (DATA.as_of) $("asof").textContent = "Figures as of " + DATA.as_of;
  const box = $("parkBox");
  H("h2", { id: "lp" }, box, "Park");
  const sel = H("select", { "aria-labelledby": "lp" }, box);
  const sandboxParks = DATA.parks.filter(p => p.sandbox);
  const options = DATA.parks.length > 1 || sandboxParks.length ? [["all", "All parks"], ...DATA.parks.map(p => [p.id, p.name])] : DATA.parks.map(p => ["all", p.name]);
  options.forEach(([id, name]) => { const o = H("option", { value: id }, sel, name); if (id === PARK) o.setAttribute("selected", "") });
  sel.addEventListener("change", () => { window.location.search = viewQuery(sel.value, INCLUDED) });
  if (PARK === "all" && sandboxParks.length) {
    H("h2", {}, box, "Sandbox parks");
    H("div", { class: "chips", id: "sandboxChips", role: "group", "aria-label": "Sandbox parks" }, box);
    chips("sandboxChips", [["Left out", false], ["Included", true]], INCLUDED, v => { window.location.search = viewQuery("all", v) });
    H("p", { class: "note", id: "sandboxNote", style: "white-space:pre-line" }, box, (INCLUDED ? "The All parks figures include these Sandbox parks:" : "The All parks figures leave out these Sandbox parks:") + sandboxParks.map(p => "\n" + window.DASHBOARD_LABELS[p.id]).join(""));
  }
  document.querySelectorAll(".sample").forEach(el => { el.textContent = SAMPLE });
  if (!M.length && PARK === "all" && !INCLUDED && sandboxParks.length) say(document.querySelector(".finding p"), ["No company park has a closed month yet. Sandbox parks are left out of All parks; choose Included under Sandbox parks to see them."]);
  else if (!M.length) say(document.querySelector(".finding p"), ["No monthly statement is in the working copy yet. The pages fill in once the first game month closes and ", ["make after-play DATA_SET=company"], " has run."]);
  return M.length > 0;
}
const READY = shell();
