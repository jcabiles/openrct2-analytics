// The figure of "How it was built": counts of merged changes, review findings and tests, read from
// the committed file `built-counts.mjs`, which holds the date they were taken and how to recount.
import { BUILT_COUNTS } from "./built-counts.mjs";

export const figures = [
  {
    id: "built-numbers",
    rows: () =>
      BUILT_COUNTS.rows.map((row) => ({ ...row, shown: row.count.toLocaleString("en-US") })),
    heading: "By the numbers",
    unit: "counts of merged changes, review findings and automated tests",
    clock: "wall-clock hour",
    period: () => `as of ${BUILT_COUNTS.asOf}, commit ${BUILT_COUNTS.commit}`,
  },
];
