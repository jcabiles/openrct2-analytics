// The board meeting: the steps light up as they scroll into view (IntersectionObserver only) and
// the pinned stage follows. Step 1's chart draws the first park's months from the embedded rows;
// with no month rows the chart mount stays empty and hidden.
import { $, $$ } from "./dom.mjs";
import { parkData, parkMonthData } from "./data.mjs";
import { plotStyle, token } from "./chart-style.mjs";
import { firstParkMonths } from "./rows/story.mjs";

const shortMonth = (date) =>
  new Date(`${date}T00:00:00Z`).toLocaleString("en-US", { month: "short", timeZone: "UTC" });

function initChart() {
  const mount = $("#stage-chart");
  const rows = firstParkMonths({ park_month: parkMonthData(), park: parkData() });
  if (rows.length === 0) return;
  let drawnWidth = 0;
  const draw = () => {
    // A hidden stage panel measures 0 wide; the chart keeps its last drawing until it is shown.
    if (mount.clientWidth === 0 || mount.clientWidth === drawnWidth) return;
    drawnWidth = mount.clientWidth;
    mount.replaceChildren(
      Plot.plot({
        width: drawnWidth,
        height: 360,
        style: { ...plotStyle(), fontSize: "14px" },
        marginLeft: 56,
        x: { type: "band", label: null, tickFormat: shortMonth },
        y: { label: "US dollars", grid: true },
        marks: [
          Plot.barY(rows, { x: "month", y: "operating_profit", fill: token("--p1") }),
          Plot.ruleY([0]),
        ],
      }),
    );
  };
  new ResizeObserver(draw).observe(mount);
  draw();
}

function initSteps() {
  // The phone layout hides the pinned stage only once this script has moved its chart panel into step 1.
  document.documentElement.classList.add("story-js");
  const steps = $$(".step");
  const dots = $$(".dots span");
  const panels = $$("[data-stage]");
  const narrow = matchMedia("(max-width: 1023px)");
  const show = (index) => {
    steps.forEach((step, i) => step.classList.toggle("on", i === index));
    dots.forEach((dot, i) => dot.classList.toggle("on", i === index));
    // Step 1 owns the chart panel; later steps show the panel of charts that are still pending.
    const stage = index === 0 ? "first" : "later";
    panels.forEach((panel) => {
      panel.hidden = !narrow.matches && panel.dataset.stage !== stage;
    });
  };
  // Below 1024px the pinned stage is hidden; step 1's chart panel sits inside step 1's card instead,
  // so the phone shows the chart under its step. Steps 2 to 5 already carry their own figures.
  const first = $('[data-stage="first"]');
  const stageEl = first.parentElement;
  const home = () => {
    if (narrow.matches) steps[0].querySelector(".step-card").insertBefore(first, steps[0].querySelector(".step-card > .fine"));
    else stageEl.insertBefore(first, stageEl.firstChild);
    show(Math.max(0, steps.findIndex((step) => step.classList.contains("on"))));
  };
  narrow.addEventListener("change", home);
  show(0);
  if (narrow.matches) home();
  const watcher = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) if (entry.isIntersecting) show(steps.indexOf(entry.target));
    },
    { rootMargin: "-45% 0px" },
  );
  steps.forEach((step) => watcher.observe(step));
}

export function init() {
  initChart();
  initSteps();
}
