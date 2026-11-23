// Rows for the insights desk controls (D6): the company months, the parks and the company years
// the range brush, its presets and the park switch are made of. Pure: they take the parsed exports
// and touch no DOM, so the build and the browser share them and a test runs them under Node.
export function deskMonths(exports) {
  const months = new Set(exports.park_month.map((row) => row.statement_company_date));
  return [...months].sort().map((month) => ({ month }));
}

// The parks that have month rows, in the order of their exported `park_number` (R20). Each entry
// keeps the park's first and last month from `park_month` and carries its number. A park with month
// rows and no number is an error, so a page never prints an unnumbered park (R22).
export function deskParks(exports) {
  const numbers = new Map(exports.park.map((row) => [row.park_id, row.park_number]));
  const span = new Map();
  for (const row of exports.park_month) {
    const date = row.statement_company_date;
    const seen = span.get(row.park_id);
    if (seen === undefined) {
      const number = numbers.get(row.park_id);
      if (number === undefined || number === null) {
        throw new Error(`desk parks: park ${row.park_id} has month rows but no park_number`);
      }
      span.set(row.park_id, { park_id: row.park_id, park_number: number, first_month: date, last_month: date });
    } else {
      if (date < seen.first_month) seen.first_month = date;
      if (date > seen.last_month) seen.last_month = date;
    }
  }
  return [...span.values()].sort((a, b) => a.park_number - b.park_number);
}

// "Park 2" and so on from each entry's `park_number`, never from its position (R20). Only the "Park n" labels use it; the park-year table and the chart hover print the park ID.
export const parkLabels = (parks) => parks.map((park) => `Park ${park.park_number}`);

// One preset per company year found in the month rows: its first and last position in the list and
// the left edge of its label under the brush.
export function deskYears(months) {
  const years = [...new Set(months.map((row) => row.month.slice(0, 4)))];
  return years.map((year) => {
    const from = months.findIndex((row) => row.month.startsWith(year));
    const to = months.findLastIndex((row) => row.month.startsWith(year));
    return { year, from, to, left: `${((from / months.length) * 100).toFixed(2)}%` };
  });
}
