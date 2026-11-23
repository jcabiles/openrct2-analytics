# Spec: a closed month's never-captured game day fails real-data builds

status: approved (--auto-build pre-ruling 2026-10-16) · date: 2026-10-16 · branch `feat/missing-day-test` from `develop` `adf2203` ·
contract map: `docs/ai-dlc/contracts/missing-day.md` · decisions: ADR 0031 (`docs/adr/0031-missing-game-day-test.md`)
and ADR 0032 (`docs/adr/0032-failed-test-alert-path.md`) · Gate 1 record (the scope interview): confirmed by the project
owner on 2026-10-16 and kept outside version control. Every line this spec relies on is restated below.

## Bottom line

This work adds two dbt tests and one pytest file. No model, Makefile target or profile changes.

- **The first test** fails a real-data build when a closed month has a game day that was never captured. A closed
  month is a game month with a kept monthly statement. Never captured means the day has no park snapshot at all. Each
  failing row names the park, the month, the day, the sessions on each side of the gap and the save to replay.
- **Where it only warns.** On the `ci` target, and on `dev` when it reads the committed sample, it only warns. The
  committed sample has no such day, so there it returns nothing.
- **The second test always warns.** It lists the captured days of a closed month that were not kept, with the
  reason (`save_boundary`, `no_cut` or `abandoned_session`), which is expected (ADR 0031). On the
  sample it lists two days, 11 April and 17 May of year 9.
- **How the first test is proven.** A pytest removes one kept mid-month snapshot from a scratch copy of the sample.
  It shows that the first test fails on `dev` and `rehearsal` and only warns on `ci`. It must catch the planted day in
  10 runs out of 10.
- **What comes later.** The email alert for failed tests is decided in ADR 0032 but not built here. The roadmap gains
  a NEXT item for it.

Four tickets: the two tests, the pytest, then the documents.

## Rulings

These are the project owner's rulings of 2026-10-16, quoted.

- "Add a dbt test that fires when a closed month (one with a statement) has any missing game day, so the saved game
  can be replayed; it errors on real data sets and warns on the ci sample. Failed dbt tests on production runs (make
  transform, make pipeline, make publish with a real data set; never make check) email the project owner; the address
  comes from an environment variable and is never committed."
- Answers to the scope interview:
  - "Error only on never-captured days". Save-boundary days go to a separate check that only warns.
  - "Skip days before capture began".
  - Severity by "Target plus data folder".
  - Failure rows carry "Park, month, day, session, save".
  - The alert ideas are split "Repo vs owner split".
- After the run: "The roadmap should ensure that future director agents read the latest version of secretary email
  script before proceeding with any work". This spec carries that instruction as the first line of the alert-outbox
  roadmap item (R5), as one line in the roadmap's general run-start section, and as ADR 0032, decision 9. "Director agents" are the sessions that run this project's work,
  and "the secretary email script" is the shared sender.

Repo rules that bind every ticket:

- Committed text never names the project owner. It contains no private machine path, no email address and no account
  of how agents produced the work.
- The written rules in `docs/CONVENTIONS.md` win over the golden examples.

## Goal

**Stated goal** (`CLAUDE.md:3`): "A portfolio analytics stack for a theme park run as a business."

**Why this test.** A business that books a month needs the month's daily readings to be complete. The way to repair
a never-captured day is to replay the saved game, so the test names which save to load.

**Audience:**

- the technical reviewer of a portfolio data stack, who checks that each failure mode has a test with a stated
  severity;
- whoever runs the pipeline, who must act on a failure.

## Every Gate 1 line, and where it lands

| Gate 1 line (quoted or closely paraphrased) | Where |
|---|---|
| In scope 1. The error-level test checks every park-month with a kept statement. Every game day of that month on `int_park_days__company_calendar`, from the park's first captured day onward, that has no `stg_park_snapshot` row of any timeline status is a failing row. Days before the first captured day are out of scope, and the header says so. | R1; D1, D2; A3, A5 |
| In scope 2. The warn-only check lists days of a closed month that have an abandoned snapshot and no kept one, with that reason. Expected on the sample: 2 rows (11 April and 17 May of year 9), which the spec confirms from a `ci` build. | R2; D4; A4 |
| In scope 3. Severity is warn on target `ci`, or on `dev` with `parquet_root` at the committed sample (the pattern of `rows_on_sample.sql:8-18`), and error otherwise. No Makefile or profiles change. | R1 (severity); D3; A8; "Not changed" |
| In scope 4. Failure rows carry `park_id`, the statement year and month, each missing game day with its company date, the `session_id` of the kept day on each side of the gap, and the save that session loaded. | R1 (columns); D5; A9; O3 |
| In scope 5. ADR 0031 (the missing-day rule) and ADR 0032 (the alert path). | Written with this spec: `docs/adr/0031-missing-game-day-test.md`, `docs/adr/0032-failed-test-alert-path.md` |
| In scope 6. Roadmap: the missing-day item (done by this branch) and a NEXT item for the alert outbox (after: the test), with no waits-on-owner line. Follow-ups on the sender's side go to the project owner's local follow-up list and block nothing. | R5 (roadmap). The local list is outside version control, so no ticket here edits it; it is recorded outside the repo. |
| Out of scope: any email-sending code, the outbox build, Makefile or profiles target changes, edits to existing models, recovery for a missing month, and the cleaning-rule counts work. | "Out of scope"; A11 |
| Done: `make check` is green on the PR head, and the zero-row build returns no rows for both tests. | A1, A2 |
| Done: on the sample, the error test returns 0 rows and the warn check returns the save-boundary days the spec states. | A3, A4 |
| Done: a planted never-captured day makes the error test fail on a real-data target and only warn on `ci`. A test that runs real dbt per target proves it (the `tests/test_dbt_environments.py` pattern). Plant rule: 10 runs, every run caught. | R3; A5, A6 |
| Done: committed text names no private path, no address, and not the owner. | A7 |

