// Rows for the board meeting (D6): the first park's months for step 1 and its chart, and the
// closed company years for step 2. Pure: they take the parsed exports and touch no DOM, so the
// build and the browser share them and a test runs them under Node.
import { deskParks } from "./insights.mjs";

// The months of the first park in deskParks order (the lowest park_number with month rows), in export order (the exports sort months by date).
export function firstParkMonths(exports) {
  const parks = deskParks(exports);
  if (parks.length === 0) return [];
  return exports.park_month
    .filter((row) => row.park_id === parks[0].park_id)
    .map((row) => ({
      park_id: row.park_id,
      park_number: parks[0].park_number,
      month: row.statement_company_date,
      operating_profit: row.operating_profit,
    }));
}

// Step 2 compares company years, so it has rows only when at least two have closed.
export function closedYears(exports) {
  if (exports.company_year.length < 2) return [];
  return exports.company_year.map((row) => ({
    company_year: row.company_year,
    operating_profit: row.operating_profit,
  }));
}
