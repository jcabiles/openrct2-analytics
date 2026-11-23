// Figure registry entries for the board meeting: the sentences of steps 1 to 4 and the pinned
// stage beside them. Only step 1 (the first park's months) and step 2 (two or more closed company
// years) read the exports; the findings of steps 3 and 4 and the later charts wait as pending.
import { monthLabel, monthSpan, usd, yearSpan } from "../figures.mjs";
import { parkLabels } from "../assets/js/rows/insights.mjs";
import { closedYears, firstParkMonths } from "../assets/js/rows/story.mjs";

// figures.mjs imports this file, so monthLabel, monthSpan and usd are only read here, at call time.
// The first park's rows come from the first park in deskParks order, so its label is the first one.
const firstLabel = (rows) => parkLabels([rows[0]])[0];

const pending = (id, unit, clock, heading) => ({ id, rows: () => [], unit, clock, ...(heading && { heading }) });

export const figures = [
  {
    id: "story-step-1",
    rows: firstParkMonths,
    unit: "US dollars",
    clock: "company month",
    period: (rows) => monthSpan(rows.map((row) => row.month)),
    sentence: (rows) =>
      `${firstLabel(rows)} opened in ${monthLabel(rows[0].month)}. Its months so far: ` +
      `${rows.map((row) => `${monthLabel(row.month)} ${usd(row.operating_profit)}`).join(", ")}.`,
  },
  {
    id: "story-step-2",
    rows: closedYears,
    unit: "US dollars",
    clock: "company year",
    period: (rows) => yearSpan(rows.map((row) => row.company_year)),
    sentence: (rows) =>
      `Operating profit went from ${usd(rows[0].operating_profit)} in company year ` +
      `${rows[0].company_year} to ${usd(rows.at(-1).operating_profit)} in company year ` +
      `${rows.at(-1).company_year}.`,
  },
  pending("story-step-3", "percent change", "company year"),
  pending("story-step-4", "US dollars", "company year"),
  {
    id: "story-stage-first",
    rows: firstParkMonths,
    heading: "Operating profit by company month",
    unit: "US dollars",
    clock: "company month",
    period: (rows) => monthSpan(rows.map((row) => row.month)),
    sentence: (rows) => `Bars show each company month of ${firstLabel(rows)}.`,
    chartLabel: "Bar chart of operating profit per company month for the first park, in US dollars",
  },
  pending("story-stage-later", "US dollars", "company year", "Company year and ride profit charts"),
];
