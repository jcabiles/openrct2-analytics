# ADR 0035: company years close from a register derived in dbt

- Date: 2026-10-18.
- Status: Accepted 2026-10-18 (ruled by the project owner, the portfolio view across parks, roadmap NEXT item 6). Amended 2026-10-21: item 4 adds the same-season incomplete rule (approved by the project owner 2026-10-20).
- Supersedes in part: ADR 0026 (`docs/adr/0026-build-time-json-for-the-first-site-page.md`), its roll-up-mart decision
  only. The year-to-date table is replaced; the rest of ADR 0026 stands.
- Builds on: ADR 0023 (one company calendar shared by all parks) and ADR 0031 (target-dependent test severity).
- Spec: `docs/ai-dlc/specs/next6-portfolio.md`.

## Bottom line

The year-to-date table is deleted. Two yearly tables replace it: `obt_park_year` (every park-year, with a close status)
and `obt_company_year` (closed company years only). A company year closes only when every park expected in it has all
eight monthly statements, March to October (a park's partial first season is exempt, and at least one expected park must be complete), and a register built in dbt from the park registry decides this. The
cost is that the committed sample, which holds one park and three months, has no closed company year, so the site
loses its company headline.

## Context

The year-to-date table grouped `fct_park_month` by company year alone. It carried no per-park completeness, so a
company total could silently omit a park that had not yet closed its year. The portfolio view needs two parks on one
company calendar, and a company figure that never hides a missing park.

## Decision

1. **A close register is derived in dbt** (`int_park_years__year_close`) from each park's `company_start_year` in the
   current park registry: no seed and no new contract column. A park is expected in every company year from its first
   full company year onward. The register owns every close rule; the two marts and the test read it and re-derive
   nothing. The register spans each park's start year to the latest company year with a kept statement.
2. **A park's partial first season is exempt.** A park-year is a partial first season when it is the park's start year,
   the park's first captured day falls in it, and the first month that day can report is game month 1 (April) or later.
   That month is the day's own game month, except that a first captured day 1 of month m (m of 1 or more) carries month
   m - 1's statement, because the plugin's day-1 callback delivers the previous month's statement, the same reason
   March's statement arrives on 1 April. So a first captured day 1 of April is a full season, and day 1 of June
   (month 3) owes months 2 to 7. The park-year gets the status `partial_first_season`, never holds its company year open, and is
   published flagged as partial. A data test (`assert_register_kept_within_expected`) fails if a row ever keeps more
   statements than it expects.
3. **`obt_company_year` holds closed years only**, and a company year closes only when at least one expected park is
   `complete`. `obt_park_year` holds every park-year with a kept statement, with its status.
4. **A blocking test fails real-data builds** when a park has already moved on to a later year (read from kept
   statements, not kept days) but still lacks a statement it owes for an earlier year, because later play can no
   longer fill that gap. The test also fails when `obt_company_year` holds a year the register does not mark closed, so
   a leaked year cannot be published. A park-year that is not a partial first season is also `incomplete` when a kept
   month comes after a missing reportable month of the same year, so the test fires in the same season (amended
   2026-10-21, with the project owner's approval of 2026-10-20); only trailing missing months keep a year `open`. A
   year still in progress whose only missing months come after its last kept month fails nothing (or that has no kept month yet). Severity is error on real-data targets and warn on
   `ci` and on `dev` over the committed sample, through the shared macro `sample_warn_severity`.

## What was given up

- **The sample loses its company headline.** `obt_company_year` has 0 rows on the committed sample, so the page shows
  park-years only and says "No company year has closed yet". Rejected: rows for open years with an `is_closed` column,
  which would publish unclosed company totals.
- **Some gaps stay silent.** A never-captured park and a trailing lost statement keep a year open without a failure,
  and a lost October is reported only when March's statement arrives on 1 April of the next year. Rejected: failing on
  every unclosed year, which would stop every mid-season `make transform` and `make publish`.
- **A leading gap now fails real-data builds in the same season.** A real capture with a gap before a kept month fails
  the blocking test on real-data targets as soon as a later month is kept, instead of after the next year's first
  statement.
- **A statement lost in a partial first season is never flagged;** it shows only in the row's
  `missing_statement_months`. Rejected: making the partial park owe every month from its join month, which departs
  from the ruling that a partial first season is exempt.
- **A company's first year can stay invisible in `obt_company_year`.** If only a park that joined mid-season reports
  that year, no expected park is complete and the year never appears there (it stays visible in `obt_park_year`).
- **The marts depend on one intermediate model** whose logic only its unit tests prove, and the register's span is set
  by the furthest-ahead park.
- **A refactor of a shipped test:** the ADR 0031 severity expression moves into one macro that both target-dependent
  tests call.

## Consequences

- `obt_company_year_to_date`, its tests and `site/_data/company_year_to_date.json` are deleted; the site, the export
  allowlist, the exposures, the expected-row table and `docs/CONVENTIONS.md` name the new tables.
- Published year figures carry a "not yet reconciled" label until reconciliation reports exist (v1.1).
- `meta.expected_min_rows` is 0 for `obt_company_year`, so a data set with no closed year can still publish.
