# Spec: year totals per park and for the company, held back until every park closes its year

status: revised after spec review round 1 · 2026-10-18 · amended 2026-10-21 (same-season incomplete rule, D2) · branch `feat/portfolio-view` from `develop` `81e9be0` ·
contract map `docs/ai-dlc/contracts/next6-portfolio.md` · roadmap: the portfolio view across parks (NEXT item 6 in
`docs/ai-dlc/roadmap/park-company.md`) · review record `docs/ai-dlc/ledger/next6-portfolio.md` · the Gate 1 record
(the scope interview of 2026-10-18) is kept outside version control; every line used here is restated under "Rulings".

## Bottom line

This work adds two year tables and the check that guards them, proves them on a temporary two-park copy of the sample,
then moves the site onto them.

- **Two new tables, sums and counts only.** `obt_park_year` has one row per park per company year; `obt_company_year`
  has one row per closed company year.
- **A company year appears only once it has closed:** every park expected in it (from its first full company year)
  has all eight monthly statements. A park's partial first season never holds a year open and is flagged as partial.
- **A blocking test fails real-data builds** when a park has moved on, to a later year or to a later month of the same
  year, while still missing a statement it owes. It only warns on `ci` and on `dev` over the committed sample.
- **A test runs two parks through the whole stack** on a temporary two-park copy of the one-park sample, through dbt
  the site export and the rendered page; planted faults turn the blocking test and the cross-park date check red.
- **The site switches tables.** `obt_company_year_to_date` is deleted; the site lists every park-year and every closed
  company year, labelled "not yet reconciled", and loses its company headline on the sample.
- **No contract, Makefile, profile or plugin change, and no new dependency.** `make check` is green after every wave.

## Rulings

Gate 1 decisions of 2026-10-18, restated unchanged:

1. Build `obt_park_year` (one row per park per company year) and `obt_company_year` (one row per company year),
   storing sums and counts, never averages of averages (`docs/CONVENTIONS.md:108`).
2. A year-end close register derived in dbt from each park's `company_start_year` in the current registry: no seed and
   no new contract column. A park is expected in every company year from its first full company year onward.
3. A park's partial first season (it joined mid-season) is exempt from the close and published flagged as partial.
4. A blocking test keeps company-year rows, and anything published from them, out until every expected park has a
   complete kept year (all eight monthly statements on the kept timeline, per `docs/requirements-brief.md:316-319`).
   Severity: error on the real-data targets, warn on `ci` and on `dev` over the committed sample
   (`docs/CONVENTIONS.md:115`, ADR 0031 pattern), because the committed sample has one park and only three months.
5. A cross-park company-date check, defined from ADR 0023 (one company calendar shared by all parks).
6. `obt_company_year` replaces `obt_company_year_to_date`: delete the old model and its tests, switch
   `site/exports.toml`, re-export `site/_data/` with `make site-export`, update exposures, the page check's one-park
   rule, the site copy, the `rows_on_sample` entries and the `docs/CONVENTIONS.md:117` list, and the expected-row table.
7. Two-park dbt unit-test fixtures for the new models, and a planted test: hide one park-month and the close test must
   turn red.
8. Published year figures carry a "not yet reconciled" label (v1 guardrail, 2026-10-18: reconciliation reports move
   to v1.1).

Goal and scope rulings: the goal is "showing two parks on one company calendar running through the whole data stack"
(2026-10-18); v1 scope was cut so the multi-park setup is visible sooner (2026-10-18). A separate feature builds the
two-park capture command; that command also writes Park 2's registry delivery for the rehearsal data set.

## Goal

A reader sees each park's year and the company's year side by side, and a company year total never silently misses an
expected park. Two-park unit fixtures prove the arithmetic; a temporary two-park copy of the sample proves the path from
Parquet through dbt to the site export. Real two-park rehearsal data arrive with the separate capture command.

## Every Gate 1 line, and where it lands

| Gate 1 line | Lands in |
|---|---|
| 1 Two year tables, sums and counts | R2, R3; tickets T4 (park-year table), T5 (company-year table) |
| 2 Close register from `company_start_year`; expected from the first full year | R1, D4; ticket T2 (the register model) |
| 3 Partial first season exempt and flagged | D4, R1 (status `partial_first_season`, never blocking), R2 (`is_partial_first_season`), R3 (`parks_partial_first_season`); unit tests U1, U6 |
| 4 Blocking test, severity by target | D1 (open years never enter the table), R4 (the test); tickets T1 (shared severity macro), T3 (close test and its pytest cases) |
| 5 Cross-park company-date check | R6 checks 4 and 5, D14; ticket T7 (the check, the two-park copy and its planted disagreements) |
| 6 Replace the year-to-date table | R7, R8; tickets T4 and T5 (exposures), T8 (site switch and deletion), T9 (documents) |
| 7 Two-park fixtures and the planted test | R1 to R3 unit tests (U2 is the hide at register level); R4 pytest case "planted hide" (the hide through the singular test); ticket T10 (two parks through the export) |
| 8 "not yet reconciled" label | R2 and R3 descriptions, R7 page copy; tickets T4, T5, T8 |

## Spec decisions

Each decision is made inside the Gate 1 rulings and names the alternative it rejects.

- **D1. `obt_company_year` holds closed years only.** Gain: Gate 1 decision 4 holds by construction, because no open
  year can be published or exported. Cost: the committed sample yields 0 rows and the site loses its company headline.
  Rejected: rows for open years with an `is_closed` column, which would publish unclosed company totals.
