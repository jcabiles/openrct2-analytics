# ADR 0026: the first site page reads a build-time JSON export; Parquet in the browser waits for NEXT 15

- Date: 2026-10-13
- Status: Accepted (2026-10-13). The project owner approved the steel-thread spec at Gate 2. It records the project owner's Gate 1 ruling of 2026-10-13 for roadmap NEXT 28 (the steel
  thread: one number, operating profit per park per company month, carried from the game event to one chart page)
  and the Gate 2 rulings of the same day on the spec's open points (listed under "Gate 2 rulings" below; the spec
  itself was removed when the slice shipped).
- Superseded in part by ADR 0035 (`docs/adr/0035-company-years-close-from-a-register-derived-in-dbt.md`), 2026-10-18:
  its roll-up-mart decision (the year-to-date table). The body below is not edited.
- Amended by ADR 0043 (`docs/adr/0043-showcase-system-fonts-and-story-passages.md`), 2026-11-02.
- Amends, for the steel-thread page only, these rules of ADR 0021 (`docs/adr/0021-showcase-site-tool.md`) and the
  ADR 0015 rules it carries forward (`:46`); each departure ends when NEXT 15 (the website build) does the migration
  below:
  - **Data path** (ADR 0021 `:46`, "pages read Parquet exports of the dbt marts"): this page reads JSON exports,
    embedded at build time.
  - The comparison does not sort, unlike ADR 0021's rule: the page takes the last roll-up row for its headline and
    draws bars in row order.
  - **Published-number mapping** (ADR 0015 `:62` and build acceptance test 3): deferred to NEXT 15; the trace doc
    `docs/showcase/trace-operating-profit.md` carries the one number's source and tests in prose meanwhile.
  - **Story files** (ADR 0021 `:46`, "story files in `docs/showcase/story/` are the single source of text"): this
    page's headline, check line and sample note are written in `site/index.njk`, not in story files.
  - **Offline page-load test** (ADR 0021 `:46`, the carried acceptance tests): replaced on this page by a static check
    of the built HTML and the copied browser files (`page_check`); the drawn bars are judged in a browser by a
    reviewer.
  - **Chart specs and the chart source check** (ADR 0015 `:63`, "Chart calculations", and build acceptance test 4):
    this page has one hand-written chart module, held by review to the same rule: no arithmetic on values, the only computation being the `park_id` comparison that picks each park's first row;
    `page_check` confirms it reads only the embedded element and loads nothing remote;
    build acceptance tests 5 to 9 (README, calendar-constant, wrapper and label tests) also wait for NEXT 15.

  It does not depart from ADR 0015 `:62`'s "Each is a mart column": every number the page shows, except the cited game-calendar constant (see "Gate 2 rulings" below, point 4) and the literal sample-history text ("three headless sessions"), neither of which is a mart value, is a column of
  `fct_park_month` or `obt_company_year_to_date`. It does not depart from ADR 0021 `:42`'s `npm ci --ignore-scripts`:
  this slice changes `make setup` to that command, which the repo did not yet run. It supersedes nothing; ADR 0021's
  tool choice, pins and self-hosting rule stand.

## Bottom line

The first site page gets its numbers from two JSON files that a `make` step copies from the dbt marts at build time
and that are committed with the page. Eleventy puts the numbers into the page when it builds, so the browser runs no
database. Every number the page shows is a mart column tied to the game by a dbt test, and the export copies columns
without computing anything. `make check` rebuilds the exports from the marts and fails if a committed file differs by
a single value, and it refuses an export of any table not on a committed allowlist of mart tables. Reading Parquet in
the browser with DuckDB-WASM, as ADR 0021 decided, is deferred to the website build (roadmap NEXT 15), not dropped;
the last section lists what NEXT 15 must move over.

## Context

- ADR 0021 chose Eleventy with Observable Plot, Observable Inputs and DuckDB-WASM, and carried forward ADR 0015's
  rule that pages read Parquet exports of the marts in the browser (`:46`). That path needs a hand-written DuckDB-WASM
  loader and one pinned Parquet extension file outside `node_modules` (ADR 0021 `:44`).
- NEXT 28 exists to prove the whole chain on one number before 3c (the marts) and NEXT 15 (the website) widen it.
  Its page shows three monthly bars on the committed sample and a company-year-to-date total.
- The project owner ruled at Gate 1 (2026-10-13): "Page data: build-time JSON export (not DuckDB-WASM). ADR 0026
  records that in-browser Parquet (ADR 0021 line 46) is deferred to NEXT 15, not dropped. The ADR 0015 export
  acceptance tests (a one-value change in a served export fails `make check`; an export of a relation not on the
  allowlist fails) are built now, in a form NEXT 15 can reuse." The same ruling granted only two npm packages,
  `@11ty/eleventy` 3.1.6 and `@observablehq/plot` 0.6.17, and put DuckDB-WASM and the pinned extension out of scope.
