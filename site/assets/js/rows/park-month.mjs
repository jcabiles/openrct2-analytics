// Rows for the operating-profit chart and month table (D6): one per company month, in export order,
// with each park's first month flagged (it has no earlier statement, so it is not checked).
// Pure: it takes the parsed exports and touches no DOM, so a test runs it under Node.
export function parkMonthRows(exports) {
  return exports.park_month.map((row, index, rows) => ({
    key: row.park_month_key,
    park_id: row.park_id,
    month: row.statement_company_date,
    operating_profit: row.operating_profit,
    first_of_park: index === 0 || rows[index - 1].park_id !== row.park_id,
  }));
}