## Spec decisions

Each decision is the default the build follows, and reviewers may challenge any of them.

- **D1. Names: two `assert_` tests, no `review_` prefix.**
  - **The error test** is `tests/dbt/assert_every_day_of_a_closed_month_was_captured.sql`.
  - **The warn check** is `tests/dbt/assert_every_captured_day_of_a_closed_month_is_kept.sql`. Its name states the
    condition that should hold, and warn severity says that a known exception is tolerated. That is the precedent of
    `tests/dbt/assert_park_registry_superseded_delivery_date_matches_file_name.sql:1-4`.
  - **Why the `review_` prefix is rejected.** `docs/CONVENTIONS.md:111` reserves the prefix for an observational
    hypothesis, a claim about cause kept for the year-end review. This check makes no claim about cause, and that rule
    returns rows "only for closed company years", whereas this check must list days on every build.
  - **Gain:** both names follow the `assert_<what holds>` rule (`docs/CONVENTIONS.md:73`), and neither misstates its
    purpose.
  - **Cost:** the warn check's name reads as a rule that real data breaks at every session boundary. Its header
    comment says so.
- **D2. Day order uses one integer index.** The index is `(game_year * 8 + game_month) * 32 + game_day`.
  - **Why it works.** Months run 0 to 7 and step with `year * 8 + month`
    (`tests/dbt/assert_statement_cash_matches_next_day_start_cash.sql:7-9`). No month has more than 31 days, so the
    index grows with every game day. The park's first captured day is the minimum index over its `stg_park_snapshot`
    rows.
  - **Gain:** one comparison, valid across the month-7 rollover.
  - **Cost:** the index has gaps (unused values 32 per month), so it orders days but never counts them.
- **D3. Severity is computed in `config()`.** The error test opens with
  `config(severity=("warn" if <rule> else "error"), store_failures=true)`. Here `<rule>` is
  `target.name == "ci" or (target.name == "dev" and <on the sample>)`.
  - **How the sample is recognized.** By its resolved location, so a relative and an absolute path to the committed
    sample both count. The rule takes `var("parquet_root", "data/sample/rehearsal")`, drops a trailing slash, and
    compares it with two strings: `data/sample/rehearsal`, and the project folder followed by
    `/data/sample/rehearsal`. The project folder is `invocation_args_dict.get("project_dir")`, because dbt's
    `project_root` renders as an empty string in a singular test's parse-time `config()` (measured on dbt 1.11.15: an
    absolute path to the sample then errored on `dev`). `project_dir` is the folder dbt runs in, or the one
    `--project-dir` names. A relative `--project-dir .` together with an absolute sample path is not recognized as
    the sample either, so the test errors, which is the safe side. The expression stays Jinja that
    `config(severity=...)` can hold. Anything else, including a path that reaches the sample
    through a symbolic link or `..`, gets error, which is the safe side.
  - **Why not the literal comparison of `tests/dbt/generic/rows_on_sample.sql:10`.** That comparison treats an
    absolute path to the sample as real data. The stated rule is "`dev` reading the committed sample", whatever the
    spelling of the path.
  - **Gain:** no Makefile or profiles change, and `make transform` (target `dev`, absolute data-set folder,
    `Makefile:108-117`) errors, while a hand-typed `dev` build over the sample warns in either spelling.
  - **Cost:** this is the first severity computed in Jinja, and it adds a path comparison that `rows_on_sample` does not make. dbt evaluates `config()` at parse time, unlike
    `rows_on_sample`, which branches in the SQL body for that reason (`rows_on_sample.sql:5-6`). Every pytest dbt call
    therefore passes `--no-partial-parse`, and R3 case (e) checks the parsed severity per target.
