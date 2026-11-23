// The figure registry (R9 to R11, R20): every figure region's id, rows function, heading, unit line
// and the sentence pattern that carries its values. A figure is live when its rows function returns
// rows (or it is always live), and pending otherwise. Values are export cells, formatted and
// nothing else; periods, labels and year lists come from row keys only.
import { parkMonthRows } from "./assets/js/rows/park-month.mjs";
import { figures as built } from "./figures/built.mjs";
import { figures as enterprise } from "./figures/enterprise.mjs";
import { figures as finance } from "./figures/finance.mjs";
import { figures as infra } from "./figures/infra.mjs";
import { figures as insights } from "./figures/insights.mjs";
import { figures as story } from "./figures/story.mjs";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

// Hard-coded month names, never a locale call: page_check rebuilds the same text from the same list.
export const monthLabel = (date) => `${MONTHS[Number(date.slice(5, 7)) - 1]} ${date.slice(0, 4)}`;
export const usd = (value) => value.toLocaleString("en-US", { style: "currency", currency: "USD" });
export const PENDING = "figure pending";

const yearList = (years) => [...new Set(years)].sort((a, b) => a - b);
// The company years a list of years (numbers or the year part of dates) covers, from keys only.
export const yearSpan = (years) => {
  const list = yearList(years);
  return list.length === 1 ? `company year ${list[0]}` : `company years ${list[0]} to ${list.at(-1)}`;
};
// The company months a list of month dates covers; a single month is just its label.
export const monthSpan = (dates) => {
  const sorted = [...dates].sort();
  return sorted[0] === sorted.at(-1)
    ? monthLabel(sorted[0])
    : `${monthLabel(sorted[0])} to ${monthLabel(sorted.at(-1))}`;
};

// The evidence block's pinned sentences (PC10); their text must not change, except `sample`,
// which is filled from the sample record (`site/_data/sample.json`) and never fixed text.
export const EVIDENCE = {
  closeRule:
    "A company year closes when every park expected in it has all eight monthly statements, March to" +
    " October, and a park's partial first season does not hold a year open; at least one expected" +
    " park must also be complete.",
  reconciliation:
    "Months checked counts the months that match the game's books exactly: operating profit plus" +
    " capital spending plus interest equals the change in cash less loan, less the money already" +
    " booked to the new month, from the previous month, with no month missing in between.",
  firstMonth:
    "Each park's first month has no earlier statement to reconcile, so its bar is not checked.",
  // The sample sentence for one sample record row; a missing or malformed record fails the build.
  // A company park can hold kept sessions before its first monthly statement, so a record with no
  // park does not point at the (empty) park-years table.
  sample: (record) => {
    if (
      record === undefined ||
      typeof record.parks !== "number" ||
      typeof record.sessions !== "number" ||
      typeof record.player_played !== "boolean"
    ) {
      throw new Error("site/_data/sample.json is missing or holds no valid sample record");
    }
    const parks =
      record.parks === 0
        ? "parks with no closed monthly statement yet"
        : "the parks listed in the park-years table";
    return record.player_played
      ? `Sample: ${parks}, ${record.sessions} sessions, at least one with a player; observational.`
      : `Sample: ${parks}, ${record.sessions} headless sessions with no player; observational.`;
  },
};

const MONEY_HEADER = "Operating profit (not yet reconciled)";

const FRAME = [
  {
    id: "company-years",
    rows: (exports) => yearList(exports.park_year.map((row) => row.company_year)),
    unit: "company years",
    clock: "company year",
    period: yearSpan,
    sentence: (years) =>
      years.length === 1 ? `Company year ${years[0]}` : `Company years ${years[0]} to ${years.at(-1)}`,
  },
  {
    // The platform counts have no checked source yet, so the hero's sentence waits as pending.
    id: "platform",
    rows: () => [],
    unit: "counts of event types, contracts, models and exports",
    clock: "wall-clock hour",
  },
  {
    id: "company-year",
    always: true,
    rows: (exports) => exports.company_year,
    heading: "Closed company years",
    unit: "US dollars",
    clock: "company year",
    period: (rows) => yearSpan(yearList(rows.map((row) => row.company_year))),
    caption: "Closed company years, operating profit in US dollars",
    headers: ["Company year", "Parks reporting", "Partial first seasons", "Park-months checked", MONEY_HEADER],
    empty: "No company year has closed yet.",
  },
  {
    id: "park-year",
    always: true,
    rows: (exports) => exports.park_year,
    heading: "Park-years",
    unit: "US dollars",
    clock: "company year",
    period: (rows) => yearSpan(yearList(rows.map((row) => row.company_year))),
    caption: "Operating profit per park and company year, in US dollars",
    headers: ["Company year", "Park ID", "Statements kept of expected", "Months checked", MONEY_HEADER, "Status"],
    statusWords: {
      complete: "complete",
      open: "not closed",
      incomplete: "incomplete",
      partial_first_season: "partial first season",
    },
  },
  {
    // The sample statement's sentence is the caller's markup (it needs the record's player flag);
    // a record with no session leaves the figure pending, so the statement shows no number.
    id: "sample",
    rows: (exports) => exports.sample.filter((row) => row.sessions > 0),
    unit: "sessions",
    clock: "wall-clock hour",
    period: () => "this build",
  },
  {
    id: "park-month",
    always: true,
    rows: parkMonthRows,
    heading: "Operating profit by month",
    unit: "US dollars",
    clock: "company month",
    period: (rows) => monthSpan(rows.map((row) => row.month)),
    caption: "Operating profit by company month, in US dollars",
    headers: ["Company month", "Operating profit"],
    firstMark: "not checked: first month",
    chartLabel: "Bar chart of operating profit per company month in US dollars",
    trace: "How the operating profit is traced to the game's books: docs/showcase/trace-operating-profit.md.",
  },
];

export const FIGURES = [...FRAME, ...enterprise, ...infra, ...built, ...story, ...insights, ...finance];
const REGISTRY = new Map(FIGURES.map((entry) => [entry.id, entry]));
if (REGISTRY.size !== FIGURES.length) throw new Error("figure registry: an id is listed twice");

// The view a template renders: the entry, its rows, its state, its unit line and its sentence.
export function figure(id, exports) {
  const entry = REGISTRY.get(id);
  if (entry === undefined) throw new Error(`figure registry: ${id} is not listed`);
  const rows = entry.rows(exports);
  const state = entry.always || rows.length > 0 ? "live" : "pending";
  const live = state === "live" && rows.length > 0;
  const period = live ? entry.period(rows) : PENDING;
  return {
    ...entry,
    rows,
    state,
    pending: PENDING,
    unitLine: `(unit: ${entry.unit}; clock: ${entry.clock}; period: ${period})`,
    sentence: live && entry.sentence ? entry.sentence(rows) : null,
  };
}
