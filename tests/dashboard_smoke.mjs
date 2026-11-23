// Smoke check of the dashboard pages: run each page's scripts against a data.js in a minimal stand-in
// for the browser's DOM, step its timers and animations, click every button and move every slider,
// and fail on any thrown error. It is not a browser: layout, CSS and drawing are not checked.
// Usage: node tests/dashboard_smoke.mjs <app folder> <data.js> [--reduced] [--park=<id>] [--sandbox]
//   [--labels=<json file>] [--follow]
// The executive page also gets `executive`: for each company year chip, the page's charts and, after
// each month chip, its key figures and sentences, sparklines and highlighted bar, and the month the slider
// lands on after a one-month step from each month chip (see executiveReadings); and `year_switch`: the
// month, key figures and chart cursor after the last year's March chip and then the first year chip,
// with no month chip clicked in between (see yearSwitch).
// Prints one JSON object: for each page, the finding sentence after loading and the page's text, and
// the company-year note (#gameYears) as opened, after the first year chip, and after the last year chip
// then the March chip; also the switch note (sandbox_note) and its pressed chip (sandbox_pressed), the
// first sample line, the tab links and the picker entries as loaded, and, on Finance, whether the
// "Same month a year earlier" button is disabled (yoy_disabled; null elsewhere). --sandbox adds sandbox=shown to the
// address; --labels sets window.DASHBOARD_LABELS from a JSON object before data.js runs. Without --follow
// a page that assigns location.search or whose tab link is clicked changes nothing else. With --follow
// each page also gets `hops`, at most five fresh loads of the address the page was sent to by this walk:
// the Included chip, the next tab link, the Left out chip, the picker on the last park, the picker on
// All parks; the walk ends at the first step whose control is missing.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import vm from "node:vm";

const PAGES = ["executive", "finance", "attractions", "pricing", "operations"];
const VOID = new Set(["meta", "link", "input", "br", "col", "img"]);
const clock = { t: 0, frames: [], timers: [], id: 1 };