- **D2. The test fails only on a gap that more play cannot fill.** A park-year is *incomplete* when it lacks a
  statement it owes and either the park already has a kept statement in a later company year, or a later month of the
  same company year is kept (a gap before a kept month). October of year Y arrives on 1 March of Y+1
  (`docs/requirements-brief.md:316-319`), so later play can no longer fill the gap. A year still in progress, whose
  only missing months come after its last kept month (or that has no kept month yet), is *open*: D1 keeps it out and it fails nothing. Gain: mid-season real-data builds pass. Cost: a
  never-captured park and a trailing lost statement keep a year open without a failure (Open points). Rejected:
  failing on every unclosed year, which would stop every mid-season `make transform` and `make publish`.
  Amended 2026-10-21: the same-year clause (a gap before a kept month) is new. Statements arrive in month order, so a
  later kept month proves the missing one was lost, and the alarm fires in the same season instead of after the next
  year's first statement (review finding L2-4 of the portfolio view; approved by the project owner 2026-10-20). Cost:
  one rule term in the register, and a real capture with such a gap now fails the blocking test on error targets.
  Gain, stated narrowly: a month missing between two kept statements already fails the exact cash-change test
  (`tests/dbt/assert_park_month_cash_change_reconciles_exactly.sql`) on every target; this rule adds the leading-gap case
  (months missing before the park's first kept statement in a full season) and the register's `incomplete` status.
- **D3. "Moved past" is read from kept statements, not kept days.** Gain: no false failure on 1 March, when the day and
  October's statement arrive together. Cost: a lost October is reported when March's statement arrives on 1 April.
- **D4. A partial first season is exempt as a whole.** The first captured day is the park's earliest
  `stg_park_snapshot` row on any timeline (ADR 0031 decision 3). A park-year is a partial first season when it is the
  park's `company_start_year`, the first captured day falls in that company year, and the first month that day can
  report is 1 (April) or later. That month is the day's game month, except that a first captured day 1 of game month m
  (m of 1 or more) carries month m - 1's statement, so the first reportable month is m - 1: the plugin's day-1 callback
  delivers the previous month's statement, the same reason given below for 1 April. That row gets status `partial_first_season` whatever months are missing; it is never `incomplete` or `open`
  and never holds its company year open. The park is expected from the next company year. A first captured day in game
  month 0 is a full season, because March's statement arrives on 1 April and can still be captured: the sample starts
  on 7 March and owes all eight. A first captured day 1 of month 1 is also a full season (day 1 of April carries
  March's statement); day 2 of month 1 is partial. Gain: carries ruling 3 as written. Cost: a statement lost during a partial season is
  never flagged; it shows only in the row's `missing_statement_months`. Rejected: the earlier reading, in which the
  partial park still owed every month from its join month and could block the year; the review found it departs from
  ruling 3.
- **D5. The register owns every close rule.** Status per park-year and the closed flag per company year live in one
  intermediate model. The two marts and the test read them and re-derive nothing. Gain: one definition of "closed".
  Cost: the marts depend on an intermediate model whose logic only its unit tests prove.
- **D6. The register spans each park's start year to the latest company year with a kept statement.** Gain: a missing
  whole year is visible as a row with 0 statements. Cost: the span is set by the furthest-ahead park.
- **D7. One severity macro serves both target-dependent tests.** The ADR 0031 expression moves from the missing-day
  test into `macros/sample_warn_severity.sql`, and both tests call it. Gain: one definition (`docs/CONVENTIONS.md:121`
  allows a macro for logic applied identically everywhere). Cost: a refactor of a shipped test, and a macro may not
  render inside a parse-time `config()`; the missing-day pytest proves it does, and if not, T1 stops and reports.
- **D8. The site lists every park-year and every closed company year.** See R7. Gain: the page picks no "latest" year,
  so it compares and computes nothing (ADR 0026); two parks and several years need no extra logic. Cost: the park-year
  table grows by one row per park per company year, and the sample page has no single headline figure. Rejected:
  showing only the latest year's park lines, which needs an equality test in the template or a mart column that exists
  only for the page.
- **D9. Keys.** `obt_park_year` is keyed on `park_year_key` = `park_id|game_year`, built from the game year, so a
  registry correction does not change keys (`docs/CONVENTIONS.md:106`). `obt_company_year` is keyed on `company_year`,
  as the old table was. The register is keyed on `park_id|company_year`, because an expected year may have no game data.
- **D10. Publish floors.** `meta.expected_min_rows` is 0 for `obt_company_year`, so a data set with no closed year can
  still publish. It is 1 for `obt_park_year` and for the register. Precedent: the 2026-10-14 floor ruling for
  `guest_refused` (roadmap, the guest staging item). Rejected: a floor of 1, which would refuse every company-data
  publish until the first season closes.
- **D11. A company year closes only when at least one expected park is `complete`.** Gain: no company year is
  published from partial seasons alone, whose totals would keep changing with every capture. Cost: if the company's
  first year has only a park that joined mid-season, that year never appears in `obt_company_year` (it stays visible
  in `obt_park_year`). Rejected: closing a year with no expected park, which the rulings do not address.
- **D12. The two-park proof is a temporary copy built at test time** (R4 describes the helper). Gain: the singular
  tests, the year marts and the export run on two parks with no committed data change, no contract change and no new
  dependency (duckdb, `shutil` and `csv` are already used). Cost: about five extra dbt builds in the pytest suite, and
  the second park is a relabelled copy, not independent play. Rejected: a two-park committed sample (Gate 1 out of
  scope), and synthesizing five more months of kept statements so a year could close (it would need kept-timeline
  sessions, consistent cash and a snapshot for every day; too fragile for a fixture).
- **D13. Close-test failure rows say which rule failed and give a hint.** Each row carries `failure_kind`
  (`park_year_incomplete` or `company_year_not_closed`) and `hint`. Gain: a reader can tell a lost statement from a
  registry entered too early (review issue R7a) without opening the register. Cost: two columns that only this test
  uses.
- **D14. Planted disagreements edit a built table in the pytest**, because dbt unit tests attach only to models, not
  to singular tests: build the two-park copy, change one stored row, run only the singular test. R6's plants and R4's
  second branch (which `obt_company_year` cannot trip by construction) use it. Gain: the singular test itself is proven
  red on two parks. Cost: it proves the check, not a model fault that would cause it. Rejected: moving the comparison
  into a new model so it can carry a unit test, which adds a model that exists only for testing.
- **D15. Each ticket that adds an `obt_` model adds it to `operating_profit_page` in `models/marts/exposures.yml`**,
  because `scripts/check_exposures.py` fails an `obt_` model with no exposure; the old reference stays until T8. Gain:
  `make check` stays green after every wave. Cost: for two waves the exposure names tables the page does not read yet.

## Requirements

### R1. Close register: `models/intermediate/int_park_years__year_close.sql` and `.yml` (Gate 1 decisions 2, 3, 7)

- **Grain:** one row per expected park per company year. **Key:** `park_year_close_key` = `park_id|company_year`.
- **Inputs:** `int_park_registry__current` (`park_id`, `company_start_year`), `fct_park_month` (kept statements:
  `park_id`, `company_year`, `statement_month`), `stg_park_snapshot` (first captured day, any timeline), and
  `int_park_years__registry_mapped` to find the company year of that day's game year, so the register never
  re-implements the company-year formula.
- **Rows:** for each registered park, every company year from its `company_start_year` to the latest `company_year` in
  `fct_park_month` across all parks (D6). A park whose start year is later than that has no rows.
- **Columns:**
  - `first_captured_company_year`: the company year of the first captured day; null when the park has no snapshot.
  - `is_partial_first_season`: the D4 rule.
  - `first_reportable_month`: the first game month the park could report that year; for a partial first season, the
    first captured day's game month, less one when that day is day 1 of a month of 1 or more (D4); else 0.
  - `statements_expected` (8 minus `first_reportable_month`) and `statements_kept` (distinct kept statement months of
    the year, so it ties to `obt_park_month`).
  - `missing_statement_months`: months from `first_reportable_month` to 7 with no kept statement, ascending,
    comma-separated, empty when none. For a partial first season it is shown, not owed.
  - `has_later_statement` (the park has a kept statement in a later company year; D3),
    `has_kept_month_after_gap` (a kept month of this year comes after the earliest missing reportable month; false when
    nothing is missing; added 2026-10-21, D2), `close_status`,
    `is_company_year_closed`, plus `park_id` and `company_year`.
- **`close_status`:** `partial_first_season` (D4, whatever is missing); otherwise `complete` (all eight months
  present), `incomplete` (a month missing and either `has_later_statement` or `has_kept_month_after_gap`), or `open` (a month
  missing, no later statement, and no kept month of the year comes after a missing reportable month; this includes a
  year with nothing kept).
  A park with no snapshot is never partial, so its rows are `open` until it has statements.
- **`is_company_year_closed`** is true for every row of a company year exactly when no row of that year is `open` or
  `incomplete` and at least one row is `complete` (D11).
- **Unit tests (two or more parks, `format: sql`, distinct values per same-typed column):**
  - **U1 closes with a partial park:** `park_a` (start 2000, origin 9) and `park_b` (start 2000, origin 4) each have
    months 0-7 of 2000 and month 0 of 2001; `park_c` (start 2000, origin 1, first captured day game year 1, month 3)
    has months 3 and 4 of 2000 only. Expected: `park_a` and `park_b` 2000 `complete`; `park_c` 2000
    `partial_first_season`, `statements_expected` 5, `statements_kept` 2, `missing_statement_months` `5,6,7`; 2000
    closed. In 2001 all three are `open` (`park_c` is expected from 2001); 2001 not closed.
  - **U2 the hide:** U1 with `park_b`'s month 4 of 2000 removed. Expected: `park_b` 2000 `incomplete`,
    `missing_statement_months` `4`; 2000 not closed.
  - **U3 gap before a kept month:** U2 with `park_b`'s 2001 statement also removed, so no later-year statement
    exists. Expected (changed 2026-10-21 from `open`): `park_b` 2000 `incomplete`, because month 4 is missing and months
    5 to 7 are kept; 2000 not closed. `park_a` 2001 (month 0 kept, months 1 to 7 missing) and `park_b` 2001 (nothing
    kept) stay `open`: only trailing months are missing.
  - **U4 lost first statement:** `park_d` (start 2000, origin 9, first captured day game year 9, month 0, day 2) has
    months 1-7 of 2000 and month 0 of 2001. Expected: 2000 `incomplete`, not partial, `missing_statement_months` `0`.
  - **U5 registry start year too early:** `park_e` (start 1999, origin 8, first captured day game year 9, month 0)
    has months 0-7 of 2000 and month 0 of 2001. Expected: a 1999 row, `incomplete`, `statements_kept` 0,
    `first_captured_company_year` 2000, not partial; 2000 `complete`.
  - **U6 partial parks alone:** `park_f` (start 2000, first captured day month 2) has months 2-7 of 2000. Expected:
    `partial_first_season`; 2000 not closed (D11).
  - **U7 never captured:** `park_a` as in U1 plus `park_g` (start 2000, no snapshot, no statement). Expected: `park_g`
    2000 and 2001 `open`, `first_captured_company_year` null; 2000 not closed.
  - **U8 staggered start years:** `park_h` (start 2000, origin 9) and `park_i` (start 2001, first captured day game year
    8, month 3, so before its start year) each have months 0-7 of 2001, `park_h` also of 2000, and month 0 of 2002.
    Expected: `park_h` has rows from 2000, `park_i` from 2001 and not partial; 2000 and 2001 closed, 2002 not.
  - **U9 partial season limited to the start year:** `park_j` (start 2000, first captured day game month 1, the
    boundary) has months 1-7 of 2000; `park_k` (start 1999, first captured day in 2000, month 3) has months 3-7 of 2000.
    Expected: `park_j` 2000 `partial_first_season`, `statements_expected` 7, `has_kept_month_after_gap` false (month 0
    is missing but lies before `first_reportable_month` 1, so it cannot set the boolean); `park_k` 1999 `incomplete` and 2000
    `incomplete` (changed 2026-10-21 from `open`: months 0 to 2 are missing and months 3 to 7 are kept, and its start
    year 1999 means 2000 is not a partial season), neither partial.
  - **U10 gap year and first day across game years:** `park_l` (start 2000) has months 0-6 of 2000 and month 0 of
    2002, none in 2001; `park_m` (start 2000) has snapshots in game year 10 month 0 and game year 9 month 3. Expected:
    `park_l` 2000 and 2001 `incomplete`; `park_m` first captured day is game year 9 month 3, so 2000 is
    `partial_first_season`.
  - **U11 gap before a kept month versus only trailing months missing (new 2026-10-21):** one test with two parks,
    neither with a statement in 2001. `park_n` (start 2000) has months 0, 1, 3 and 4 of 2000 kept. `park_o` (start 2000)
    has months 0 to 4 of 2000 kept. Expected: `park_n` 2000 `incomplete`, `missing_statement_months` `2,5,6,7`,
    `has_later_statement` false, `has_kept_month_after_gap` true; `park_o` 2000 `open`, `missing_statement_months`
    `5,6,7`, `has_kept_month_after_gap` false; 2000 not closed.
  - **U11b partial first season with a gap stays partial (new 2026-10-21):** `park_q` (start 2000) has a first captured
    day of game year 9, month 3, day 2, and kept statements for months 3 and 5 of 2000. Expected: `park_q` 2000
    `partial_first_season`, `missing_statement_months` `4,6,7`, `has_kept_month_after_gap` true. A second park, `park_r`
    (first captured day game year 10, month 0, day 1; months 0 to 7 of 2000 kept), expects 2000 `complete`,
    `missing_statement_months` empty, `has_kept_month_after_gap` false; 2000 is closed.
  - **Expectations that change:** exactly two existing rows flip from `open` to `incomplete`: `park_b` 2000 in
    `models/intermediate/int_park_years__year_close.yml` (month 4 missing, months 5 to 7 kept; this is U3) and `park_k`
    2000 in `models/intermediate/int_park_years__year_close__unit_tests.yml` (U9). The yml test holding `park_b`,
    `int_park_years__year_close_keeps_a_year_open_without_a_later_statement`, is renamed to say what it proves, and its
    `open` rows (`park_a`, `park_b` and `park_c` in 2001) still prove the open case. No other expectation changes.
- **Kept within expected:** `tests/dbt/assert_register_kept_within_expected.sql` returns a row for any register row
  with `statements_kept` above `statements_expected`, so a page can never read "8 of 7".
- **Day-1 unit tests:** a first captured day 1 of month 1 is `complete` (8 of 8, year closed); day 1 of month 3 is
  `partial_first_season` owing months 2 to 7. The earlier fixtures for `park_c`, `park_f` and `park_k` moved their
  first captured day from day 1 to day 2, with no change to any expected row.
- `rows_on_sample` 1 (the sample park, 2000, `open`); `meta.expected_min_rows` 1; descriptions state unit and clock
  (company date, year).

### R2. `models/marts/obt_park_year.sql` and `.yml` (Gate 1 decisions 1, 3, 7, 8)

- **Grain:** one row per park per company year with at least one kept statement. **Key:** `park_year_key` (D9).
- **Inputs:** `obt_park_month` (sums and counts per park-month), `fct_park_month` (`net_cash_change_usd`, joined on
  `park_month_key`), the register (status columns). At most three concepts (`docs/CONVENTIONS.md:119`).
- **Columns:** `park_year_key`, `park_id`, `company_year`, `game_year`, `first_statement_company_date`,
  `last_statement_company_date`, `statements_kept`, `statements_expected`, `close_status`, `is_partial_first_season`,
  `is_company_year_closed`, `months_checked` (kept statements with a net cash change), then the measure columns of
  `obt_park_month` under the same names: each sum is summed, and each ratio is recomputed from the year's sums with
  the month model's formula (`docs/CONVENTIONS.md:108`, `:114`).
- The model description and every money column description say "not yet reconciled" (ruling 8: the table is published
  by `make publish`).
- Enforced contract, money `decimal(18,2)` (`:110`); `rows_on_sample` 1; `meta.expected_min_rows` 1.
- **Unit test:** two parks with different origins in one company year, two months each with different
  `operating_days`. Expected: sums per park, `average_park_rating` = summed `park_rating_sum` / summed
  `operating_days` (not the mean of monthly averages), `months_checked` counts non-null net cash changes, and status
  columns are carried from the register.

### R3. `models/marts/obt_company_year.sql` and `.yml` (Gate 1 decisions 1, 3, 4, 7, 8)

- **Grain:** one row per closed company year (D1). **Key:** `company_year`.
- **Input:** `obt_park_year` only, rows where `is_company_year_closed`, including `partial_first_season` rows.
- **Columns:** `company_year`, `parks_reporting`, `parks_partial_first_season`, `statements_kept` (park-months),
  `months_checked` (park-months, summed across parks, so its unit is park-months and not months), then the measure
  columns of `obt_company_month` under the same names, summed from park-years, with
  each ratio recomputed from summed sums.
- The description says "not yet reconciled" and that a closed year's totals still change while a park in its partial
  first season reports more months.
- Enforced contract; `rows_on_sample` 0, filled by a data set with a closed year (the rehearsal data set once a park
  has a complete year; ADR 0023 `:22-26`); `meta.expected_min_rows` 0 (D10).
- **Unit test:** a closed 2000 with `park_a` and `park_b` (different `operating_days`) gives one row with
  `parks_reporting` 2 and day-weighted averages. A closed year that includes a `partial_first_season` park gives
  `parks_partial_first_season` 1 and includes its sums. Rows of an unclosed 2001 give no row.

### R4. Close test: `tests/dbt/assert_every_expected_park_closes_its_company_year.sql` (Gate 1 decisions 4, 7)

- **Rows returned:** register rows with `close_status = 'incomplete'` (`failure_kind` `park_year_incomplete`), plus
  every `obt_company_year` row whose year the register does not mark closed (`company_year_not_closed`). Each row has
  `failure_kind`, `park_id` (null for the second kind), `company_year`, `statements_kept`, `statements_expected`,
  `missing_statement_months` and `hint` (D13). `partial_first_season` and `open` rows are never returned.
- **Hint:** when `company_year` is earlier than `first_captured_company_year`, the hint says the registry start year
  is earlier than the park's first captured day, which most likely means the registry row was entered wrong and needs
  a corrected delivery (ADR 0023). Otherwise it names the missing months and says those before the last kept statement of the year, or all of them once a later year has a statement, are lost.
- **Severity:** `config(severity=sample_warn_severity(), store_failures=true)`: warn on `ci` and on `dev` over the
  committed sample, error elsewhere (D7; ADR 0031 decision 4). The header comment states this, the scope and the hint.
- **Pytest cases** in the two-park pytest (R4 and R6 share it; golden path `tests/test_dbt_missing_day.py`). The
  helper of D12 builds the copy:
  - **The copy:** every `v1/*.parquet` file of the committed sample gets its rows appended again with `park_id` set to
    a second park ID in the sample's format, and `session_id`, `event_id` and every string column naming a save given
    a fixed suffix. A new registry file in the copy, dated after the committed one, registers the second park with
    `company_start_year` 2001 and `game_year_origin` 9 (the contract's columns, `data_set` `rehearsal`), so the second
    park's game year 9 is company year 2001 and the first park's is 2000. The committed sample is never written. If a
    dbt source also reads `audit/`, the helper suffixes its session IDs the same way. Every case first asserts that
    `fct_park_month` holds three kept statements for each park, so a copy that built wrongly fails loudly.
  - **Base build, then a company year the register has not closed** (`dev` over the copy, so error severity): after
    `dbt run`, the close test alone gives PASS. Then insert a row for company year 2000 into the built
    `obt_company_year` (schema read from the manifest) and test again. Expected: FAIL, a non-zero exit, and one stored
    row of kind `company_year_not_closed` for 2000.
  - **Planted hide:** in the copy, remove the first park's statement of game year 9, month 1 from
    `finance_month.parquet`, and move its statement of game year 9, month 2 to game year 10, month 0 (the statement
    year and month and the game-date columns change; `event_id`, `session_id` and `seq` stay, so it stays below the
    session's cut and kept, per `macros/timeline_status.sql`). The case first asserts the moved statement is kept in
    `fct_park_month` (if it is not, the ticket stops and reports). Expected on `ci`: WARN, exit 0. Expected on the
    `rehearsal` target in the same project copy: FAIL, a non-zero exit. The stored row is `park_year_incomplete`
    for the first park, 2000, 1 of 8, with month 1 in `missing_statement_months`; the base build's register row for
    that park-year lists `3,4,5,6,7`, so month 1 is the hide. No row names the second park.
  - **Committed sample on `ci`:** PASS (the gate's own run would only show a WARN as a warning).
  - **Severity by parse:** the manifest records `warn` for `ci` and for `dev` over the committed sample, and `error`
    for `dev` over another folder and for `rehearsal`.
- **What the planted hide does and does not show.** On a three-month sample, any later statement leaves months 3 to 7
  missing, so the year would be `incomplete` even without the hide. The proof that the hide itself is caught is month 1
  in the failure row, and U2 proves that a hide alone turns an otherwise complete year `incomplete` at register level.
  In a full `dbt build` of the planted copy, `assert_park_month_cash_change_reconciles_exactly` also fails (a gap
  between two kept statements), and the missing-day test is expected to fail too (no snapshot in the moved statement's
  month). That is expected. The pytest builds with `dbt run` and tests only the close test, as the golden path does,
  and asserts the close test's own status: a failing error-severity test shows as `FAIL` in dbt's results.
- Partial parsing is disabled, as in the missing-day pytest. Runs select `+assert_every_expected_park_closes_its_company_year`.

### R5. Exact ties (identities at error severity, `docs/CONVENTIONS.md:111`)

- `tests/dbt/assert_obt_park_year_reconciles_exactly.sql`: each `obt_park_year` row equals its own aggregate of
  `obt_park_month` on every sum column and `statements_kept`, and `months_checked` equals its count over
  `fct_park_month`. It uses a full outer join, so a year on one side only fails.
- `tests/dbt/assert_obt_company_year_reconciles_exactly.sql`: each `obt_company_year` row equals the sum of its
  closed `obt_park_year` rows, `parks_reporting` equals their count, and the set of company years equals the set the
  register marks closed.

### R6. Company-date check: `tests/dbt/assert_park_years_share_one_company_calendar.sql` (Gate 1 decision 5)

The check runs at error severity on every target, like the other company-date tests, with `store_failures=true`. Each
returned row names the check that failed (`failed_check`), the parks and the values. It returns a row when any of these
fails:

1. **Registry recompute at the published grain.** An `obt_park_year` row's `company_year` equals
   `company_start_year + (game_year - game_year_origin)` from `int_park_registry__current`.
2. **One season window.** `first_statement_company_date` and `last_statement_company_date` lie in 1 March to
   1 October of the row's `company_year`.
3. **One-to-one years.** No park has two rows for one `company_year`, or two company years for one `game_year`.
4. **One date, one company month, across parks.** Across all parks' kept statements in `fct_park_month`, one
   `statement_company_date` never maps to two different (`company_year`, `statement_month`) pairs.
5. **One company month, one date, across parks.** Across all parks, one (`company_year`, `statement_month`) pair never
   maps to two different `statement_company_date` values.

**What it catches.** Checks 4 and 5 are the cross-park assertions: two parks that share a company year (check 5) or a
statement date (check 4) and date one company month differently (a model dating one park's statements by hand or from a
superseded registry row, or one park's month off by one).
Checks 1 to 3 catch a mart grouped on the wrong year column or reading a superseded registry row (ADR 0023 decision 8),
a date outside its season, and duplicate current registry rows. With R1's "complete means months 0 to 7", checks 4 and
5 imply every complete park in a closed year has the same eight statement dates, so no separate closed-year comparison
is needed. **What it cannot catch.** A registry row that is wrong but self-consistent: that park's dates all shift into
another valid company year and every check agrees (ADR 0023, "What was given up"). With one park, checks 4 and 5 reduce
to per-park checks. Checks 4 and 5 compare parks only where they share a company year or a date: two parks in separate
company years with a self-consistent shift pass. "Exactly one managed park per company year" is not checked (managed labels are out of scope).
Checks 2, 4 and 5 guard the `company_date` formula against a future model change: every statement date is
`company_date(company_year, statement_month, 1)`, a one-to-one function, so they cannot fire on data the pipeline
builds today. The pytest plants prove the checks by editing a built table (D14).

**Pytest cases** (D14), in the two-park pytest:

- **Base build:** `dev` over the copy. Expected: R6 PASS; `obt_park_year` has two rows, one per park (company years
  2000 and 2001); the register has three rows (first park 2000 and 2001, second park 2001, all `open`).
- **Planted disagreement, check 4:** on a copy of the built warehouse, set the second park's stored
  (2001, month 0) statement date in `fct_park_month` to 1 March 2000; run R6 alone. Expected: FAIL, a row with
  `failed_check` 4 naming both parks.
- **Planted disagreement, check 5:** on a fresh copy, set that row's `company_year` to 2000, leaving its date. Expected:
  FAIL, a row with `failed_check` 5 naming both parks.

### R7. Site switch (Gate 1 decisions 6, 8)

- **`site/exports.toml`:** replace the `company_year_to_date` export with `company_year` (`marts.obt_company_year`:
  company year, parks reporting, parks in a partial first season, statements kept, months checked, operating profit;
  `order_by = ["company_year"]`) and add `park_year` (`marts.obt_park_year`: key, park, company year, statements kept
  and expected, close status, partial flag, months checked, operating profit; `order_by = ["company_year",
  "park_id"]`). Delete `site/_data/company_year_to_date.json` and regenerate with `make site-export`, which writes
  `site/_data/company_year.json` and `site/_data/park_year.json`.
- **`site/index.njk`** (the page computes nothing, ADR 0026; it loops over rows in export order and picks no year):
  - **Closed company years table:** one row per `company_year.json` row (company year, parks reporting, partial first
    seasons, park-months checked, operating profit); the column is headed "Park-months checked" because the company
    row sums park-months across parks (R3). With zero rows it shows one sentence: no company year has closed yet. The
    page also states the close rule in one sentence: a year closes when every park expected in it has all eight monthly
    statements, March to October, a park's partial first season does not hold a year open, and at least one expected
    park must also be complete (D11).
  - **Park-years table:** one row per `park_year.json` row (company year, park ID, statements kept of expected, months
    checked, operating profit, and the status in words: complete, not closed, incomplete, or partial first season).
    The word for `complete` is "complete", not "closed": a complete park-year can sit in a company year that has not
    closed, and only a company year closes.
  - **Checked months:** each table's checked-months column comes from that row's own `months_checked`; one sentence
    without a number explains the check (operating profit plus capital spending plus interest equals the change in
    cash less loan, and each park's first month has nothing to check against; the sentence is plural, as the page may
    show several parks). No sentence sums across rows.
  - **Captions, units and clock:** each year table has a fixed caption, and each year heading carries "clock: company
    year" and its unit, so invariant 3 (every metric names its unit and its clock) holds for both tables.
  - **"not yet reconciled"** in the header of every year money column.
  - **Sample note:** it states no park count. It says the sample is the parks listed in the park-years table, three
    headless sessions with no player, observational.
  - The month chart and month table are unchanged; they already mark each park's first month.
- **`src/openrct2_analytics/showcase/page_check.py`** replicates the page: every `company_year.json` row matches a row
  of the closed-years table, and zero rows require the empty-state sentence; every `park_year.json` row matches a row of
  the park-years table; every year money header carries "not yet reconciled". The one-park rule (`:350-361`) becomes:
  every distinct `park_id` in `park_year.json` and in `park_month.json` appears in the park-years table, and the page
  text, table captions included, contains no park count ("one park" or a number followed by "park" or "parks"). That
  pair is what stops a page from claiming one park when two are present. The check also pins both year-table captions
  (as the month table's caption is pinned), requires "clock: company year" in both year headings, pins the close
  sentence with its at-least-one-complete clause, the "complete" status word, the plural first-month sentence and the
  "Park-months checked" header. The pinned copy (captions, headers, status words, the close rule) lives in
  `src/openrct2_analytics/showcase/page_check_text.py`, which keeps `page_check.py` under 500 lines.
  `tests/page_check_support.py`, `tests/test_showcase_page_check.py` and `tests/test_showcase_export.py` follow, with
  cases for two parks over two years, a page that says "one park" while two parks are present (fails), a park missing
  from the park-years table (fails), a missing "not yet reconciled" (fails) and zero closed years with the empty-state
  sentence (passes).
- **Deletions:** `models/marts/obt_company_year_to_date.sql`, its `.yml`, its tie test, and its reference in
  `models/marts/exposures.yml` (T4 and T5 already added the new tables, D15). `ARCHITECTURE.md`'s path span for the
  deleted JSON file (`:229`) names the two new files in the same change, because `scripts/check_docs.py` fails a path
  that does not exist; T9 rewrites the paragraph.
- **Two parks through the export (T10):** a pytest case builds the two-park copy on `dev` through `obt_company_year`,
  runs `python -m openrct2_analytics.showcase.export write` on that warehouse into a temporary served folder, and
  asserts `park_year.json` has two rows naming both parks and `company_year.json` has zero rows. The test then renders
  the site from those served files (`npm run site:build` with a temporary input and output folder) and runs the page
  check on the built page, so a template that drops a park fails here; the proof reaches the final rendering step, not
  only the export. The copy's parks sit
  in different company years, so no company year closes; closed-year arithmetic across parks stays proven by R3's unit
  test.
- **Render over every status word:** that sample has no closed company year and no `complete` park-year, so a second
  pytest case (no dbt) renders the real template from synthetic served files that hold a closed year and one park-year
  of each status, and runs the page check on the result. It is what makes a template change to the closed-years table
  or to the word for `complete` fail the gate.

### R8. Documents (a change that invalidates a document updates it in the same change)

- **Pre-step:** merge `origin/develop` into the branch first. The ride-weather branch edits `ARCHITECTURE.md`,
  `CHANGELOG.md` and `docs/CONVENTIONS.md`, and adds ADR 0034; it merges first.
- `docs/CONVENTIONS.md:117`: in the `rows_on_sample` list, drop the old model and add `obt_park_year`,
  `obt_company_year` and `int_park_years__year_close`. At `:115`, name the shared severity macro.
- The expected-row table, `docs/ai-dlc/reports/dbt-design--findings.md` section 6.2 (`:171 and :186`): the same three rows,
  with their counts and the real data that fills the 0.
- `docs/ai-dlc/reports/dbt-design--marts.md`: a dated note (2026-10-18) marks the superseded parts: the old
  year-to-date table is replaced by `obt_company_year`, and `obt_park_year` holds every park-year with a status, not
  closed years only. Line 5's list of built marts names the two new tables.
- New ADR, number 0035 (0034 is taken by the ride-weather branch): "company years close from a register derived in
  dbt", recording Gate 1 decisions 2 to 4 and D1 to D4 and D11 with what was given up.
  `docs/adr/0026-build-time-json-for-the-first-site-page.md` gains a status line "Superseded in part by ADR 0035" (its
  roll-up-mart decision); its body is not edited.
- `ARCHITECTURE.md` (on this base `:29-33`, `:227-239`, `:491`), `models/overview.md` (`:23`, `:51`),
  `docs/showcase/trace-operating-profit.md`, `CHANGELOG.md`.
- The dated notes call the old model "the year-to-date table", so Verify-by step 6 stays empty. The roadmap is not
  edited (the scope-cut branch already updates the across-parks item).

## Files

Every owned file is listed in the Tickets table. Not touched: `dbt_project.yml`, `contracts/`, `Makefile`,
`profiles.yml`, `publish_audit.py`, the plugin, `pyproject.toml`, `uv.lock`, the committed sample, the roadmap.

## Contracts touched and how each is regenerated

- **Data contracts (ODCS):** none. The registry contract keeps version 1.0.0 (Gate 1 decision 2); the pytest's second
  registry row uses its existing columns. **dbt model contracts:** two new enforced contracts; one removed.
- **Served site files:** regenerated by `make site-export` and committed; `make check` compares them with a fresh build.
- **Exposures:** `operating_profit_page` gains the new tables in T4 and T5 and loses the old one in T8.
- **Publish audit:** unchanged; it audits the register and `obt_park_year` against the registry because both carry
  `park_id` (contract map section 1).

## Test seams

dbt unit tests on fixed two-park inputs; the singular tests on the `ci` sample build in `make check`; the two-park
pytest (D12, D14) with real dbt per target in a temporary project copy; page and export pytests on hand-written JSON
(`tests/page_check_support.py`).

## Constraints

- **Repo invariants.** None is touched. No event field changes (1, 6); the pytest's copy keeps `seq` gap-free per
  session except where a planted case removes a row on purpose, as the missing-day pytest does. Raw captures are only
  read, and the planted copies live in a temporary folder (2). Year tables read `_usd` columns, and every column
  states unit and clock, with the clock "company date (year)" (3). No player-action data is read (4). No game files or
  private paths (5). Site copy states its sample and "observational" (7). The plugin is untouched (8).
- **CONVENTIONS rules** (`docs/CONVENTIONS.md`): tables only `:105`, keys `:106`, sums and counts `:108`, enforced
  contracts `:110`, identities at error `:111`, catalog names `:114`, severity by target `:115`, unit tests `:116`,
  `rows_on_sample` `:117`, descriptions `:118`, mart width `:119`, macros `:121`, no packages `:122`.
- **House rules:** no new dependency; files under 500 lines; delete the replaced code in the same change; no ticket
  loosens an assertion or adds a skip.

## Golden paths

Each ticket names its golden path in the Tickets table. The year marts follow `models/marts/obt_company_month.sql` and
`.yml` (sums across parks, two-park unit fixtures); the pytest follows `tests/test_dbt_missing_day.py` (Parquet
rewrite, run then test, status read per test, stored rows).

## Out of scope

Year-over-year metrics 30-37 (the next slice); region roll-ups; managed or autopilot park labels; a park-ID copy rule; a
two-park committed sample (the one-park sample is kept); the two-park capture command and its registry delivery (a
separate feature); reconciliation reports (v1.1); roadmap edits.

## Verify-by

Run from the worktree root after `make setup`. Each step lists its expected result.

1. `make doctor`: exits 0.
2. Unit tests, two-park fixtures:
   `uv run python -m openrct2_analytics.ingest.warehouse_guard --root warehouse warehouse/dev/dev.duckdb && uv run dbt
   build --profiles-dir . --target dev --select +obt_company_year +assert_every_expected_park_closes_its_company_year
   --indirect-selection cautious --vars "{parquet_root: data/sample/rehearsal}"`. Expected: U1 to U7 and the R2 and
   R3 unit tests PASS; the close test PASS with 0 rows on the sample.
3. The two-park pytest: `uv run pytest tests/test_dbt_two_parks.py -q`. Expected: every case of R4, R6 and R7's export
   case passes.
4. Sample counts (fresh `ci` build inside `make check`): register 1, `obt_park_year` 1, `obt_company_year` 0.
5. `make site-export && git diff --exit-code site/_data`. Expected: no diff once committed;
   `site/_data/company_year_to_date.json` absent.
6. Old name gone: `git grep -n "company_year_to_date" -- models site src tests scripts ARCHITECTURE.md
   docs/CONVENTIONS.md docs/showcase docs/ai-dlc/reports/dbt-design--findings.md docs/ai-dlc/reports/dbt-design--marts.md`.
   Expected: no output.
7. `make check`: exits 0.

## Definition of Done

- Every ticket acceptance criterion is met; Verify-by steps 1 to 7 give their expected results; `make check` is green
  after every wave; the old model, its test and its export are gone and no document describes them as current.

## Open points

No point changes a Gate 1 decision or a contract. These consequences are recorded for the project owner's awareness:

- **The sample page loses its company headline** (D1, D8): the closed-years table is empty until real data hold a
  complete year.
- **A registered park that is never captured keeps years open without failing** (D2; review finding C3, rejected).
  The company-year row for that year is already withheld (D1), so nothing incomplete is published. An error would fail
  every real build while parks are played in turns, because Park 2 joins later on the company calendar. The gap stays
  visible in the register (`open`, `first_captured_company_year` null) and as a missing closed year on the site.
- **A trailing lost statement looks pending.** A statement lost at the end of a park's captured history (October of
  its last captured year, or any month of a park that stops playing) looks the same as one not yet arrived, so the year
  stays `open` and nothing fails. With the rehearsal practice of ending sessions just after 1 March, the March
  statement that would expose a lost October arrives on 1 April, after the session ends, so the loss shows only after
  another session.
- **A discarded first session can start the season early** (D4 reads any timeline): it can make a season look full
  when the kept history starts in April or later, so the park owes months it never kept and fails in the same season, at the next real-data build once a later month is kept (rule of 2026-10-21).
- **Partial seasons have two side effects.** A park in its partial first season never holds a year open, so its later
  months change a closed company year's totals when they arrive (R3's description says so); and a first year with only
  a partial park never closes (D11), though it stays visible in `obt_park_year`.
- **Park 2's real rehearsal data and registry row** come from the separate two-park capture command.
- **ADR numbering assumes the ride-weather branch merges first.** If `origin/develop` lacks ADR 0034 when T9 runs, T9
  still uses 0035 and reports it; if the docs check refuses the gap, T9 stops and reports.

## Tickets

Ten tickets in six waves. No two tickets in one wave own a file; a file owned in two waves is edited in order.
"Fits Luna" means at most two files and one behaviour, with an offline runnable test. "The quick build" is defined
below the table. Every done-condition fails before its ticket's change.

| Ticket | Owned files | Golden path | Acceptance | Done-condition | After | Fits Luna |
|---|---|---|---|---|---|---|
| T1 Severity macro (D7) | `macros/sample_warn_severity.sql`, `macros/sample_warn_severity.yml`, `tests/dbt/assert_every_day_of_a_closed_month_was_captured.sql` | the test's current `config()`; `macros/company_date.yml` | check: `uv run pytest tests/test_dbt_missing_day.py` passes unchanged; check: `uv run sqlfluff lint` on the files; judgment: the macro's YAML states the rule and cites ADR 0031 | `git grep -n sample_warn_severity -- macros tests/dbt` shows the definition and the call, and the pytest exits 0 | none | no (three files); Sonnet |
| T2 Close register (R1) | `models/intermediate/int_park_years__year_close.sql`, `.yml` | `int_park_years__company_year.sql`; `obt_company_month.yml` unit tests | check: U1-U7 PASS; check: `rows_on_sample` 1 on `ci`; judgment: statuses match R1 and D4 | the quick build of `+int_park_years__year_close` exits 0 and reports PASS for U1-U7 | none | yes |
| T4 `obt_park_year` (R2) | `models/marts/obt_park_year.sql`, `.yml`, `models/marts/exposures.yml` (adds the model, D15) | `obt_company_month.sql`, `.yml` | check: R2 unit test PASS; check: `rows_on_sample` 1; check: the exposure check passes; judgment: every column states unit and clock, and the description says "not yet reconciled" | the quick build of `+obt_park_year` reports the R2 unit test PASS, and `make check` exits 0 | T2 | no (three files); Sonnet |
| T5 `obt_company_year` (R3) | `models/marts/obt_company_year.sql`, `.yml`, `models/marts/exposures.yml` (adds the model, D15) | `obt_company_month.sql`, `.yml` | check: R3 unit test PASS; check: `rows_on_sample` 0; check: the exposure check passes; judgment: the description says "not yet reconciled" and that a partial season can still change a closed year | the quick build of `+obt_company_year` reports the R3 unit test PASS, and `make check` exits 0 | T4 | no (three files); Sonnet |
| T7 Company-date check and the two-park copy (R6, D12, D14) | `tests/dbt/assert_park_years_share_one_company_calendar.sql`, `tests/two_park_support.py`, `tests/test_dbt_two_parks.py` | `assert_every_kept_statement_finds_its_company_year.sql`; `tests/test_dbt_missing_day.py` | check: R6 PASS on the sample; check: R6's three pytest cases pass; check: `uv run mypy tests` clean; judgment: the header states what it catches and what it cannot | `uv run pytest tests/test_dbt_two_parks.py` exits 0 | T4 | no (three files, real dbt); Sonnet |
| T3 Close test (R4) | `tests/dbt/assert_every_expected_park_closes_its_company_year.sql`, `tests/test_dbt_two_parks.py` (adds R4's cases, each named with `close`) | the missing-day test and its pytest | check: R4's five pytest cases pass; check: `uv run mypy tests` clean; judgment: each failing row names park, year, missing months and the hint | `uv run pytest tests/test_dbt_two_parks.py -k close` exits 0 with five tests passed | T1, T2, T5, T7 | yes, by size; real dbt, so allow the longer run |
| T6 Exact ties (R5) | `tests/dbt/assert_obt_park_year_reconciles_exactly.sql`, `tests/dbt/assert_obt_company_year_reconciles_exactly.sql` | `assert_company_year_to_date_reconciles_exactly.sql` | check: PASS on the sample build; judgment: every sum column, `statements_kept`, `months_checked` and the closed-year set are compared through a full outer join (the sample exercises only the park-year tie, because the company table is empty there) | the quick build of both tests reports both PASS | T4, T5 | yes |
| T8 Site switch and deletion (R7) | `site/exports.toml`, `site/_data/*.json`, `site/index.njk`, `page_check.py` (and `page_check_years.py` if needed), `tests/page_check_support.py`, `tests/test_showcase_page_check.py`, `tests/test_showcase_export.py`, `models/marts/exposures.yml`, the old model's `.sql` and `.yml`, its tie test, `ARCHITECTURE.md` (the `:229` path span only) | `site/exports.toml`; `page_check.py` `:200-262` | check: Verify-by step 5; check: `uv run pytest tests/test_showcase_page_check.py tests/test_showcase_export.py`; check: `git grep -n company_year_to_date -- models/marts site src tests scripts` prints nothing; judgment: the page copy states the close rule, "not yet reconciled" and its sample | `site/_data/park_year.json` and `site/_data/company_year.json` exist, `site/_data/company_year_to_date.json` does not, the grep prints nothing, and `make check` exits 0 | T3, T6 | no; Sonnet |
| T9 Documents (R8) | `docs/CONVENTIONS.md`, `docs/ai-dlc/reports/dbt-design--findings.md`, `docs/ai-dlc/reports/dbt-design--marts.md`, ADR 0035 (new), ADR 0026, `ARCHITECTURE.md`, `models/overview.md`, `docs/showcase/trace-operating-profit.md`, `CHANGELOG.md` | `docs/ai-dlc/specs/missing-day.md` R4 and R5 | pre-step: merge `origin/develop`; check: `uv run python scripts/check_docs.py` exits 0; check: Verify-by step 6 prints nothing; judgment: ADR 0035 states what was given up, and the reports' dated notes mark what is superseded | ADR 0035 exists, Verify-by step 6 prints nothing, and `make check` exits 0 on the merged branch | T8 | no; Claude (ADR wording) |
| T10 Two parks through the export (R7) | `tests/test_dbt_two_parks.py` (adds one case named with `export`) | R4's base build; `tests/test_showcase_export.py` | check: the case passes; judgment: it asserts both park IDs in `park_year.json` and zero rows in `company_year.json` | `uv run pytest tests/test_dbt_two_parks.py -k export` exits 0 with one test passed | T8 | yes |

Waves, each ending with `make check` green: 1 = T1, T2 (the register is intermediate, so needs no exposure); 2 = T4
(exports unchanged); 3 = T5, T7 (T7 needs only the park-year table); 4 = T3 (reads both year tables), T6; 5 = T8 (its
grep covers only its own files); 6 = T9 (after merging `origin/develop`), T10 (disjoint files). T8 waits for T6
because T6's golden path is the tie test that T8 deletes; T8 runs `make site-export` and owns the regenerated files.

**The quick build** (T2, T4, T5, T6): its output must report PASS for each named unit test or test, because a
selector that matches nothing also exits 0.

```sh
uv run python -m openrct2_analytics.ingest.warehouse_guard --root warehouse warehouse/dev/dev.duckdb
uv run dbt build --profiles-dir . --target dev --select +<model or test> --indirect-selection cautious \
  --vars "{parquet_root: data/sample/rehearsal}"
```

Sample counts are confirmed from the fresh `ci` build inside `make check`, never from `dev`.
