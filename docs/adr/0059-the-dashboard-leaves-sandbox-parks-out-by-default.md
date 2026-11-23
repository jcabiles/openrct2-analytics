# ADR 0059: the dashboard leaves Sandbox parks out by default

- Date: 2026-11-20.
- Status: Proposed with the spec `docs/ai-dlc/specs/sandbox-hide.md`; it takes effect when the branch that builds it
  merges. It amends ADR 0054 and ADR 0057 and edits neither.

## Bottom line

The local company dashboard's "All parks" figures now leave out Sandbox (throwaway practice) parks. A switch under the
park picker, "Sandbox parks: Left out / Included", brings them back, and its state lives only in the page address
(`?sandbox=shown`). Park labels reach the page from the server through a second page global,
`window.DASHBOARD_LABELS`. Gain: practice play no longer distorts the company figures, and nothing is deleted or
hidden for good. Cost: one more global beside `window.DASHBOARD`, and one page reload for each switch.

## Context

ADR 0054 summed the all-parks figures from the company statement mart, which adds every park, Sandbox parks included,
and has no park column to filter on. A practice park therefore changed the company totals. ADR 0057 gave
`marts.dim_park` a `park_number` that is null exactly for a Sandbox park, which makes the classification available to
`data.py` without a new model.

## Decision

1. **Every "All parks" total is a sum of `marts.obt_park_month` over the parks in view** (spec decision D2, one summing path for every scope). `data.py` no longer reads
   `obt_company_month`. The summed fields are the additive ones (statement amounts in US dollars, guest visits in guests
   and operating days in days; company date clock for the month). A month opens when at least one park in view closed it
   (has a statement for it). Cash in bank (US dollars) and guests in the park (guests), per company month, are the sum
   over each park in view of its last kept reading in that month (company date clock), whether or not that park closed
   the month. A park is Sandbox when
   its `dim_park.park_number` is null. The data file holds a scope `all` (company parks) and, only when a Sandbox park
   exists, a scope `with_sandbox` (every park), plus one scope per park when there is more than one park or any Sandbox park exists.
2. **The switch lives in `shell()` of `src/openrct2_analytics/dashboard/app/shared.js` and its state lives only in the address query** (spec decision D4, the switch's placement and state). It is drawn
   in the "All parks" view when at least one park is Sandbox; `?sandbox=shown` selects `with_sandbox`, and anything
   else leaves Sandbox parks out. No browser storage holds the choice. A park view carries only its park and has no
   switch. A Sandbox park stays in the park picker and keeps its own scope.
3. **Labels reach the page from the server through `window.DASHBOARD_LABELS`** (spec decision D6, one label and one fallback for banner and switch). On each page load, when the current
   build has a Sandbox park, the server adds `<script>window.DASHBOARD_LABELS = {...};</script>` after the banner. It
   maps each Sandbox park ID to its `<name> (first played <Mon D>)` label from `park_label` (ADR 0058), or to
   `<park ID> (first-played date unavailable)` when no label can be read. Every `<` is written as `\u003c`, so a park
   name cannot close the script element. The banner's Sandbox set comes from the same build (the parks with
   `sandbox: true`), so the banner, the script and the pages share one source and the banner needs no separate registry
   read. This replaces the spec's decision D1, which had the banner keep its own registry read. The banner sentence is `Sandbox park <label> is left out of the All parks figures unless Sandbox parks are
   included; remove it with make delete-company-data PARK=<id>.`, true with the switch on or off.

## Amendments to earlier records

- **ADR 0054, "Season cutoff":** "the company statement for all parks" now reads "the statements of the parks in view".
- **ADR 0054, "One data file":** the app also reads `window.DASHBOARD_LABELS`, a small object the server writes into
  each page. It holds only Sandbox park labels and no figure.
- **ADR 0057, consequences:** "The dashboard is unchanged: it selects named columns from `dim_park`" no longer holds.
  The dashboard reads `park_number` to classify Sandbox parks.

## Consequences

- Gain: the company figures cover company parks only by default, with one code path for every scope.
- Cost: the summing queries in `data.py` change, each scope build gains one extra `group by`, and a warehouse built before
  `park_number` existed fails its rebuild until `make transform DATA_SET=company` or a filing runs (the banner says so).
- Nothing is deleted; `make delete-company-data` is unchanged.