- The roadmap guardrail (`docs/ai-dlc/roadmap/park-company.md:16`) says every number the site shows is tied to an
  in-game source by a dbt test. At Gate 2 (2026-10-13) the project owner ruled that the page's roll-up values become
  columns of a thin dbt-tested roll-up mart built in this slice, rather than values the export computes.

## Decision

1. **A `make` step writes JSON from the marts.** `make site-export` builds the committed sample on the dbt `ci`
   target in a temporary folder and runs `python -m openrct2_analytics.showcase.export write`, which reads the marts
   with the pinned Python `duckdb` and writes `site/_data/park_month.json` and `site/_data/company_year_to_date.json`.
   The export runs only after `dbt build` exits 0, so every written file comes from a build whose tests passed.
2. **The served copies are tracked and compared inside the gate.** The JSON files are committed. `make check` runs
   `export check` right after its sample `dbt build`: it rebuilds each export in memory and compares it with the
   committed file by row count, the header keys, and a SHA-256 hash of the rows in served order (the page relies on the order); any
   difference fails the gate. ADR 0021's rule hashes sorted rows; this comparison does not sort (see Amends above).
3. **An allowlist of mart relations.** `site/exports.toml` lists each export: name, mart relation, output file,
   columns and sort key. The export refuses a relation not on the list, and refuses a list entry outside the `marts`
   schema.
4. **The page reads the numbers at build time.** Eleventy loads the JSON as global data and writes the monthly rows
   into one JSON element in the page and into the month table (`#park-month-table`); the chart code passes those rows to Plot unchanged. Plot and the `d3` bundle it
   needs are copied from the locked `node_modules` into the built site and loaded by relative URLs; nothing comes
   from a CDN. The page is built offline inside `make check`, and a page check compares the embedded numbers with the
   committed JSON, checks the month table's cells against the same rows, and confirms the copied browser files sit where the page's script tags point.
5. **The roll-ups are mart columns; the export computes nothing.** The company year, the months present, the months
   checked and the company-year-to-date total are columns of `obt_company_year_to_date`, one row per company year,
   built from `fct_park_month` only. A dbt test ties each one exactly to `fct_park_month` (the total to the sum of
   its `operating_profit`, the counts to its rows), and `company_year` comes from the company-calendar logic in
   `int_statements__labeled`, never from Python. The export selects allowlisted columns in a fixed order and writes
   them as delivered.

## What was given up

- **Parquet in the browser, for now.** Gain: no DuckDB-WASM loader, no pinned extension file, two packages instead of
  four, and a page that builds and loads without WebAssembly. Cost: the page cannot filter or query in the browser;
  every view is fixed at build time, and NEXT 15 must replace the data path (below).
- **A rebuilt-only export.** The export could be rebuilt inside the gate and never committed. Gain of committing it: a
  served copy exists to tamper with and compare, and a reviewer sees the published numbers in the diff. Cost: both
  files must be regenerated with `make site-export` whenever the sample or a mart changes.
- **Live data sets.** The export reads only the committed sample. Gain: the gate and the page read the same data, so
  the comparison is exact. Cost: the page cannot show the rehearsal or company warehouse until NEXT 15.
- **Roll-ups computed in the export.** The first draft computed the total and the counts by SQL in the export step.
  Gain of the roll-up mart instead: every shown number is a dbt-tested mart column, as the guardrail requires. Cost:
  one more mart, one tie test and one unit test in this slice.

## Rejected alternatives

- **DuckDB-WASM now, as ADR 0021 states.** Rejected by the Gate 1 ruling for this slice: it needs the loader, the
  pinned extension and two more packages, all outside a one-number proof.
- **Eleventy reading the DuckDB file at build time through a Node DuckDB package.** It needs a dependency nobody
  approved and would read a warehouse file from site code, which ADR 0021 forbids (pages read exports, never a
  warehouse file).
- **Fetching the JSON from the browser at view time.** It adds a request the offline page-load rule must then guard,
  and the page check could not compare the numbers in the built HTML.

## Consequences

- The steel-thread page proves ADR 0015's export acceptance tests 1 and 2 in `make check` (a one-value change in a
  served export fails; a relation not on the allowlist fails), with Python tests on real temporary DuckDB files.
- Every number the page shows, except the cited game-calendar constant (see "Gate 2 rulings" below, point 4), is a mart column tied by a dbt test: each monthly bar after a park's first statement
  by the cash identity on `fct_park_month`, and every other number by the tie test on `obt_company_year_to_date`.
  Each park's first month has no earlier statement to reconcile, and the page and the trace doc say so.
- The published-number mapping and ADR 0015 acceptance tests 3 to 9 remain NEXT 15's.
- Gate 2 ruled the Makefile form: `site-export` keeps its own copy of the temporary-folder lines, held equal to the
  gate's by a test.