class Node {
  constructor(tag, doc) {
    Object.assign(this, { tagName: tag, ownerDocument: doc, attrs: new Map(), childNodes: [], parentNode: null, listeners: {}, text: "", props: {}, style: {} });
  }
  get nodeType() { return this.tagName === "#text" ? 3 : 1 }
  get children() { return this.childNodes.filter(c => c.nodeType === 1) }
  get firstChild() { return this.childNodes[0] || null }
  get id() { return this.attrs.get("id") || "" }
  get className() { return this.attrs.get("class") || "" }
  set className(v) { this.attrs.set("class", String(v)) }
  get classList() {
    const get = () => this.className.split(/\s+/).filter(Boolean), put = a => this.attrs.set("class", a.join(" "));
    return { contains: c => get().includes(c), add: c => put([...new Set([...get(), c])]), remove: c => put(get().filter(x => x !== c)), toggle: (c, on) => { const want = on === undefined ? !get().includes(c) : !!on; put(want ? [...new Set([...get(), c])] : get().filter(x => x !== c)); return want } };
  }
  get dataset() { return new Proxy({}, { get: (_, k) => this.attrs.get("data-" + String(k)) }) }
  setAttribute(k, v) { this.attrs.set(k, String(v)) }
  getAttribute(k) { return this.attrs.has(k) ? this.attrs.get(k) : null }
  removeAttribute(k) { this.attrs.delete(k) }
  hasAttribute(k) { return this.attrs.has(k) }
  appendChild(c) { c.remove(); c.parentNode = this; this.childNodes.push(c); return c }
  append(...items) { for (const c of items) this.appendChild(typeof c === "string" ? this.ownerDocument.createTextNode(c) : c) }
  replaceChildren(...items) { for (const c of this.childNodes) c.parentNode = null; this.childNodes = []; this.append(...items) }
  remove() { if (this.parentNode) { const list = this.parentNode.childNodes; list.splice(list.indexOf(this), 1); this.parentNode = null } }
  get textContent() { return this.nodeType === 3 ? this.text : this.childNodes.map(c => c.textContent).join("") }
  set textContent(v) { if (this.nodeType === 3) this.text = String(v); else { this.replaceChildren(); if (v !== "" && v != null) this.append(String(v)) } }
  contains(o) { for (let n = o; n; n = n.parentNode) if (n === this) return true; return false }
  matches(sel) { return sel.split(",").some(s => matchChain(this, s.trim().split(/\s+/))) }
  closest(sel) { for (let n = this; n && n.nodeType === 1; n = n.parentNode) if (n.tagName !== "#document" && n.matches(sel)) return n; return null }
  querySelectorAll(sel) { const out = [], walk = n => { for (const c of n.children) { if (c.matches(sel)) out.push(c); walk(c) } }; walk(this); return out }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn) }
  dispatchEvent(ev) {
    ev.target ||= this; ev.preventDefault = () => { }; ev.stopPropagation = () => { };
    for (let n = this; n; n = n.parentNode) { for (const fn of n.listeners[ev.type] || []) fn.call(n, ev); if (!ev.bubbles) break }
  }
  click() {
    this.dispatchEvent({ type: "click", bubbles: true, clientX: 10, clientY: 10, shiftKey: false });
    const win = this.ownerDocument.window;
    if (this.tagName === "a" && this.closest(".tabs") && win) { const [file, query = ""] = this.getAttribute("href").split("?"); win.sent = { file, query: query && "?" + query } }
  }
  focus() { this.ownerDocument.activeElement = this; this.dispatchEvent({ type: "focus" }) }
  getBoundingClientRect() { return { left: 0, top: 0, width: 1000, height: 400 } }
  get offsetWidth() { return 200 }
  get offsetHeight() { return 40 }
  setPointerCapture() { }
}
for (const prop of ["value", "max", "hidden"]) {
  Object.defineProperty(Node.prototype, prop, {
    get() { return prop in this.props ? this.props[prop] : prop === "hidden" ? this.attrs.has("hidden") : this.attrs.get(prop) ?? "" },
    set(v) { this.props[prop] = v },
  });
}
function matchSimple(node, sel) {
  if (node.nodeType !== 1) return false;
  const parts = sel.match(/[#.][\w-]+|\[[^\]]+\]|^[\w-]+/g) || [];
  return parts.every(p => {
    if (p[0] === "#") return node.id === p.slice(1);
    if (p[0] === ".") return node.classList.contains(p.slice(1));
    if (p[0] === "[") { const [, k, v] = p.match(/^\[([\w-]+)(?:=["']?([^"'\]]*)["']?)?\]$/); return v === undefined ? node.attrs.has(k) : node.attrs.get(k) === v }
    return node.tagName === p;
  });
}
function matchChain(node, parts) {
  if (!matchSimple(node, parts[parts.length - 1])) return false;
  let i = parts.length - 2;
  for (let n = node.parentNode; i >= 0 && n; n = n.parentNode) if (matchSimple(n, parts[i])) i--;
  return i < 0;
}
function parse(html, doc) {
  const re = /<!--[\s\S]*?-->|<!doctype[^>]*>|<\/([\w-]+)\s*>|<([\w-]+)((?:\s+[\w:-]+(?:="[^"]*")?)*)\s*\/?>|([^<]+)/gi;
  let cur = doc, m;
  while ((m = re.exec(html))) {
    if (m[1]) cur = cur.parentNode || doc;
    else if (m[2]) {
      const node = new Node(m[2].toLowerCase(), doc);
      for (const a of m[3].matchAll(/([\w:-]+)(?:="([^"]*)")?/g)) node.attrs.set(a[1], (a[2] ?? "").replace(/&amp;/g, "&"));
      cur.appendChild(node);
      if (node.tagName === "script") { const end = html.indexOf("</script>", re.lastIndex); re.lastIndex = end + 9 }
      else if (!VOID.has(node.tagName)) cur = node;
    } else if (m[4] && m[4].trim()) cur.append(m[4]);
  }
}
function makeWindow(html, reduced, location) {
  const doc = new Node("#document", null);
  doc.ownerDocument = doc;
  Object.assign(doc, {
    createElement: t => new Node(t, doc), createElementNS: (_, t) => new Node(t, doc),
    createTextNode: s => { const t = new Node("#text", doc); t.text = String(s); return t },
    getElementById: id => doc.querySelector("#" + id),
  });
  parse(html, doc);
  doc.body = doc.querySelector("body");
  doc.activeElement = doc.body;
  const win = {
    document: doc, innerWidth: 1440, innerHeight: 900, console, URLSearchParams,
    location,
    matchMedia: q => ({ matches: /reduced-motion/.test(q) ? reduced : false }),
    requestAnimationFrame: f => { clock.frames.push(f); return clock.id++ },
    setTimeout: (f, ms = 0) => { const id = clock.id++; clock.timers.push({ id, at: clock.t + ms, f }); return id },
    clearTimeout: id => { clock.timers = clock.timers.filter(t => t.id !== id) },
  };
  win.window = win;
  doc.window = win;
  return win;
}
function advance(ms) {
  for (const end = clock.t + ms; clock.t < end;) {
    clock.t += 16;
    const due = clock.timers.filter(t => t.at <= clock.t);
    clock.timers = clock.timers.filter(t => t.at > clock.t);
    due.forEach(t => t.f());
    const frames = clock.frames;
    clock.frames = [];
    frames.forEach(f => f(clock.t));
  }
}
// One page loaded at `search`, run until its timers settle. `sent` holds the address the page sent
// itself to (an assigned location.search or a clicked tab link), as { file, query }.
function load(app, dataFile, page, o, search) {
  Object.assign(clock, { t: 0, frames: [], timers: [] });
  let win;
  const location = { pathname: "/" + page + ".html", get search() { return search }, set search(v) { search = v; win.sent = { file: page + ".html", query: v } } };
  win = makeWindow(readFileSync(join(app, page + ".html"), "utf8"), o.reduced, location);
  win.sent = null;
  if (o.labels) win.DASHBOARD_LABELS = o.labels;
  const context = vm.createContext(win);
  for (const [name, file] of [["data.js", dataFile], ["shared.js", join(app, "shared.js")], [page + ".js", join(app, page + ".js")]]) {
    vm.runInContext(readFileSync(file, "utf8"), context, { filename: name });
  }
  advance(8000);
  return { win, context, doc: win.document, page };
}
// What the shared shell shows: the switch, the sample line, the tab links and the picker.
function shellReadings({ win, doc, page }) {
  const pressed = [...(doc.getElementById("sandboxChips")?.querySelectorAll("button") || [])].find(b => b.getAttribute("aria-pressed") === "true");
  return {
    page, search: win.location.search,
    sandbox_note: (doc.getElementById("sandboxNote") || {}).textContent || "",
    sandbox_pressed: pressed ? pressed.textContent : null,
    sample: (doc.querySelector(".sample") || {}).textContent || "",
    tabs: doc.querySelectorAll(".tabs a").map(a => a.getAttribute("href")),
    picker: doc.querySelectorAll("#parkBox option").map(o => o.textContent),
    yoy_disabled: page === "finance" ? doc.querySelector('#mode [data-m="yoy"]').hasAttribute("disabled") : null,
  };
}
// Five fresh loads, each from the control the previous load shows; the walk ends when a control is missing.
function follow(app, dataFile, page, o, search) {
  const hops = [], press = (v, label) => { const b = v.doc.getElementById("sandboxChips")?.querySelectorAll("button").find(x => x.textContent === label); if (b) b.click(); return b };
  const pick = (v, last) => {
    const sel = v.doc.querySelector("#parkBox select"), opts = sel ? v.doc.querySelectorAll("#parkBox option") : [];
    if (!opts.length) return false;
    sel.value = last ? opts[opts.length - 1].attrs.get("value") : "all";
    sel.dispatchEvent({ type: "change", bubbles: true });
    return true;
  };
  const steps = [
    v => press(v, "Included"),
    v => { const a = v.doc.querySelectorAll(".tabs a").find(x => x.getAttribute("aria-current") !== "page"); if (a) a.click(); return a },
    v => press(v, "Left out"),
    v => pick(v, true),
    v => pick(v, false),
  ];
  let view = load(app, dataFile, page, o, search);
  for (const step of steps) {
    const { win } = view;
    if (!step(view) || !win.sent) break;
    view = load(app, dataFile, win.sent.file.replace(/\.html$/, ""), o, win.sent.query);
    hops.push(shellReadings(view));
  }
  return hops;
}
// The Executive page by company year, read through its own controls. Per year: the race chart's month
// labels, bar values and prior-year bars as [x, text] pairs (a month's label and bars share one x), the
// year chart's labels, the race description; then per month chip, the page's figures and sentences.
function executiveReadings(doc) {
  const text = id => (doc.getElementById(id) || {}).textContent || "";
  const buttons = id => doc.getElementById(id).querySelectorAll("button");
  const style = n => n.getAttribute("style") || "";
  const out = {};
  for (let yi = 0; yi < buttons("yrs").length; yi++) {
    const year = buttons("yrs")[yi].textContent;
    buttons("yrs")[yi].click(); advance(1500);
    const race = doc.getElementById("race");
    const entry = {
      executive_months: buttons("mos").map(b => b.textContent),
      race_months: race.querySelectorAll("text").filter(t => t.getAttribute("y") === "280").map(t => [+t.getAttribute("x"), t.textContent]),
      race_values: race.querySelectorAll("text").filter(t => /font-weight:600/.test(style(t))).map(t => [+t.getAttribute("x"), t.textContent]),
      race_prior_x: race.querySelectorAll("rect").filter(r => r.getAttribute("fill") === "#118dff" && r.getAttribute("width") === "21").map(r => +r.getAttribute("x")),
      year_labels: doc.getElementById("years").querySelectorAll("g").map(g => g.getAttribute("aria-label")),
      race_desc: text("raceDesc"), race_sub: text("raceSub"), months: [],
    };
    for (let mi = 0; mi < buttons("mos").length; mi++) {
      buttons("mos")[mi].click(); advance(1500);
      const tiles = doc.getElementById("kpis").querySelectorAll(".kpi");
      entry.months.push({
        chip: buttons("mos")[mi].textContent, through: text("thruOut"), finding: text("finding"), lead_title: text("leadTitle"), event: text("event"),
        kpi_labels: tiles.slice(0, 3).map(t => t.querySelector(".l").textContent), cash_label: tiles[3].querySelector(".l").textContent, kpi_values: tiles.map(t => t.querySelector(".n").textContent), kpi_deltas: tiles.map(t => t.querySelector(".d").textContent),
        lead_rows: doc.getElementById("lead").querySelectorAll("text").map(t => t.textContent),
        // each tile's sparkline bars as [x, fill]; the race value labels shown at full opacity (the highlighted month)
        sparks: tiles.map(t => t.querySelectorAll("rect").map(r => [+r.getAttribute("x"), r.getAttribute("fill")])),
        race_lit_x: race.querySelectorAll("text").filter(t => /font-weight:600/.test(style(t)) && t.getAttribute("opacity") === "1").map(t => +t.getAttribute("x")),
      });
    }
    // A keyboard step on the month slider from each month chip: where the page lands, as the month it names.
    entry.slider_steps = [];
    for (let mi = 0; mi < buttons("mos").length; mi++) {
      for (const delta of [1, -1]) {
        buttons("mos")[mi].click(); advance(1500);
        const from = text("thruOut"), thru = doc.getElementById("thru");
        thru.value = +thru.value + delta; thru.dispatchEvent({ type: "input", bubbles: true, target: thru }); advance(1500);
        entry.slider_steps.push({ from, delta, lands: text("thruOut") });
      }
    }
    out[year] = entry;
  }
  return out;
}
// Pick March in the last year, let it settle, then pick the first year without clicking a month chip: the
// month the controls show, the key figures and the chart cursor's x. Null when the page has no such chips.
function yearSwitch(doc) {
  const buttons = id => doc.getElementById(id).querySelectorAll("button"), click = b => { b.click(); advance(1500) };
  const march = buttons("mos").find(b => b.textContent === "Mar"), years = buttons("yrs");
  if (!march || !years.length) return null;
  click(years[years.length - 1]);
  click(buttons("mos").find(b => b.textContent === "Mar"));
  click(buttons("yrs")[0]);
  const cursor = doc.getElementById("race").querySelectorAll("line").find(l => l.getAttribute("stroke-dasharray") === "3 3");
  return { through: doc.getElementById("thruOut").textContent, kpi_values: doc.getElementById("kpis").querySelectorAll(".kpi").map(t => t.querySelector(".n").textContent), cursor_x: +cursor.getAttribute("x1") };
}
function run(app, dataFile, page, o) {
  const { win, context, doc } = load(app, dataFile, page, o, o.search);
  const finding = () => (doc.getElementById("finding") || {}).textContent || "";
  const opened = finding(), note = () => (doc.getElementById("gameYears") || {}).textContent || "";
  const opened_note = note(), shell = shellReadings({ win, doc, page });
  // Year and month clicks (on a page that has those chips) come first, so the note is read after each change; `text` and `finding` keep their values.
  const chip = (box, n) => { const el = doc.getElementById(box); if (!el) return; const b = el.querySelectorAll("button"); (n < 0 ? b[b.length + n] : b[n])?.click(); advance(1500) };
  chip("yrs", 0);
  const year_note = note();
  chip("yrs", -1);
  chip("mos", 1);
  const month_note = note();
  // Every control once: each button (looked up again after each click, since pages rebuild them),
  // then each slider at its two ends.
  for (let i = 0; ; i++) {
    const button = doc.querySelectorAll("button")[i];
    if (!button) break;
    button.click();
    advance(1500);
  }
  for (const input of doc.querySelectorAll("input")) {
    for (const value of [input.attrs.get("min"), input.max || input.attrs.get("max")]) { input.value = value; input.dispatchEvent({ type: "input", bubbles: true, target: input }); advance(1500) }
  }
  // What the page itself sees for reduced motion, read inside its own context.
  const reduced_motion = vm.runInContext("window.matchMedia('(prefers-reduced-motion: reduce)').matches", context);
  const result = { finding: opened, text: doc.querySelector(".report").textContent, opened_note, year_note, month_note, reduced_motion, ...shell };
  if (page === "executive") { result.year_switch = yearSwitch(doc); result.executive = executiveReadings(doc) }
  if (o.follow) result.hops = follow(app, dataFile, page, o, o.search);
  return result;
}
const args = process.argv.slice(2), [app, dataFile] = args.filter(a => !a.startsWith("--"));
const park = (args.find(a => a.startsWith("--park=")) || "").slice(7), labelsFile = (args.find(a => a.startsWith("--labels=")) || "").slice(9);
const query = [park && "park=" + park, args.includes("--sandbox") && "sandbox=shown"].filter(Boolean).join("&");
const options = { reduced: args.includes("--reduced"), follow: args.includes("--follow"), search: query && "?" + query, labels: labelsFile && JSON.parse(readFileSync(labelsFile, "utf8")) };
const out = {};
for (const page of PAGES) out[page] = run(app, dataFile, page, options);
console.log(JSON.stringify(out));
