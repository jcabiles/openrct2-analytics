# ADR 0052: terminal messages may show game money in dollars

- Date: 2026-11-15.
- Status: Proposed with the play-launcher spec (`docs/ai-dlc/specs/play-launcher-autofile.md`); it takes effect when the
  branch that builds it merges. It is an exception to rule 3 of "Never break" in `AGENTS.md`, for display text only.

## Bottom line

Rule 3 keeps money in the game's tenths of a dollar until one staging conversion. This record allows one exception:
text printed to the terminal for a person may show game money in dollars, through the one function
`display_usd` in `src/openrct2_analytics/ingest/autopilot_progress.py`. Nothing converted is stored, returned in a
result object or written to a file. The first use is the `Profit:` line of the autopilot report.

## Context

A finished autopilot run now prints the park's profit for the year. A reader of that line wants dollars. The sum is the
game's own total: the 14 statement lines the plugin sends in each `finance_month` event, each as `<type>_tenths`
(`plugin/src/finance.ts`). Printing tenths would force the reader to convert by hand, and a wrong hand conversion is
the exact error rule 3 exists to prevent.

## Decision

1. **Display text may show dollars.** The conversion is `display_usd(tenths)` (for example, `-1234` is `-$123.40`),
   and it is the only place the terminal path converts. Gain: the line reads as money. Cost: a second conversion
   outside dbt, which is why it is the only one and sits in one function.
2. **Everything else stays in tenths.** The profit is summed in tenths, carried in tenths in the run result, and
   converted only when the report line is formatted. No file, Parquet column, contract field or mart receives a
   dollar value. Gain: rule 3 holds for every stored number. Cost: a reviewer must check that no new caller stores
   the display string.
3. **The line says it is for display.** The report line ends "shown in dollars for display", so a reader does not copy
   it into an analysis as a metric. Metrics still name their unit and their clock (rule 3).

## Rejected options

- **Printing tenths.** Gain: no exception. Cost: a reader converts by hand, with a real risk of a factor-of-ten error.
- **Reading the dbt marts for the profit.** Gain: the one conversion stays in staging. Cost: the report would need the
  warehouse built first, and the autopilot run ends before any build.

## Consequences

- Rule 3 in `AGENTS.md` still reads as written; this record is the named exception.
- A later terminal message that shows money uses `display_usd` and needs no new record. A stored dollar value still
  breaks rule 3.
