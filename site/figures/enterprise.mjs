// The company-rules section's figure: the park-openings list (R16). One entry per park with month rows,
// in `park_number` order; the list labels each "Park n" from its number (R20).
import { monthLabel, monthSpan } from "../figures.mjs";
import { parkClass } from "../assets/js/data.mjs";
import { deskParks, parkLabels } from "../assets/js/rows/insights.mjs";

// A pure rows function: one { park_id, park_number, month } per deskParks entry, month being the park's first company month.
export function parkOpeningRows(exports) {
  return deskParks(exports).map((park) => ({
    park_id: park.park_id,
    park_number: park.park_number,
    month: park.first_month,
  }));
}

export const figures = [
  {
    id: "park-openings",
    rows: parkOpeningRows,
    heading: "Parks, by opening year",
    unit: "company month of first statement",
    clock: "company month",
    // figures.mjs imports this file, so monthLabel and monthSpan are only read here, at call time.
    swatch: parkClass,
    line: (rows, index) => `${parkLabels(rows)[index]} opened in ${monthLabel(rows[index].month)}.`,
    period: (rows) => monthSpan(rows.map((row) => row.month)),
  },
];