- **D4. The warn check's reason comes from lineage, not from a second copy of the cut rule.**
  - **What it lists.** One row per day of a closed month that has a `stg_park_snapshot` row but no `fct_park_day` row,
    per session holding such a snapshot.
  - **The reason.** Three values, read from the session's `int_sessions__lineage` row:
    - `save_boundary` when `is_on_kept_path` is true and `cut_seq` is not null (the snapshot fell at or after a
      proven cut);
    - `no_cut` when `is_on_kept_path` is true and `cut_seq` is null, a session on the kept path that wrote no save,
      so the macro abandons all its snapshots without any save boundary (`macros/timeline_status.sql:10-14`);
    - `abandoned_session` when the session is off the kept path, or has no lineage row.
  - **Why no second copy.** The query tests only whether `cut_seq` is null, never `seq` against it. The
    `timeline_status` macro stays the only place that compares `cut_seq` (`macros/timeline_status.sql:1-7`).
  - **Gain:** no repeat of the cut rule, and the two tests together cover every closed-month day, from the park's
    first captured day onward, that lacks a kept reading, with no day in both.
  - **Cost:** the sample holds no session off the kept path, so no test exercises `abandoned_session` (open point O4).
    `no_cut` is exercised by R3 case (f).
- **D5. The save to replay is the save the session before the gap loaded.** That is
  `int_sessions__lineage.loaded_save_id` of `session_id_before`. It is null when the session before the gap started
  from the park's file, or when no kept day precedes the gap; the header says to use the park's original file then.
  - **Gain:** the save always predates the gap, and it takes one join.
  - **Cost:** the save may be much older than the gap, so the replay is longer (open point O3).
- **D6. Both tests store their failing rows.** Each test sets `store_failures: true`.
  - **Gain:** the rows can be read back from the `dbt_test__audit` schema, both by the Verify-by queries and by the
    later alert outbox (ADR 0032, decision 2). The precedent is `tests/dbt/generic/repeat_delivery_payload_differs.sql:15`.
  - **Cost:** every built warehouse, including published files, gains two tables in `dbt_test__audit`.
    `tests/test_dbt_environments.py:487-492` already expects that schema. The publish audit counts every table with a
    `park_id` column (`src/openrct2_analytics/ingest/publish_audit.py:285-343`). The stored rows carry only parks
    already in the data, so the audit's result does not change (open point O5).

## Requirements

Both tests follow `docs/CONVENTIONS.md`:

- the dbt SQL style (lowercase, at most 80 characters per line, explicit `as`, CTEs named for their step, typed and
  qualified joins);
- a header comment that states what a row means, the severity, and the clock: the game day, with company dates
  carried for reading.

Neither test reads a money column.

### R1. The error test: `tests/dbt/assert_every_day_of_a_closed_month_was_captured.sql` (Gate 1 in scope 1, 3, 4)

- **Config.** Severity per D3; `store_failures=true` (D6).
- **CTEs.**
  - `statements`: from `fct_park_month`: `park_id`, `statement_year`, `statement_month`, `statement_company_date`.
  - `calendar_days`: from `int_park_days__company_calendar`: `park_id`, `game_year`, `game_month`, `game_day`,
    `company_date`, plus D2's index as `day_index`.
  - `snapshot_days`: the distinct `park_id` and game date of every `stg_park_snapshot` row, kept or abandoned.
  - `first_captured`: per `park_id`, the minimum `day_index` over `snapshot_days`.
  - `closed_month_days`: `calendar_days` inner join `statements` (on `park_id`, `game_year = statement_year`,
    `game_month = statement_month`), inner join `first_captured` (on `park_id`), where `day_index` is at least the
    first captured index.
  - `never_captured`: `closed_month_days` left join `snapshot_days`, keeping the rows with no match.
  - `kept_days`: `park_id`, game date, `session_id` and `day_index` from `fct_park_day`.
  - `neighbours`: for each never-captured day, the `session_id` of the kept day with the largest `day_index` below it
    (`session_id_before`) and with the smallest above it (`session_id_after`), from the same park. Either may be null.
  - `with_save`: left join `int_sessions__lineage` on `session_id_before` for `loaded_save_id`.
- **Columns, in this order:** `park_id`, `statement_year`, `statement_month`, `statement_company_date`, `game_year`,
  `game_month`, `game_day`, `company_date`, `session_id_before`, `session_id_after`, `save_to_replay`.