- Known limits, rejected as findings: the gate does not check that the chart's y channel reads the mart column (the
  drawn bars are judged in a browser, because a render in the gate needs a new dependency no ruling grants), and the
  page check would not refuse an added untested number (page text and chart arithmetic are a review judgment).
- `npm ci` reports 9 known vulnerabilities, all in the dependency trees of `@11ty/eleventy` and `@observablehq/plot`
  (the base lockfile held only `typescript` and `@openrct2/types`). Eleventy runs only at build time on local files;
  only Plot and d3 are served with the page.

## Gate 2 rulings

The project owner ruled on these points of the steel-thread spec on 2026-10-13, all at the recommended default:

1. The roll-up mart is `obt_company_year_to_date`, one row per company year, the open year included. Gain: no clash
   with the design's planned closed-years-only `obt_company_year`. Cost: one more mart name that the marts slice (3c)
   must keep or fold into its planned company tables.
2. The year-to-date total column is named `operating_profit`, as `docs/CONVENTIONS.md` asks of a published column
   (named exactly as its catalog metric); its description says "summed over the months present so far". Cost: the same
   name means a month in one table and a year to date in the other; `months_present` carries the difference.
3. `months_checked` counts park-months. Cost: once a second park lands, "2 of 2 months" reads wrongly, and NEXT 6 (the
   two-park view) rewords the check line.
4. The 8 in "of 8 months" is page text, not a mart column, because it is the length of the game's company year (March
   to October, statement months 0 to 7), not a measured value. ADR 0015 `:62` limits the mart-column rule to results
   measured from the parks' data, and its build acceptance test 6 passes a game-calendar constant whose sentence cites
   its source. The sample note's month count and company year still come from `months_present` and `company_year`.
5. `fct_park_month` carries two columns beyond the Gate 1 list: `company_year` (reused from
   `int_statements__labeled`) and `months_since_previous_statement`, which gives the missing-month rule a column to
   test.
6. The headline shows the latest company year in the mart (the last row of the ordered export); the bars show every
   month. Cost: once a second company year exists, the bars span two years while the headline shows one, and NEXT 15
   decides the multi-year view.
7. The cash identity is a singular test at error severity, with one clause added to `docs/CONVENTIONS.md`; only
   `operating_profit`'s `source_models` and `reconciled_by` are repointed in the metric catalog; there is no
   `interest_costs` column (the mart carries `interest_usd`); the export package lives at
   `src/openrct2_analytics/showcase/`; `make site-export` reads only the committed sample; the template language is
   Nunjucks; the total is a headline above the chart; `make setup` switches to `npm ci --ignore-scripts`.

## What NEXT 15 must migrate

NEXT 15 keeps the allowlist, the comparison and the gate position, and replaces the data path:

1. **Writer:** `export write` writes Parquet for each allowlist entry, as ADR 0021 `:46` states, instead of JSON. The
   allowlist file, the `marts`-only rule and the refusal codes stay.
2. **Comparison:** `export check` compares the served Parquet with the rebuilt rows by the same row count and hash of
   the rows in served order; `tests/test_showcase_export.py` keeps its cases with Parquet fixtures.
3. **Page data path:** the page reads the Parquet through ADR 0021's hand-written DuckDB-WASM loader and the pinned
   extension, and drops the embedded JSON element, the month table's rows (`#park-month-table`) and the Eleventy global data files.
4. **Page check:** the static check of embedded numbers and of the month table (`#park-month-table`) is replaced by ADR 0021's offline page-view test in a browser,
   which compares rendered values with the export.
5. **Packages:** NEXT 15 adds the two ADR 0021 packages this slice did not, `@observablehq/inputs` 0.12.0 and
   `@duckdb/duckdb-wasm` 1.33.1-dev57.0, at exact pins with `--ignore-scripts`.
6. **Page text:** the headline, check line, sample note and the month table's caption, headers and first-month mark (`#park-month-table`) move from `site/index.njk` into story files in
   `docs/showcase/story/`, the single source of text ADR 0021 carries forward.
7. **Mapping and chart rules:** the published-number mapping and its test (ADR 0015 build acceptance test 3), the
   chart specs with their source check (test 4) and tests 5 to 9 cover this page too.
8. **The roll-up mart:** `obt_company_year_to_date` is either kept as the open-year table or folded into 3c's
   planned `obt_company_month` and `obt_company_year` in the same change that repoints its allowlist entry; the
   planned `obt_company_year` holds closed years only, so it cannot serve the open year without a change to its
   design.
9. **Removal:** `site/_data/park_month.json`, `site/_data/company_year_to_date.json` and the JSON branch of the export
   module are deleted in the same change, so two data paths never live side by side.

Plot's `barY` stacks rows that share an x value, so once a second park lands each bar would draw a cross-park sum that
is no mart column; NEXT 6 (the two-park view) must split or facet the bars.
