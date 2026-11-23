# ADR 0057: the park number is a warehouse column served as a seventh export

- Date: 2026-11-17.
- Status: Proposed with the spec `docs/ai-dlc/specs/say-the-park.md`; it takes effect when the branch that builds it
  merges. It amends ADR 0045 (`docs/adr/0045-site-data-holds-the-department-exports.md`) and edits neither it nor any
  other record.

## Bottom line

`marts.dim_park` gains a column `park_number`, and `site/_data/` grows from six files to seven. The seventh,
`park.json`, is a dimension export: one row per numbered park, with `park_id` and `park_number`. The site and the
filing line read the number from this column and never compute it. This amends ADR 0045, which listed six files.

## Context

The site labelled parks "Park n" by the position of each park in its own month rows, so a park without a monthly
statement shifted every later label. The filing line of `make auto-file` needs the same number. Two computations of
one order would drift apart.

## Decision

1. **`dim_park.park_number` is the one numbering home.** For every registered park that is not a Sandbox park it is the
   1-based position by `company_start_year`, then the earliest `emitted_at` of any of its `session_start` rows (all
   sessions, `nulls last`), then `park_id`. It is cast to `integer`. A Sandbox park (registry note equal to the
   practice note) has no number and is not counted. Every non-Sandbox park of the warehouse is counted, whatever its
   `data_set`.
2. **The Sandbox note has one copy in dbt, the macro `macros/practice_note.sql`.** `tests/test_practice_note.py` fails
   when it differs from `registry_feed.PRACTICE_NOTE`.
3. **A seventh served file, `site/_data/park.json`, carries `park_id` and `park_number`,** ordered by `park_number`
   then `park_id`. It is written by `make site-export` and compared with a fresh sample build by `make check`, as the
   other six are. It computes nothing. Any test that pins the list of files in `site/_data/` lists the seven files.
4. **Exposures that show "Park n" depend on `ref('dim_park')`.**

## Consequences

- Gain: one order, tested once in the `dim_park` unit tests, read by every caller.
- Cost: one more join and window in `dim_park`, one macro, one more committed file to regenerate when `dim_park`
  changes.
- ADR 0045 decision 4 now reads "seven files" for the list pinned by tests; its other decisions stand.
- The dashboard is unchanged: it selects named columns from `dim_park`.
