// The insights desk: department tabs, the season range with its presets, and the park switch.
// The state lives in `desk` (data.mjs); a view reads it and listens with `onDeskChange`. With no
// month rows the controls are absent from the page and nothing is wired (R15).
import { $, $$, svg, clear } from "./dom.mjs";
import { desk, parkMonthData } from "./data.mjs";
import { deskMonths } from "./rows/insights.mjs";

const CHANGE = "desk-change";
const emit = () => document.dispatchEvent(new CustomEvent(CHANGE, { detail: desk }));

export function onDeskChange(handler) {
  document.addEventListener(CHANGE, (event) => handler(event.detail));
}

export function setRange(start, end) {
  desk.range = [start, end];
  emit();
}

export function setPark(park) {
  desk.park = park;
  emit();
}

// The company months inside the chosen range, as the dates of the month rows.
export function selectedMonths() {
  if (desk.range === null) return [];
  const months = deskMonths({ park_month: parkMonthData() }).map((row) => row.month);
  return months.slice(desk.range[0], desk.range[1] + 1);
}

function initTabs() {
  const tabs = $$('[role="tab"]');
  const panels = $$('[role="tabpanel"]');
  const select = (index, focus) => {
    desk.view = tabs[index].dataset.view;
    tabs.forEach((tab, i) => {
      tab.setAttribute("aria-selected", String(i === index));
      tab.tabIndex = i === index ? 0 : -1;
      panels[i].hidden = i !== index;
    });
    if (focus) tabs[index].focus();
    emit();
  };
  tabs.forEach((tab, index) => {
    tab.addEventListener("click", () => select(index, false));
    tab.addEventListener("keydown", (event) => {
      const last = tabs.length - 1;
      const target = { ArrowRight: index === last ? 0 : index + 1, ArrowLeft: index === 0 ? last : index - 1, Home: 0, End: last }[event.key];
      if (target === undefined) return;
      event.preventDefault();
      select(target, true);
    });
  });
  if (tabs.length > 0) desk.view = tabs[0].dataset.view;
}

// The season strip: one bar per company month (all parks added), drawn behind the two handles.
// A handle is 28px wide, so bar centres run from 14px to the width less 14px. Bars inside the
// chosen range are red; the rest are muted, and a band marks the range.
const HANDLE = 28;
function drawStrip(host, totals, [from, to]) {
  const width = Math.max(240, Math.round(host.getBoundingClientRect().width));
  const height = 64;
  const top = 6;
  const base = height - 18;
  const at = (i) => HANDLE / 2 + (totals.length === 1 ? 0.5 : i / (totals.length - 1)) * (width - HANDLE);
  const barWidth = Math.max(6, ((width - HANDLE) / Math.max(totals.length, 4)) * 0.55);
  const most = Math.max(...totals, 1);
  host.setAttribute("viewBox", `0 0 ${width} ${height}`);
  clear(host);
  svg("rect", { x: at(from) - barWidth, y: 0, width: at(to) - at(from) + 2 * barWidth, height: height - 14, rx: 4, class: "b-sel" }, host);
  totals.forEach((total, i) => {
    const loss = total < 0;
    // A loss month hangs a short bar below the baseline in the loss colour; an empty month has no bar.
    const y = loss ? base : base - (total / most) * (base - top);
    const barHeight = loss ? 4 : base - y;
    const kind = loss ? "b-loss" : i >= from && i <= to ? "b-on" : "b-off";
    svg("rect", { x: at(i) - barWidth / 2, y, width: barWidth, height: barHeight, class: kind }, host);
  });
}

// `host` is the strip's svg, the first child of the brush that holds the two range inputs.
function initStrip(host) {
  const months = deskMonths({ park_month: parkMonthData() }).map((row) => row.month);
  const totals = months.map((month) =>
    parkMonthData().filter((row) => row.statement_company_date === month).reduce((sum, row) => sum + row.operating_profit, 0),
  );
  const draw = () => drawStrip(host, totals, desk.range);
  onDeskChange(draw);
  new ResizeObserver(draw).observe(host);
  draw();
}

function initRange() {
  const out = $("[data-range-out]");
  if (out === null) return;
  const start = $('input[data-range="start"]');
  const end = $('input[data-range="end"]');
  const presets = $$("[data-preset]");
  const labels = out.dataset.months.split("|");
  const show = () => {
    const [a, b] = desk.range;
    start.value = a;
    end.value = b;
    out.textContent = a === b ? labels[a] : `${labels[a]} to ${labels[b]}`;
    start.setAttribute("aria-valuetext", labels[a]);
    end.setAttribute("aria-valuetext", labels[b]);
    // With a one-year sample the year preset and "All months" cover the same months: only the last preset (All months) shows pressed.
    const pressed = presets.map((preset) => preset.dataset.preset === `${a},${b}`);
    const last = pressed.lastIndexOf(true);
    presets.forEach((preset, i) => preset.setAttribute("aria-pressed", String(i === last)));
  };
  desk.range = [0, Number(end.max)];
  show();
  onDeskChange(show);
  initStrip(start.parentElement.firstElementChild);
  start.addEventListener("input", () => setRange(Number(start.value), Math.max(Number(start.value), desk.range[1])));
  end.addEventListener("input", () => setRange(Math.min(Number(end.value), desk.range[0]), Number(end.value)));
  for (const preset of presets) {
    preset.addEventListener("click", () => setRange(...preset.dataset.preset.split(",").map(Number)));
  }
}

function initParks() {
  const choices = $$('input[name="park"]');
  if (choices.length === 0) return;
  desk.park = "all";
  for (const choice of choices) choice.addEventListener("change", () => setPark(choice.value));
}

export function init() {
  initTabs();
  initRange();
  initParks();
}
