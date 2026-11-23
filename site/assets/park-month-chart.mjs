// Draws one stacked bar per company month from the rows the page embeds at build time. The rows go
// to Plot unchanged; colours and type come from the token reader. Each park's first bar (its month
// has no earlier statement, so it is not checked) is drawn as a dashed outline with no fill.
// `redrawParkMonthChart` draws for a month range, a park choice and the desk's park order, which
// sets the colours; the chart draws nothing until it is given that order.
import { plotStyle, token } from "./js/chart-style.mjs";
import { parkClass, usd } from "./js/data.mjs";

const rows = JSON.parse(document.getElementById("park-month-data").textContent);
const container = document.getElementById("park-month-chart");

const monthLabel = (date) =>
  new Date(date + "T00:00:00Z").toLocaleString("en-US", {
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  });

const firstOfPark = new Set(
  rows.filter((row, i) => i === 0 || rows[i - 1].park_id !== row.park_id).map((row) => row.park_month_key),
);
const allMonths = [...new Set(rows.map((row) => row.statement_company_date))].sort();

// The chosen company months (null: every month), park ("all" or a park ID) and park order.
let shown = { months: null, park: "all", parks: [] };
let drawnWidth = 0;

const visibleRows = () =>
  rows.filter(
    (row) =>
      (shown.months === null || shown.months.includes(row.statement_company_date)) &&
      (shown.park === "all" || row.park_id === shown.park),
  );

const MARGIN_LEFT = 56;

const paint = () => {
  const width = container.clientWidth;
  // A hidden view measures zero; the size observer draws it when it is shown again.
  drawnWidth = width;
  if (rows.length === 0 || width === 0 || shown.parks.length === 0) return;
  container.replaceChildren(
    Plot.plot({
      width,
      height: 290,
      style: { ...plotStyle(), fontSize: "12px" },
      marginBottom: 50,
      // "$6,500" at 12px measures about 40px; plus 6px tick and 3px padding is 49px, so 56 leaves 7px spare.
      marginLeft: MARGIN_LEFT,
      x: { type: "band", paddingInner: 0.3, paddingOuter: 0.1, domain: shown.months ?? allMonths, label: "Company month", tickFormat: monthLabel },
      y: { label: "Operating profit", grid: true, tickFormat: (value) => usd(value, 0) },
      color: { domain: shown.parks, range: shown.parks.map((_, index) => token(`--${parkClass(index)}`)) },
      marks: [
        Plot.barY(
          visibleRows(),
          Plot.stackY({
            x: "statement_company_date",
            y: "operating_profit",
            fill: "park_id",
            fillOpacity: (row) => (firstOfPark.has(row.park_month_key) ? 0 : 1),
            stroke: token("--ink"),
            strokeOpacity: (row) => (firstOfPark.has(row.park_month_key) ? 1 : 0),
            strokeWidth: 2,
            strokeDasharray: "6 4",
            inset: 1,
            title: (row) => `${monthLabel(row.statement_company_date)}, ${row.park_id}: ${usd(row.operating_profit, 0)}`,
          }),
        ),
        Plot.ruleY([0]),
      ],
    }),
  );
};

// Redraws for the chosen months and park; returns how many month rows the choice holds.
export function redrawParkMonthChart(months, park, parks) {
  shown = { months, park, parks };
  paint();
  return visibleRows().length;
}

new ResizeObserver(() => {
  if (container.clientWidth !== drawnWidth) paint();
}).observe(container);
