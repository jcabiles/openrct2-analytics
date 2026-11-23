// Figure registry entries for the Finance view. The profit chart's own entry (park-month) sits in
// the frame list. The revenue-mix panel reads the `park_month_revenue` export; the exports hold no
// visits, price, growth or statement data, so the other panels stay pending (ADR 0045).
import { monthLabel, monthSpan, usd, yearSpan } from "../figures.mjs";
import { parkClass } from "../assets/js/data.mjs";
import { deskParks } from "../assets/js/rows/insights.mjs";
import { revenueMixRows } from "../assets/js/rows/panels.mjs";

const pending = (id, heading, unit, clock) => ({ id, rows: () => [], heading, unit, clock });

// A share is null when the month's operating revenue is 0 or missing; the cell says so.
const share = (value) => (value === null ? "no share" : value.toFixed(2));

export const figures = [
  {
    id: "fin-legend",
    rows: deskParks,
    unit: "parks",
    clock: "company month",
    swatch: parkClass,
    period: (rows) => yearSpan(rows.flatMap((row) => [row.first_month, row.last_month]).map((date) => date.slice(0, 4))),
  },
  pending("note-fin", null, "notes", "company month"),
  pending("fin-visits", "Guest visits and per-capita spending", "guests, then US dollars per visit", "company month"),
  pending("fin-price", "Ride price and riders", "US dollars, then riders per game day", "game day"),
  {
    id: "fin-mix",
    rows: revenueMixRows,
    heading: "Revenue mix",
    unit: "US dollars; percent of operating revenue",
    clock: "company month",
    period: (rows) => monthSpan(rows.map((row) => row.month)),
    caption: "Revenue lines in US dollars and their shares of operating revenue, by park and company month",
    headers: [
      "Park",
      "Company month",
      "Rides",
      "Food and drink",
      "Merchandise",
      "Entrance",
      "Rides share",
      "Food and drink share",
      "Merchandise share",
      "Entrance share",
    ],
    cells: (row) => [
      row.park,
      monthLabel(row.month),
      usd(row.ride),
      usd(row.foodDrink),
      usd(row.merchandise),
      usd(row.entrance),
      share(row.ridePct),
      share(row.foodDrinkPct),
      share(row.merchandisePct),
      share(row.entrancePct),
    ],
  },
  pending("fin-growth", "Growth between company years", "percent change", "company year"),
  pending("fin-stalls", "Stall items", "US dollars; items sold", "company year"),
  pending("fin-statement", "Full profit and loss statement", "US dollars", "company month"),
];
