# ADR 0031: a closed month's never-captured game day fails real-data builds

- Date: 2026-10-16.
- Status: Accepted 2026-10-16 (ruled by the project owner).
- Builds on:
  - ADR 0006 (`docs/adr/0006-plugin-records-facts-dbt-decides-validity.md`): the plugin records facts and dbt
    decides which are valid.
  - ADR 0024 (`docs/adr/0024-save-lineage-rules-for-the-kept-timeline.md`): the save-lineage rules that drop the
    events after each save's cut.
  - ADR 0012 (`docs/adr/0012-data-team-practices-adapted-for-one-person.md`): every test states its severity.
- Spec: `docs/ai-dlc/specs/missing-day.md`.

## Bottom line

A closed month is a game month with a kept monthly statement. When such a month has a game day that was never
captured, the build fails on real data. Never captured means the day has no park snapshot on any timeline. The failure
names the park, the month, the day, the sessions on each side of the gap and the save to replay. A day that was
captured but dropped at a save boundary does not fail anything. It is listed by a separate check at warn severity. Days
before a park's first captured day are not checked. The failing test only warns, rather than fails, in two cases: on
target `ci`, and on target `dev` when it reads the committed sample folder. The committed sample has no never-captured
day, so the failing test finds nothing there. A planted fixture proves that it works.

## Context

- **Why a missing day matters.** A closed month's day totals are only complete when every one of its game days has a
  kept reading. The way to recover a missing day is to replay the saved game, so a failure must say which save to load.
- **Two kinds of missing day.** A day can lack a kept reading for two different reasons, and they need opposite
  treatment.
  - **Never captured.** The day has no `park_snapshot` event at all. It was played without the plugin, or its events
    were lost. This is a real gap.
  - **Dropped at a save boundary.** The day has a snapshot, but the save-timeline rule abandoned it. A session's last
    day is recorded after that session's save, so the next session, which resumes from the save, keeps none of that
    day's events (`data/sample/rehearsal/README.md:55-65`). The rule drops one day per session boundary by design. A
    test that failed on these days would fail almost every real month that spans more than one session.
- **Where the gaps are on the sample.** The committed sample (one park, three chained sessions, 6 March to 22 June of
  year 9) has only two kinds of gap.
  - **Before capture began:** 1 to 6 March. Snapshots start on game month 0, day 7.
  - **At the two save boundaries:** 11 April (game month 1, day 11) and 17 May (game month 2).
- **Severity by target alone is not enough.** `make check` builds on `ci` over the sample. `make transform` and
  `make pipeline` build on `dev` over a real data set's folder (`Makefile:108-117`). `make publish` builds on
  `rehearsal` or `company`. A severity read from `target.name` alone would therefore treat `make transform` like a
  hand-typed `dev` build over the sample.

## Decision

1. **Never-captured days fail.** A singular dbt test, `tests/dbt/assert_every_day_of_a_closed_month_was_captured.sql`,
   returns one row per never-captured day.
   - **Which days it checks.** It walks every game day of each kept statement month, on the day calendar
     `int_park_days__company_calendar`, from the park's first captured day onward.
   - **What fails.** A day fails when it has no `stg_park_snapshot` row at all, kept or abandoned.
   - **What each row names.** The park, the statement year and month, the missing day with its company date, the
     session of the nearest kept day on each side, and the save to replay.
2. **Save-boundary days are listed, not failed.** A second singular test,
   `tests/dbt/assert_every_captured_day_of_a_closed_month_is_kept.sql`, has warn severity on every target. It lists
   each day of a closed month that has a snapshot but no kept one, with its reason. Together the two tests cover every
   day of a closed month, from the park's first captured day onward, that lacks a kept reading, and no day appears in
   both.
3. **Days before a park's first captured day are out of scope.** The first captured day is the park's earliest game
   day with any `stg_park_snapshot` row. Earlier days of the same month are not checked, and the test's header comment
   says so. A park whose capture starts mid-month would otherwise fail on its first month for days nobody could have
   recorded.
4. **Severity depends on the target and the data folder.** The failing test warns in two cases:
   - when `target.name` is `ci`;
   - when `target.name` is `dev` and `parquet_root` is the committed sample folder.

   It errors in every other case: on `dev` over any other folder, and on every other target, so `make transform`,
   `make pipeline` and `make publish` on a real data set fail.
   - **How "the sample folder" is recognized.** By its resolved location, so a relative and an absolute path to the
     committed sample both warn. The variable, with its default `data/sample/rehearsal`, loses any trailing slash and is
     compared with `data/sample/rehearsal` and with the project folder followed by `/data/sample/rehearsal`. The project
     folder is `invocation_args_dict.get("project_dir")`, because dbt's `project_root` renders empty in a singular test's
     parse-time `config()`. `project_dir` is the folder dbt runs in, or the one `--project-dir` names.
   - **Why not the literal comparison of `rows_on_sample`** (`tests/dbt/generic/rows_on_sample.sql:10`). It treats an
     absolute path to the sample as real data. A path that reaches the sample through a symbolic link or `..` is not
     recognized and errors, which is the safe side. The fixture test checks both spellings.
   - **No other file changes.** Neither the `Makefile` nor `profiles.yml` changes.
5. **The sample finds nothing, so a fixture proves the test.** On the `ci` sample the failing test returns zero rows,
   because the sample's only gaps are before capture began and at save boundaries. A pytest builds a scratch copy of
   the sample's Parquet with one kept mid-month snapshot removed. It shows that the test fails on a real-data target
   and only warns on `ci`. The copy is made in a temporary folder at test time, and the committed sample is never
   modified.

## What was given up

- **Different severity in different places.** The failing test's severity is computed in Jinja inside `config()`.
  This is the first test in the repo to do so. dbt evaluates `config()` when it parses the project, so the severity
  depends on dbt re-parsing whenever the target or the variables change. Its pytest disables partial parsing (dbt's
  reuse of an earlier parse) for that reason. A `ci` run therefore cannot show the error that a production run would
  raise. The fixture test is the only proof.
- **Whole months before capture are not checked.** Statement months that end before a park's first captured day get
  no day check at all. Their statements are still checked by the existing statement tests.
- **Save-boundary days never block a build.** A save-boundary day costs its month one day of readings, and only the
  warn listing shows it.

## Consequences

- A failure on real data stops `make transform`, `make pipeline` and `make publish` until the missing days are
  replayed and captured.
- A missing month has no recovery path yet (`ARCHITECTURE.md`, the paragraph "Marts and the site page"), and this
  test does not add one.
- The alert path for failed tests on production runs is decided separately in ADR 0032
  (`docs/adr/0032-failed-test-alert-path.md`).
- The rule in `docs/CONVENTIONS.md:113` ("a severity that differs by data set reads `target.name`") gains a clause:
  on `dev` the severity also reads the data folder.
