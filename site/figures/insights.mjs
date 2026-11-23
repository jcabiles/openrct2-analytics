// Figure registry entries for the insights desk: its controls and the Operations and Attractions
// panels. The ride panels read the `ride_month` and `ride_year` exports; the panels with no export
// behind them stay pending (ADR 0045).
import { monthLabel, monthSpan, yearSpan } from "../figures.mjs";
import { deskMonths, deskParks, deskYears, parkLabels } from "../assets/js/rows/insights.mjs";
import {
  availabilityRows,
  longestLineRows,
  rideYearRows,
  ridersRows,
} from "../assets/js/rows/panels.mjs";

// figures.mjs imports this file, so yearSpan is only read here, at call time.
const yearsOfDates = (dates) => yearSpan(dates.map((date) => date.slice(0, 4)));

const pending = (id, heading, unit, clock) => ({ id, rows: () => [], heading, unit, clock });

// A cell is the export value as delivered; a null reading says so instead of printing "null".
const NO_READING = "no reading";
const cell = (value) => (value === null ? NO_READING : String(value));
const twoPlaces = (value) => (value === null ? NO_READING : value.toFixed(2));
const monthPeriod = (rows) => monthSpan(rows.map((row) => row.month));
const yearPeriod = (rows) => yearSpan(rows.map((row) => row.year));
const rideMonthHeaders = (last) => ["Park", "Ride", "Company month", last];
const rideYearHeaders = (last, third) => ["Park", "Ride", "Company year", last, third];

export const figures = [
  {
    id: "desk-play",
    rows: deskParks,
    unit: "parks",
    clock: "company month",
    period: (rows) => yearsOfDates(rows.flatMap((row) => [row.first_month, row.last_month])),
    sentence: (rows) =>
      `Data shown: ${parkLabels(rows).join(", ")}, ` +
      yearsOfDates(rows.flatMap((row) => [row.first_month, row.last_month])),
  },
  {
    id: "desk-range",
    rows: deskMonths,
    unit: "company months",
    clock: "company month",
    period: (rows) => yearsOfDates(rows.map((row) => row.month)),
    presets: deskYears,
    label: "Season range (company months)",
    startLabel: "Range start, company month",
    endLabel: "Range end, company month",
  },
  {
    id: "desk-park",
    rows: deskParks,
    unit: "parks",
    clock: "company month",
    period: (rows) => yearsOfDates(rows.flatMap((row) => [row.first_month, row.last_month])),
  },
  pending("note-ops", null, "notes", "company month"),
  pending("note-attr", null, "notes", "company month"),
  {
    id: "ops-availability",
    rows: availabilityRows,
    heading: "Availability by ride",
    unit: "percent of operating time",
    clock: "company month",
    period: monthPeriod,
    caption: "Average availability from downtime by ride and company month, in percent",
    headers: rideMonthHeaders("Availability"),
    cells: (row) => [row.park, row.ride, monthLabel(row.month), twoPlaces(row.availability)],
  },
  {
    id: "ops-waits",
    rows: longestLineRows,
    heading: "Longest line by ride",
    unit: "minutes",
    clock: "company month",
    period: monthPeriod,
    caption: "Longest line seen in minutes, by company month, for the five busiest rides of each park",
    headers: rideMonthHeaders("Longest line"),
    cells: (row) => [row.park, row.ride, monthLabel(row.month), cell(row.longestLine)],
  },
  {
    id: "ops-riders",
    rows: ridersRows,
    heading: "Riders per ride by month",
    unit: "riders",
    clock: "company month",
    period: monthPeriod,
    caption: "Riders by ride and company month",
    headers: rideMonthHeaders("Riders"),
    cells: (row) => [row.park, row.ride, monthLabel(row.month), cell(row.riders)],
  },
  pending("ops-guardrails", "Guardrails", "percent change", "company year"),
  {
    id: "attr-rating",
    rows: rideYearRows,
    heading: "Riders against guest rating",
    unit: "riders; guest rating points",
    clock: "company year",
    period: yearPeriod,
    caption: "Riders and latest guest rating by ride and company year",
    headers: rideYearHeaders("Riders", "Guest rating"),
    cells: (row) => [row.park, row.ride, String(row.year), cell(row.riders), cell(row.rating)],
  },
  {
    id: "attr-age",
    rows: rideYearRows,
    heading: "Ride age",
    unit: "game months since built; guest rating points",
    clock: "company year",
    period: yearPeriod,
    caption: "Latest ride age in game months and latest guest rating by ride and company year",
    headers: rideYearHeaders("Ride age", "Guest rating"),
    cells: (row) => [row.park, row.ride, String(row.year), cell(row.age), cell(row.rating)],
  },
  pending("attr-types", "Ride profit by ride type", "US dollars", "company year"),
  pending("attr-scatter", "Excitement against ride profit", "rating points; US dollars", "company year"),
  pending("attr-table", "The ride table", "rides", "company year"),
];