- **Grain:** one row per park and never-captured game day.
- **The header comment states:**
  - what a row means and how to act on it (replay `save_to_replay`, or the park's original file when it is null);
  - that days before the park's first captured day are not checked;
  - that a park with no snapshot at all has no first captured day and so returns no row;
  - that a park-year without a registry mapping has no calendar rows, and that
    `assert_every_kept_statement_has_a_company_date` errors on its statements instead;
  - the severity rule and ADR 0031.
- **Sample result:** 0 rows. The sample's only gaps are before capture began (1 to 6 March) and at save boundaries.

### R2. The warn check: `tests/dbt/assert_every_captured_day_of_a_closed_month_is_kept.sql` (Gate 1 in scope 2)

- **Config.** `config(severity="warn", store_failures=true)` on every target.
- **CTEs.** The same `statements` and `calendar_days` as R1. Then:
  - `captured`: `stg_park_snapshot`, distinct `park_id`, game date and `session_id`;
  - `kept_days`: the game dates of `fct_park_day`;
  - `not_kept`: the closed-month days with a `captured` row and no `kept_days` row;
  - a left join to `int_sessions__lineage` on `session_id` for D4's reason.

  No filter on the first captured day is needed, because every captured day is on or after it.
- **Columns:** `park_id`, `statement_year`, `statement_month`, `game_year`, `game_month`, `game_day`,
  `company_date`, `session_id`, `reason` (`save_boundary`, `no_cut` or `abandoned_session`).
- **Grain:** one row per park, game day and session whose snapshot of that day was not kept.
- **The header comment** says that real data lists one day per session boundary by design (ADR 0006, ADR 0024), that
  this never blocks a build, and that never-captured days are R1's.
- **Sample result:** 2 rows, both `save_boundary`:
  - game year 9, month 1, day 11 (11 April), session 1;
  - game year 9, month 2, day 17 (17 May), session 2.

  Measured on a fresh `ci` build (columns in the order above):
  - `('k1791584320937-w5p1uw', 9, 1, 9, 1, 11, 2000-04-11, 's1791584320937-xotnl9', 'save_boundary')`
  - `('k1791584320937-w5p1uw', 9, 2, 9, 2, 17, 2000-05-17, 's1791584801027-j3kesv', 'save_boundary')`

  R3 case (d) uses these rows. A different count or month stops the ticket.

### R3. The pytest: `tests/test_dbt_missing_day.py` (Gate 1 "Done means", plant rule)

- **Where it lives.** A new file, because `tests/test_dbt_environments.py` is 496 lines. It imports `SAMPLE`, `dbt`
  and the `project` fixture from `tests.test_dbt_environments`, as `tests/test_company_year.py:16-17` does.
- **The planted fixture.**
  - Copy `SAMPLE` (Parquet and registry) into `tmp_path / "planted"` with `shutil.copytree`.
  - Rewrite `v1/park_snapshot.parquet` there through DuckDB without the one row of game year 9, month 1, day 20
    (20 April). That day falls inside session 2's kept run, which starts on 12 April and runs into May
    (`data/sample/rehearsal/README.md:55-65`), so it is a kept mid-month day with kept neighbours in the same session.
  - Assert that exactly one row was removed (108 before, 107 after).
  - The committed sample is never written. Nothing is created under `data/`.
- **The helper.** `run_missing_day(project, target, parquet_root, env)` runs
  `dbt run --select +<R1 test> +<R2 test> --no-partial-parse`, then
  `dbt test --select <R1 test> <R2 test> --no-partial-parse`. Both commands pass one `--vars` with `parquet_root` set
  to the given folder and `registry_root` set to `<folder>/registry` (`parquet=False, registry=False`, per the
  helper's note at `tests/test_dbt_environments.py:49-51`). The registry source reads
  `<registry_root>/v1/park_registry_*.csv` (`models/staging/_sources.yml:990`), and the sample keeps its feed under
  `registry/v1/` (`data/sample/rehearsal/README.md:32`), so the copy's `registry_root` is `<copy>/registry`, never
  the copy itself. The helper returns the `dbt test` exit code and each test's PASS, WARN or
  FAIL, read as `tests/test_dbt_registry_current.py:25-26` reads it.
  - **Why `run` then `test`.** Only the two new tests run, so no other test reacts to the removed row.
- **Targets.**
  - `ci` sets `OPENRCT2_CI_DIR` to a temporary folder.
  - `dev` creates `project / "warehouse" / "dev"` first.
  - `rehearsal` sets `OPENRCT2_PUBLISH_RUN_ID` to `run1` and creates `project / "warehouse" / "candidate" / "run-run1"`
    first (`tests/test_dbt_environments.py:118-121, 276-292`).
  - **Why `rehearsal`, not `company`.** The sample registry's data set is `rehearsal`, which
    `assert_park_registry_current_data_set_matches_target` requires.
- **Cases.** Cases (a) to (c) and (f) have `planted` in their function names, so Verify-by step 5 selects exactly them, and
  no other case does.
  - **(a) Planted, `ci`.** The `dbt test` exit code is 0, R1 is WARN, and its stored row names game year 9, month 1,
    day 20. `session_id_before` equals `session_id_after` (session 2), and `save_to_replay` equals session 2's
    `loaded_save_id`.
  - **(b) Planted, `dev`.** The exit code is not 0, and R1 is FAIL.
  - **(c) Planted, `rehearsal`.** The exit code is not 0, and R1 is FAIL. Run it in the same project copy right after
    (a), so the change of target is proven to change the outcome.
  - **(d) Committed sample, `ci`.** The exit code is 0, R1 is PASS, R2 is WARN, and R2's stored rows equal the two
    days R2 states, with their sessions and `save_boundary`.
  - **(f) Planted, `no_cut` reason (`test_planted_session_without_save_gets_no_cut_reason`).** On `ci`, over a
    scratch copy of the sample edited in two files: session 3's `save_written` row is removed, and session 2's
    statement in `finance_month.parquet` is relabelled from month 1 to month 2. Removing the save alone is not enough:
    session 3's cut becomes null, so its only statement (month 2) is abandoned, month 2 is no longer a closed month,
    and R2 returns 0 rows. With the relabel, statements exist for months 0 and 2, and R2 must list 15 rows in total with
    WARN status: 14 rows with a null cut and reason `no_cut` (session 3, days 18 to 31 of month 2), plus 1 row with
    reason `save_boundary` (session 2, day 17). These counts were measured once on a
    scratch `ci` build and are confirmed at build. If the build returns 0 rows, the ticket stops and reports (open
    point O4).
  - **(g) Second-game-year gap.** A planted copy shifts the park's snapshots and statements seven game months forward,
    so the park runs into game year 10, and drops the day (10, 0, 15); the error test returns exactly that day.
  - **(h) Trailing slash.** `dev` over `data/sample/rehearsal/` with a trailing slash warns.
  - **(e) Severity per target, parse only.** `dbt parse --no-partial-parse` per case, then read R1's
    `config.severity` from `target/manifest.json`:
    - `ci` over the sample or the planted folder: `warn`;
    - `dev` with no `parquet_root` variable: `warn`;
    - `dev` with the relative path `data/sample/rehearsal`: `warn`;
    - `dev` with the absolute path to the sample, built from the resolved project copy path (`Path(project).resolve()`,
      because macOS resolves a temporary folder to its real location, which is the value dbt reports) joined to
      `data/sample/rehearsal`: `warn`;
    - `dev` with the planted folder: `error`;
    - `rehearsal` and `company` with the planted folder and a safe run ID: `error`.
- **Total-WARN assertions.** No Python test asserts a total WARN count today. `grep -rn "WARN" tests/*.py` shows only
  per-test status reads. If the build finds one that R2's new WARN changes, the same ticket updates it.

### R4. Documents (house rule: a change that invalidates a document updates it in the same change)

- **`docs/CONVENTIONS.md:113`.** The row gains a clause: "on `dev`, a severity that differs by data set also reads
  `parquet_root` (ADR 0031)".
- **`ARCHITECTURE.md`.** The singular-test list (`:173-180`) adds both tests with one sentence each. The
  missing-month paragraph (`:226-230`) adds that a never-captured day of a closed month now fails real-data builds,
  and that recovery is still to replay the save.
- **`CHANGELOG.md`, "Unreleased".** One entry for the two tests and ADRs 0031 and 0032.

### R5. Roadmap (`docs/ai-dlc/roadmap/park-company.md`; Gate 1 in scope 6)

- **The missing-day item.** One item, marked done in the repo's `Done:` form. It names ADR 0031 and this spec.
- **The alert outbox item.** One item under the NEXT heading (`:90`), in the step group the ticket judges right, with
  the next free NEXT number. It reads "Alert outbox for failed tests on production runs", names ADR 0032, and carries:
  - as its first line: "Before any work on this item, read the current shared sender and its wrapper; their
    formatting, exit codes and receipt fields change often (ADR 0032, decision 9).";
  - an `after:` line naming the missing-day item;
  - no `waits-on-owner:` line.
- **The general run-start line.** The roadmap's general run-start section (`:33-34`, the director's preflight) gains
  one line: "Before sending any test email or working on alerts, read the current shared sender and its wrapper; their
  formatting changes often." The alert item's first line repeats it for that item. T4 makes both edits; this spec does
  not edit the roadmap.

## Per-test zero-row behaviour

| Test | Zero-row build | Why |
|---|---|---|
| R1 | PASS, no rows | no kept statements |
| R2 | PASS, no rows | no kept statements |

## Files

| File | New or edited | Owning rule | Owning module (`docs/CONVENTIONS.md` section 3) | Ticket |
|---|---|---|---|---|
| `tests/dbt/assert_every_day_of_a_closed_month_was_captured.sql` | new | R1 | `tests/dbt/` | T1 |
| `tests/dbt/assert_every_captured_day_of_a_closed_month_is_kept.sql` | new | R2 | `tests/dbt/` | T2 |
| `tests/test_dbt_missing_day.py` | new | R3 | `tests/` | T3 |
| `docs/CONVENTIONS.md`, `ARCHITECTURE.md`, `CHANGELOG.md`, `docs/ai-dlc/roadmap/park-company.md` | edited | R4, R5 | docs | T4 |
| this spec, `docs/ai-dlc/contracts/missing-day.md`, `docs/adr/0031-missing-game-day-test.md`, `docs/adr/0032-failed-test-alert-path.md` | new | this spec | docs | spec commit |

**Not changed:**

- every model and its YAML, `macros/`, `Makefile`, `profiles.yml` and `dbt_project.yml`;
- `contracts/`, `models/staging/_sources.yml`, `data/` (the committed sample included), `site/`, `metrics/` and
  `src/`;
- the existing `tests/dbt/` files and `tests/test_dbt_environments.py`;
- `pyproject.toml` and `uv.lock`.

No new dependency: DuckDB and dbt are already used.

## Contracts touched and how each is regenerated

- **Event contracts (`contracts/`):** none. The source drift check passes unchanged.
- **Enforced model contracts:** none. No model changes.
- **Stored-failure tables:** two new tables in `dbt_test__audit`, created by dbt at build from the tests (D6). They are
  never committed.
- **Site exports:** not affected. The export comparison in `make check` passes unchanged, and `make site-export` is
  not run.

## Test seams

- **dbt singular tests:** R1 (error by target) and R2 (warn).
- **The gate's builds.** The `ci` sample build runs R1 (PASS) and R2 (WARN, 2 rows). The zero-row build runs both
  (PASS, no rows). `sqlfluff` lints both.
- **pytest:** `tests/test_dbt_missing_day.py` runs real dbt per target over the planted fixture and the sample, and
  reads the parsed severity from the manifest.
- **What cannot be tested here:**
  - R2's `abandoned_session` reason, because the sample has no session off the kept path (O4); `no_cut` is covered by
    R3 case (f);
  - a gap that spans two sessions (`session_id_before` and `session_id_after` differ), because one planted day in
    session 2 has the same session on both sides. The column logic is the same join, and the reviewer reads it.

## Constraints

**"Never break" (`CLAUDE.md`), and how this work meets each:**

1. **Envelope fields and `seq`:** unchanged. The tests read the existing envelope columns.
2. **Raw captures are append-only:** nothing writes raw or landed files. The planted copy lives in pytest's temporary
   folder.
3. **Money:** no money column is read. Each header names its clock, the game day.
4. **Previews and predictions:** no event is added or reclassified.
5. **No game files, screenshots, GPL type definitions or private machine paths are committed.** The alert sender's
   path stays in an environment variable (ADR 0032).
6. **Versioned contract:** no contract changes.
7. **Analyses:** none published. The sample results are stated with their sample (one park, three headless
   sessions).
8. **Plugin:** unchanged.

**Files.** Each new file is well under 500 lines. `tests/test_dbt_environments.py` does not grow.

## Golden paths

- **Error test:** `tests/dbt/assert_every_kept_statement_has_a_company_date.sql` (config first, header comment, explicit
  columns).
- **Warn check:** `tests/dbt/assert_park_registry_superseded_delivery_date_matches_file_name.sql` (warn severity,
  header).
- **Severity by target and folder:** `tests/dbt/generic/rows_on_sample.sql:10` (the comparison).
- **Month index:** `tests/dbt/assert_statement_cash_matches_next_day_start_cash.sql:7-9`.
- **pytest:**
  - `tests/test_company_year.py` (imports the environment helpers, reads a status);
  - `tests/test_dbt_environments.py:276-292` (a safe run ID on a publish target);
  - `:352-356` (reading stored failures).
- **Spec form:** `docs/ai-dlc/specs/marts-month-summaries.md`.

## Out of scope

- **From Gate 1:**
  - any email-sending code;
  - the alert outbox build (ADR 0032 records its design, and the roadmap item of R5 builds it later);
  - Makefile or profiles target changes;
  - edits to existing models;
  - recovery for a missing month;
  - the cleaning-rule counts work.
- **Also out:**
  - changes to the shared sender or the Apps Script (follow-ups on the sender's side, ADR 0032 "Consequences");
  - a unit test for either singular test (dbt unit tests apply to models only);
  - a check of statement months that end before a park's first captured day.

## Verify-by

Run from the repo root on the PR head, after the last ticket merges. `make setup` must have run once.

1. `make check` exits 0.
2. **A fresh `ci` build in a temporary folder:**

   ```sh
   dir=$(mktemp -d "${TMPDIR:-/tmp}/openrct2-missing-day.XXXXXX")
   export OPENRCT2_CI_DIR="$dir"
   uv run python -m openrct2_analytics.ingest.warehouse_guard --root "$dir" "$dir/ci.duckdb"
   uv run dbt build --profiles-dir . --target ci --target-path "$dir/target" --log-path "$dir/logs" \
     --vars "{parquet_root: data/sample/rehearsal}"
   uv run python - "$dir/ci.duckdb" <<'EOF'
   import sys, duckdb
   con = duckdb.connect(sys.argv[1], read_only=True)
   print(con.execute("select count(*) from dbt_test__audit.assert_every_day_of_a_closed_month_was_captured").fetchall())
   print(con.execute("select game_year, game_month, game_day, company_date, session_id, reason from dbt_test__audit.assert_every_captured_day_of_a_closed_month_is_kept order by 1, 2, 3").fetchall())
   EOF
   ```

   Expected: `[(0,)]`, then two rows, `(9, 1, 11, …, <session 1>, 'save_boundary')` and
   `(9, 2, 17, …, <session 2>, 'save_boundary')`. The PR records the exact rows.
3. **The zero-row build, in the same folder:**

   ```sh
   uv run python -m openrct2_analytics.ingest.empty_extract --out-dir "$dir/empty"
   uv run dbt build --profiles-dir . --target ci --target-path "$dir/target" --log-path "$dir/logs" \
     --vars "{parquet_root: $dir/empty}" > "$dir/empty.log"
   grep -E "PASS .*assert_every_day_of_a_closed_month_was_captured" "$dir/empty.log"
   grep -E "PASS .*assert_every_captured_day_of_a_closed_month_is_kept" "$dir/empty.log"
   rm -rf "$dir"
   ```

   Both greps print one line.
4. `uv run pytest tests/test_dbt_missing_day.py` exits 0 with 7 passed.
5. **Plant rule, 10 runs, every run caught:**

   ```sh
   for i in 1 2 3 4 5 6 7 8 9 10; do
     uv run pytest -p no:cacheprovider tests/test_dbt_missing_day.py -k planted || exit 1
   done
   ```

   This exits 0, and the PR records "10 of 10".
6. `OPENRCT2_CI_DIR="$dir" uv run sqlfluff lint tests/dbt/assert_every_day_of_a_closed_month_was_captured.sql
   tests/dbt/assert_every_captured_day_of_a_closed_month_is_kept.sql` exits 0, run in step 2's shell, where `$dir` is
   step 2's folder holding `ci.duckdb` (the dbt templater opens it).
7. **Nothing outside "Files" changed.** This prints nothing:

   ```sh
   git diff --name-only origin/develop... -- models macros Makefile profiles.yml dbt_project.yml \
     contracts data site metrics src tests/test_dbt_environments.py
   ```
8. **No private paths in the diff or the commit messages.** Both print nothing:

   ```sh
   git diff origin/develop... | grep -n -E "/(Users|home|private)/|@[a-z0-9-]+\.[a-z]"
   git log --format=%B origin/develop.. | grep -n -E "/(Users|home|private)/"
   ```

   A reviewer confirms that no added line names the project owner.
9. `grep -rn -E "WARN=|count.*WARN" tests/*.py scripts/*.py` prints nothing, or each hit is updated in T3 (R3,
   total-WARN assertions).

## Definition of Done

The work is done when every criterion passes on the PR head and nothing outside "Files" changed.

| # | Criterion | Tag | Req |
|---|---|---|---|
| A1 | `make check` exits 0 on the PR head | check: `make check` | all |
| A2 | The zero-row build returns no rows for both tests | check: Verify-by step 3 | R1, R2 |
| A3 | On the sample, R1 returns 0 rows | check: Verify-by step 2, first query; R3 case (d) | R1 |
| A4 | On the sample, R2 returns the two save-boundary days R2 states | check: Verify-by step 2, second query; R3 case (d) | R2 |
| A5 | A planted never-captured mid-month day fails R1 on `dev` and `rehearsal` and only warns on `ci`, through real dbt per target | check: R3 cases (a) to (c) | R1, R3 |
| A6 | Plant rule: 10 runs, every run caught | check: Verify-by step 5 | R3 |
| A7 | No private path, no address and no owner name in committed text | check: Verify-by step 8; judgment: the reviewer reads every added line for the owner's name | rulings |
| A8 | Severity is warn on `ci` and on `dev` over the sample (relative or absolute path), and error otherwise | check: R3 case (e) | R1, D3 |
| A9 | R1's failing row carries park, statement month, missing day with company date, the session on each side and the save to replay | check: R3 case (a); judgment: the reviewer reads the `neighbours` join for a gap that spans two sessions | R1, D5 |
| A10 | The documents and the roadmap match the build, and the run-start section and the outbox item both carry the read-the-sender line | check: `uv run python scripts/check_docs.py`; check: `grep -n "read the current shared sender" docs/ai-dlc/roadmap/park-company.md` prints two lines (the run-start line and the outbox item's first line); judgment: the reviewer reads the diff against R4 and R5 | R4, R5 |
| A11 | No model, macro, Makefile, profile, contract, sample or site file changed | check: Verify-by step 7 | Gate 1 out of scope |

## Open points

Each open point carries a recommended answer, which the build follows unless the project owner or the director rules
otherwise.

- **O1. Where the alert address comes from. Resolved.**
  - **Resolution.** The repo never holds or passes the address: no `--to`, and no fallback that passes one. The shared
    sender reads its recipient from an environment variable in its own configuration, and that value is never
    committed. Today the sender takes its recipient from local configuration, so moving it to an environment variable
    is a project-owner follow-up outside this repo, until it is done. It blocks nothing here.
  - **Gain:** no address in the repo, its settings or a process listing, and one place to change it.
  - **Cost:** the outbox cannot show an alert reaching the project owner until the sender's follow-up is done.
- **O2. What triggers a digest. Resolved.**
  - **Resolution:** a production run sends a digest only when an error-level test failed (or dbt errored). Warnings,
    including R2's save-boundary rows, are listed inside any digest that is sent but never send one alone. In dbt a
    test with rows at warn severity ends with status `warn`, not `fail`, so the ruling's "failed" means error-level.
  - **Gain:** R2 warns on almost every real multi-session month, so this avoids a near-daily email and keeps alerts
    within the sender's shared limit of 10 sends a day.
  - **Cost:** a warning alone never reaches anyone by email. It is read in the build log or the stored rows.
- **O3. Which save to replay (D5).**
  - **Recommended:** the save the session before the gap loaded.
  - **Alternative:** the latest save that session wrote before the gap (`stg_save_written`). It is closer to the gap,
    so the replay is shorter. But a session's last save is written on its last day, which may fall after the gap's
    start, so it needs a game-date rule and a second join.
  - **Gain of the recommendation:** the save always predates the gap.
  - **Cost:** a longer replay when the session ran a long time before the gap.
- **O4. R2's second reason.**
  - **Recommended:** keep `abandoned_session` for days held only by a session off the kept path, a fork (D4).
  - **Gain:** no captured day goes missing from both lists.
  - **Cost:** no test exercises that value, because the sample has no fork.
  - **Alternative:** one fixed reason for every row, which is simpler but mislabels a fork's day as a save boundary.
- **O5. Stored failure rows (D6).** Gate 1 does not mention storing rows.
  - **Recommended:** store them for both tests.
  - **Gain:** Verify-by and the outbox read real rows.
  - **Cost:** two more tables in every built warehouse.
  - **The check.** If the T3 worker finds the publish audit counting the stored rows as parks, the worker stops and
    reports.
- **O6. The outbox folder (for the later outbox item).**
  - **Recommended:** `warehouse/outbox/`, because `/warehouse/` is already git-ignored (`.gitignore`).
  - **Gain:** no `.gitignore` change.
  - **Cost:** the outbox item must confirm that `warehouse_guard` and the publish swap ignore non-DuckDB files in
    that folder.

## Tickets

Four tickets. The tests come first and the documents last. Each ticket owns at most one behaviour.

| Ticket | Owned files | Golden path | Acceptance | Done-condition | After | Shape |
|---|---|---|---|---|---|---|
| T1 Error test | `tests/dbt/assert_every_day_of_a_closed_month_was_captured.sql` | `assert_every_kept_statement_has_a_company_date.sql`; `rows_on_sample.sql:10` | check: PASS on the `ci` sample; check: `sqlfluff lint` on the file; judgment: header states scope, clock, severity | the quick build passes, and R1 is PASS | none | one singular test, offline dbt |
| T2 Warn check | `tests/dbt/assert_every_captured_day_of_a_closed_month_is_kept.sql` | `assert_park_registry_superseded_delivery_date_matches_file_name.sql` | check: WARN with 2 rows on a fresh `ci` build (Verify-by step 2); check: `sqlfluff lint` | the exact May day and both company dates are written into this spec's R2 and handed to T3 | none | one singular test, offline dbt |
| T3 Per-target pytest | `tests/test_dbt_missing_day.py` | `tests/test_company_year.py`; `tests/test_dbt_environments.py:276-292` | check: R3 cases (a) to (h); check: Verify-by step 5 (10 of 10); check: `uv run mypy tests` clean | `uv run pytest tests/test_dbt_missing_day.py` exits 0 | T1, T2 | one pytest file, real dbt; route: claude (severity at parse time, per-target setup) |
| T4 Documents and roadmap | `docs/CONVENTIONS.md`, `ARCHITECTURE.md`, `CHANGELOG.md`, `docs/ai-dlc/roadmap/park-company.md` | `docs/ai-dlc/specs/marts-month-summaries.md`, R10 | check: A10; check: `make check` exits 0 | `make check` exits 0 on the merged branch | T3 | four documents, one behaviour (documents match the build); route: claude (roadmap wording) |

**The quick build** (T1, T2):

```sh
uv run python -m openrct2_analytics.ingest.warehouse_guard --root warehouse warehouse/dev/dev.duckdb
uv run dbt build --profiles-dir . --target dev --select +<test> --indirect-selection cautious \
  --vars "{parquet_root: data/sample/rehearsal}"
```

The sample counts are always confirmed from the fresh `ci` build of Verify-by step 2, never from `dev`.
