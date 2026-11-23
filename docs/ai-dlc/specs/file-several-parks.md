# Spec: file several new parks in one play

**Bottom line.** Today `make auto-file` hands every new company park to one after-play run, and a run that would
register two company parks is refused, so a play that opened two new parks is not filed. After this change:
- When two or more new parks wait, `make auto-file` shows each park's name and played game days and asks whether it was
  opened first, second (and so on) or is a Sandbox park. It refuses before writing anything when the answers do not
  match the order of each park's first recorded session.
- It plans every park's company start year and runs every refusal check for all parks first, then registers the parks
  one at a time, each re-checked under the landing lock, then runs the after-play steps once.
- A failure after the first registration, on either path, names the parks already registered and the exact rerun
  command, exits 1 (130 for an interrupt) and never prints "Nothing was changed" itself. A rerun files the rest without
  registering a park twice and without a question for a park already answered; a park still waiting gets the year the
  rule gives at the rerun, which equals the planned year when no data changed.
- One new park keeps today's path, unasked. `make register-parks` and `make after-play` keep their one-company-park rule.
  The command line, the Makefile, the data contracts, the dbt models and the plugin do not change.

- Status: revised after review, 2026-11-16 (findings and fixes: `docs/ai-dlc/ledger/file-several-parks.md`). Slug
  `file-several-parks`. No tickets yet.
- Contract map: `docs/ai-dlc/contracts/file-several-parks.md` (cited below as "map", with its item number).
- Owner rulings: the preflight of 2026-11-16, recorded in the map's "Owner rulings" section (cited as "ruling").
- Roadmap item: `docs/ai-dlc/roadmap/park-company.md` lines 171-175 (cited as "roadmap").
- Builds on ADR 0050 (`docs/adr/0050-company-start-year-from-the-register-command.md`) and ADR 0051
  (`docs/adr/0051-launcher-files-each-play.md`), and the earlier spec `docs/ai-dlc/specs/play-launcher-autofile.md`.

## Stated goal

The roadmap item, quoted verbatim from `docs/ai-dlc/roadmap/park-company.md` lines 171-175 (develop `ed85773`):

```text
- [ ] **File several new parks in one play** — problem: `make auto-file` hands every new company park to one after-play run, which refuses several company parks (`auto_file.py` hands one list to after-play; `register_parks.py` refuses it), so a play that starts two new parks is not filed (seen 2026-11-15) · outcome-link: outcome (b) item 3 · verify: agent ·
      pass/fail: with two new parks waiting from one play, `make auto-file DATA_SET=company COUNT_AS=company` shows each park's name and played game days and asks, for each, "opened first", "opened second" or "Sandbox"; it collects every answer before writing anything; every refusal check runs for all parks before the first registration; it then registers them one at a time in the given order, each later company park with the year `next_start_year` gives after the previous registration (the first park's latest held year plus one), and runs the after-play steps once; each park's "is new" line prints its own year. If a later registration still fails, the message names the parks already registered (never "Nothing was changed") and a rerun files the rest without changing a year or registering twice. Tests: two company parks in either order; one company and one Sandbox; cancelling at the question; a failure after the first registration and its rerun; each fails before the change. A short ADR amends ADR 0050 decision 6 and ADR 0051 decision 3; `make check` passes.
      riskiest-assumption: two company parks registered moments apart build cleanly, including the year close · cheapest-test: extend `tests/test_dbt_two_parks.py` with planted data in which the second park starts while the first has an unfinished year, and assert the expected start year and a passing build · assumption-status: untested
      outcome-measure: plays refused for several company parks, 1 seen on 2026-11-15, target 0; read from `make auto-file` exits
      touches: `src/openrct2_analytics/ingest/auto_file.py`, `tests/test_auto_file.py` (463 lines; split it if it would pass the 500-line limit), `tests/test_dbt_two_parks.py`, a new ADR, `ARCHITECTURE.md`, `AGENTS.md`
```

One-line goal: one company play that opened two or more new parks is filed by one `make auto-file` run.

## 1. Requirements

Words used below:
- A **new park** is a waiting park that is not registered, has a session that is this play's (a session missing from
  `local/auto-file/converted-before.json`, ADR 0051 decision 2), and has no stored answer (R8).
- A park's **first recorded session** is its earliest `session_start` row by `emitted_at`, as
  `register_parks._source_rows` already orders parks (map item 2).
- The **several-park path** is the new flow of R4 to R8. **Today's path** is the current flow: one call to after-play,
  which registers the parks itself.

Each criterion is tagged `check:` (a test or command proves it) or `judgment:` (a reviewer looks). Test names are
proposals; the ticket may rename them but keeps one test per criterion.

- **R1 Ask per park only when two or more new parks wait.** (ruling; roadmap pass/fail)
  - With one new park, nothing changes: it takes `COUNT_AS` with no question, and today's path files it.
    `check:` the existing `test_this_play_only_takes_count_as` passes unchanged.
  - With two or more new parks, each new park is asked, in the order `auto_file._classify` returns, with this text
    (`k` is the number of new parks; the ordinals are the English words first, second, third, ...):
    ```
    Park <name> (<id>), <n> game days played, is new in this play. Which is it?
    1. Opened first
    2. Opened second
    ...
    k. Opened <k-th>
    k+1. Sandbox
    ```
    An answer outside 1 to k+1 repeats the question, as today's questions do. The question is asked whatever `COUNT_AS`
    is (section 12, item 2). `check:` `test_two_new_parks_are_each_asked_with_days_played`.
  - Every answer is collected before anything is written. `check:` the same test asserts the fake register function was
    not called before the last answer.
  - Parks from an earlier play keep ADR 0051's question (Company, Sandbox, Don't file now), and a registered park keeps
    its registration. `check:` the existing tests for those questions pass unchanged.
- **R2 Played game days** of a park are the number of distinct game dates (`game_year`, `game_month`, `game_day`) in its
  converted `park_snapshot` rows, over all its converted sessions; a park with no `park_snapshot` row, or no
  `park_snapshot.parquet` file at all, has 0 (the file guard of `company_managed_years`, `managed_years.py:102-103`, is
  kept; DuckDB would otherwise raise on a missing file). (ruling) The existing auto-file fixtures plant only
  `session_start`, so every new test of R1 to R11 also plants `park_snapshot` rows (section 5).
  `check:` `test_played_game_days_counts_distinct_game_dates` (repeated dates counted once, two sessions on one date
  counted once, a park with no snapshot row gives 0, a missing file gives 0).
- **R3 The order answers must match the first recorded sessions.** (ruling) Answer "Opened n" is correct only when the
  park's first recorded session is the n-th earliest among the asked parks, and each n is given at most once. Ranks
  count every asked park, Sandbox ones included, because that is the order in which the parks were opened (section 12,
  item 1). Any mismatch or repeat is refused before anything is written:
  `auto-file refused: order: Park <label> was answered as opened <given>, but its first recorded session is the <actual> of this play's new parks. Nothing was changed.`
  followed by today's rerun line `To file it, run: make auto-file DATA_SET=company COUNT_AS=<x>`; exit 2.
  `check:` `test_order_answers_that_do_not_match_are_refused_before_writing` (a swapped pair and a repeated rank; the
  folder tree is unchanged; the fake register function and `file_with` are never called).
- **R4 Plan everything, then check everything, before the first registration.** (ruling; roadmap) When the chosen
  parks hold two or more company parks to register, auto-file:
  1. plans every park's start year with a pure function that treats each earlier park in the order as registered (its
     registry row and its managed days count), so park n's year is the year `register_parks.next_start_year` would give
     after parks 1 to n-1 were registered. A simulated registration is built exactly as `_delivery` writes its row
     (`register_parks.py:351-354`): the planned start year, the game year origin from `_source_rows`, the practice flag
     and data set `company`; the inputs (labels, save sequence, session start years) are the ones `read_managed_inputs`
     gives, the same inputs `company_managed_years` reads;
  2. runs, for all parks, every refusal that `make register-parks` would give before its lock: the registry feed check,
     a park registered as another data set (`mismatch`), a staged delivery left over (`leftover`), a company raw file
     holding a session never converted (`not-converted`), a typed-year park whose first session is not in game year 1
     (`start-year-origin`), and fewer free delivery names today than parks to register (`no-free-name`). Today
     `not-converted` is raised only when a company park is already registered (`_floor_info` runs in the `else` branch of
     `start_years`, `register_parks.py:273-283`; with an empty registry it returns early). The plan runs the
     raw-file check for park 2 and later as if the earlier parks of the plan were registered, whether or not the
     registry holds a company park today, so park 2 cannot refuse after park 1 landed;
  3. refuses with exit 2, today's refusal text under the `auto-file refused:` prefix and "Nothing was changed." when any
     check fails, with nothing written.

  `check:` `test_plan_gives_each_later_company_park_the_year_after_the_previous` (pure, in
  `tests/test_start_year_plan.py`), `test_a_refusal_for_the_second_park_stops_before_the_first_registration` (the
  second park began in game year 9; the folder tree is unchanged), and
  `test_an_unconverted_raw_session_refuses_before_the_first_registration` (empty registry, two new company parks, a
  company raw file holding a session that was never converted; refused with `not-converted`, folder tree unchanged).
- **R5 Register one park at a time, then run after-play once.** (ruling; roadmap) Parks are registered in
  first-recorded-session order, each in its own registration (one delivery file each), through the same code
  `make register-parks` runs, so each re-checks its year under the landing lock (ADR 0050 decision 6). The first company
  park of the company is registered with no year (2000); every later company park passes its planned year as
  `START_YEAR`. Sandbox parks take no year. After the last registration, auto-file calls after-play once with every
  waiting park listed and no `--start-year`; after-play's register step then prints
  `after-play: register: no waiting park needs registering` and runs the other steps.
  `check:` `test_two_company_parks_are_registered_one_at_a_time` (two delivery files, years 2000 and the year after
  the first park's latest held year; one `file_with` call), run for both orders (the park whose ID sorts later was
  opened first, and the reverse).
  - Prints: `register` raises on refusal and prints nothing; it returns the name of the delivery file it wrote.
    `register_parks.main` keeps today's lines ("Registered 1 park(s) in <name>." and "Park X: company start year Y
    (START_YEAR)."). Auto-file prints only its own R6 and R7 lines, so the "(START_YEAR)" wording never appears in an
    auto-file run.
  - `check:` `test_a_changed_floor_is_refused_under_the_lock`. The test patches `lock.hold_lock`, as
    `tests/test_register_parks_start_year_lock.py:43` does, so that a row raising the floor lands after park 2's
    pre-lock year check (`register_parks.py:385`) and before the under-lock re-check (`:396`). It asserts the
    refusal, that the landing lock is released and that no delivery file was written for park 2. Removing the
    under-lock check turns the test red; a row landed before the call would be caught by the pre-lock check and prove
    nothing.
- **R6 Each "is new" line prints its own year.** (roadmap) Before the first registration, one line per park to
  register, in registration order, in today's format:
  `auto-file: park <label> is new; registering it as <company park, start year <Y>|a sandbox park>.`
  `check:` asserted in `test_two_company_parks_are_registered_one_at_a_time`.
- **R7 A failure after the first registration says what was filed.** (ruling; roadmap) This covers both paths: the
  several-park path, and today's path, which lets one after-play call register one company park and the Sandbox
  parks and then run contracts and transform.
  - **How auto-file learns what landed.** It keeps the registered parks it read at the start of `_file` and, when a
    failure ends the run, reads the registry again (`register_parks.registered_parks`). A park listed now and not at
    the start was registered by this run. This holds when an interrupt arrives after a delivery was renamed into
    place and before the registering call returned (`register_parks.py:406-411`), and when after-play registered the
    parks itself; a counter in the loop would miss both. The year and choice shown for each park are the text of its
    R6 line.
  - **When nothing landed**, today's behaviour holds: the refusal texts, "Nothing was changed.", and exits 2, 1 and
    130 as they are. A waiting list that changed during the questions is such a case too. `after_play.check_can_start`
    (`after_play.py:72-84`) does not compare the list; the parks-missing refusal is raised later, in `_to_register`
    (`:92-96`). So on the several-park path, just before its first registration, auto-file calls `check_can_start`
    again and compares the waiting parks in the status it returns with the parks the player answered for. If they
    differ (a park added or removed during the questions, which can take a long time), it refuses before writing
    anything: exit 2, `auto-file refused: waiting-list: the waiting parks changed while you were answering (added:
    <ids or none>; removed: <ids or none>). Nothing was changed.`
    `check:` `test_a_park_added_between_the_questions_and_the_first_registration_is_refused` (a fake that adds a
    waiting park after the last answer; asserts the line, exit 2, no delivery written, no `answers.json`).
  - **When at least one park landed** (a registration refused or failed, the run was interrupted, or after-play
    exited non-zero), auto-file prints:
    ```
    auto-file failed: <reason>: <detail>.
    auto-file: already registered by this run: park <label> as <company park, start year <Y>|a sandbox park>[; park ...].
    To file the rest, run: make auto-file DATA_SET=company COUNT_AS=<x> (run it here; the launcher starts a new play)
    ```
    For an interrupt the first line is `auto-file interrupted.`. After an after-play failure the first line is left out,
    because after-play has printed its own, and one line is printed in its place: `auto-file: after-play stopped, and
    these parks are already registered.` Auto-file's own text never contains "Nothing was changed".
  - **After-play's own lines after a landed registration.** `after_play.main` gains one optional keyword argument,
    `registrations_landed: bool = False`. Auto-file passes `registrations_landed=True` on every after-play call made
    after a registration landed (the several-park path always; today's path never, because that call does the
    registering itself and a refusal before any step changed nothing). When true, `main` leaves the " Nothing was
    changed." suffix off its refusal lines (`after_play.py:211-216`, the `Refused`, `register_parks.Refused` and
    `ConfigError` handlers). At its default, after-play's output, exit codes and one-company-park refusal are
    unchanged. So the phrase never reaches the player after a landed registration, whatever after-play refuses.
    `check:` `test_an_after_play_refusal_after_a_landed_registration_has_no_nothing_was_changed` (real `after_play.main`
    through auto-file; a refusal raised after the registrations; asserts the combined output holds no "Nothing was
    changed" and holds the R7 lines), and the existing after-play tests, which stay as they are, prove the default.
  - **Exit code**: 130 for an interrupt (after-play's 130 too); otherwise 1, including after-play's exit 2 after a
    landed registration, so that exit 2 keeps meaning "nothing changed" (section 12, item 3).
  - **Errors caught for every registration**, park 1 included. `auto_file.main`'s except chain (`auto_file.py:295-312`)
    gains: `lock.LockTaken` (`auto-file refused: lock-taken: <error>; see ARCHITECTURE.md "Stale locks". Nothing was
    changed.`, exit 2, as `register_parks.main` prints it); `register_parks.CheckFailed` (`auto-file failed:
    check-failed: <error>`, exit 1); and `csv.Error` and `UnicodeDecodeError` added to the `auto-file failed: io:`
    tuple. None ends in a traceback. When parks had already landed, the R7 lines above replace the plain texts.
  `check:` `test_a_failure_after_the_first_registration_names_the_filed_parks` (parametrized: a refusal, a held landing
  lock, `CheckFailed`, `csv.Error`, an `OSError`, a `KeyboardInterrupt`, after-play exit 1, after-play exit 2 printing
  its refusal line; the last two on the several-park path and on today's path with a fake `file_with` that really
  registers first); each asserts the exact output, the exit code and that auto-file's own lines never contain "Nothing
  was changed". `check:` `test_a_failure_at_the_first_registration_is_caught` (a landing lock held and a failed delivery
  check at park 1; "Nothing was changed." is printed, exit 2 and 1, no traceback, tree unchanged).
- **R8 A rerun files the rest.** (ruling; roadmap)
  - **Which answers are stored.** Whenever any per-park question (R1) was asked, on either path, auto-file writes
    every answer of this run to the git-ignored `local/auto-file/answers.json` (park ID to `company` or `practice`,
    written through a temporary file and renamed) just before the first registration or, on today's path, just before
    the after-play call. Answers to ADR 0051's earlier-play and conflict questions are stored too, so a rerun asks
    nothing already answered. A run that asked no per-park question writes no file.
  - **Removal.** `answers.json` is removed with `converted-before.json` after exit 0, on the "nothing is waiting"
    path, and by `--record` (`auto_file.py:98-114`), so a new play starts clean.
  - **On a rerun**, a waiting park with a stored answer takes it with no question, and a registered park of this play
    whose stored answer equals its registration gets no conflict question (ruling: "a rerun keeps a registered park's
    stored choice without a conflict question"). This holds for a Sandbox park too, which is the case the stored file
    exists for (`auto_file.py:195-199` asks a conflict question when the saved choice differs from `COUNT_AS`). An
    answers file that cannot be read or parsed is ignored with one printed line, as `converted-before.json` is
    (ADR 0051 decision 4): `auto-file: answers.json could not be read; asking again.`
  - **Years.** A registered park keeps its year and gets no second row. An unregistered park gets the year
    `next_start_year` gives at the rerun, which equals the planned year when no data changed in between; the spec does
    not promise more (the roadmap's "without changing a year" holds for registered parks). A launcher run between the
    failure and the rerun runs `--record`, which removes the answers and turns the park still waiting into an earlier
    play's park; the R7 rerun line says to run the command from the window, not the launcher.

  `check:` `test_rerun_after_a_partial_failure_files_the_rest` (first run fails at the second registration; the rerun
  asks nothing, writes one more row with the planned year, leaves park 1's row as it was, and exits 0).
  `check:` `test_rerun_keeps_a_stored_sandbox_choice_without_a_conflict_question` (`COUNT_AS=company`, park 1 answered
  Sandbox and registered, park 2 failed). `check:` `test_an_unreadable_answers_file_is_ignored_with_one_line` (a
  corrupt file: the exact line, then the questions are asked). `check:` `test_answers_file_is_removed_after_success_and_by_record`
  (exit 0, the "nothing is waiting" path, and `--record` each leave no `answers.json`). `check:`
  `test_an_earlier_play_company_park_and_a_new_company_park_are_filed_in_order` (section 12, item 5: the earlier park
  answered Company with no order question, the new park Opened first; two rows, in first-session order).
- **R9 A third company park follows the same chain.** (ruling) `check:` `test_three_company_parks_get_three_years`
  (one test; three rows with years 2000, F1 + 1 and F2 + 1).
- **R10 Mixed answers.** (roadmap) One company park and one Sandbox park from one play: asked per R1, checked per R3,
  and filed by today's path, because only one company park registers. Today's path also writes `answers.json` (R8) and
  reports a landed registration after a later failure (R7): after-play registers both parks before contracts, so a
  contracts or transform failure leaves a delivery holding both parks. `check:`
  `test_one_company_and_one_sandbox_new_park_file_in_one_after_play_run` (one `file_with` call holding both parks).
  `check:` `test_a_mixed_play_failing_after_registration_reruns_without_a_conflict_question` (a fake `file_with` that
  really registers both parks and then returns 1; the output is the R7 text and exit 1; the rerun with
  `COUNT_AS=company` asks no question for the Sandbox park and files nothing twice).
- **R11 Cancelling at the question changes nothing.** (roadmap) Ctrl-C or end of input at any per-park question exits
  130 with `auto-file interrupted. Nothing was changed.` (today's text), and the tree is unchanged.
  `check:` `test_cancelling_at_a_per_park_question_changes_nothing`.
- **R12 The other commands keep their rule.** (ruling; map item 2) `make register-parks` still registers at most one
  non-sandbox park per run, and `make after-play` keeps its `several-company-parks` refusal and text. `check:` the pinned
  tests `tests/test_register_parks_start_year.py` (lines 146-149, 359, 446) and `tests/test_after_play.py` (lines
  307-314) pass with their assertions unchanged. The only test lines that change are imports and calls of moved names:
  `register_parks.next_start_year` at `tests/test_register_parks_start_year.py` lines 219 and 226 keeps working because
  `register_parks` re-imports it (with `__all__` or an `as` alias if it no longer uses the name, so ruff F401 stays
  quiet); `tests/test_register_parks_start_year_order.py` and `tests/test_register_parks_start_year_lock.py` import
  no moved name and do not change.
- **R13 The command line and the Makefile stay as they are.** (map item 1 and "Integration points") `check:`
  `git diff --exit-code develop -- Makefile tests/test_makefile_guards.py launcher/` prints nothing.
- **R14 The cheapest test runs first.** (roadmap riskiest-assumption and cheapest-test; ruling) `tests/test_dbt_two_parks.py`
  gains one case, `test_second_park_registered_as_company`, on the `company` target with `OPENRCT2_PUBLISH_RUN_ID`
  set, as the existing rehearsal case does. It plants both parks from game year 1: `tests/two_park_support.py:39-44`
  gives park 2 a game year origin of 9, which `register_parks.py:324-336` refuses for a later company park, so the
  helper gains a parameter for the origin (and for the data set that `second_park_registry` hard-codes as
  `rehearsal`; the existing rehearsal-target cases at `tests/test_dbt_two_parks.py:361-371` keep their values by
  default). Both parks are registered as `company` with no note: park 1 with year 2000 and park 2 with the start year
  the real rule gives over the planted data while park 1 has an unfinished year. The case computes that year by
  calling `next_start_year` on the planted files before it writes park 2's registry row, and asserts it equals the
  expected value. It then asserts a passing build, the `int_park_years__year_close` rows, the result of the
  year-close singular test (the CLOSE case of `tests/test_dbt_two_parks.py:308-380`), and that the built registry
  holds park 2 as `company`. It runs alone before any other ticket; if it fails, this slice stops (roadmap "Run 1
  order"). The file is 434 lines: the case and its planted data go into a new `tests/test_dbt_two_parks_company.py`
  from the start, so no file passes 500 lines. `check:`
  `.venv/bin/python -m pytest tests/test_dbt_two_parks_company.py -k registered_as_company`.
- **R15 Each new filing test fails before the change.** (roadmap; engineering standards) `check:` the new tests of
  R1 to R13 are run once against the `ed85773` source and every one fails; the ticket report lists the failures.
  The R14 probe is exempt: it tests existing dbt behavior, changes no model and may pass before the change.
- **R16 Records.** (map "Docs that must change"; brief) A new ADR, `docs/adr/0055-file-several-new-parks-in-one-play.md`,
  amends ADR 0050 decisions 6 and 7 and ADR 0051 decisions 2, 3 and 4 (section 3); the doc lines of section 3 are
  updated in the same change.
  `judgment:` a reviewer reads the ADR and each listed doc line against R1 to R13 and finds no stale claim (for example
  "Only one company park" presented as a limit of `make auto-file`).
- **R17 The gate passes.** (roadmap) `check:` `env -u VIRTUAL_ENV make check` exits 0 in the ticket worktree.

## 2. Design

### 2.1 Placement plan

| New rule or piece | Owner | Reused or extended | Layer |
|---|---|---|---|
| The floor rule (F, the park that sets it) and the plan of start years with earlier parks simulated as registered (R4.1) | new `src/openrct2_analytics/domain/start_year_plan.py`: `floor_year(start_years, managed) -> (F, setter)` and `plan_years(order, registrations, managed_inputs) -> list[Planned]`. Pure: no file, no clock. | `company_years.managed_years_by_park` and `Registration` (`domain/company_years.py:32-100`), called once per planned company park with the simulated registrations added | domain |
| Reading the managed-day inputs once | `managed_years.py`: the reads inside `company_managed_years` (`managed_years.py:99-133`) move into `read_managed_inputs(parquet_dir, registry_dir) -> ManagedInputs`, which `company_managed_years` calls (no behaviour change) | existing queries | ingest |
| Played game days (R2) | `managed_years.py`: new `played_game_days(parquet_dir) -> dict[str, int]` | `table(parquet_dir, "park_snapshot")` | ingest |
| The start-year rules, moved out of a full file | new `src/openrct2_analytics/ingest/start_year.py` takes `_registered_company_parks`, `_floor` (now calling `floor_year`), `_floor_info`, `next_start_year`, `start_years`, `_check_later_year`, `_check_origin`, plus `Refused` and `_source_rows`, which they need. `register_parks` imports them back (`register_parks.Refused` stays the same class, so `auto_file.py:301` and the tests keep working). `start_year.py` never imports `register_parks`. New here: `plan_start_years(project_dir, order) -> list[Planned]`, which reads the inputs, calls `plan_years` and raises the existing `not-converted` (also for an empty registry, R4.2) and `start-year-origin` refusals. | everything listed is moved, not copied | ingest |
| The registration refusals for all parks before the lock (R4.2) | `register_parks.py`: new `check_registrations(project_dir, today, count) -> None` runs `_prepare` once and refuses `no-free-name` when fewer than `count` names are free today (the raw-file `not-converted` check for park 2 and later is in `plan_start_years`, R4.2) | `_prepare` (`register_parks.py:109-125`), `_free_name` (`:101-106`) | ingest |
| One registration that raises instead of printing a refusal | `register_parks.py`: `_run` (`:358-415`) becomes public `register(project_dir, today, practice, *, parks, start_year) -> str`, which prints nothing, raises on refusal and returns the delivery file name; `main` calls it, prints today's lines and keeps its text and exit codes | `_run` as it is | ingest |
| Per-park question, order check, the plan, the sequential registrations, `answers.json` writing and reading (R1, R3-R6, R8, R9, R11) | new `src/openrct2_analytics/ingest/several_parks.py`, called by `auto_file._file` when two or more new parks wait or the chosen parks hold two or more company parks to register | `auto_file._answer`, `_Park`, `SHOWN`, `CHOICE_NAMES`; `register_parks.register`, `check_registrations`; `start_year.plan_start_years`; `managed_years.played_game_days` | ingest |
| Choosing the path; the stored answers on a rerun; `--record` removing `answers.json`; the landed-parks read and the R7 lines on both paths; the extra caught errors | `auto_file.py` (`_choose` `:184-202`, `_file` `:224-258`, `_record` `:98-114`, `main` `:295-312`). `_needs_question` and `_choose` hold the same rule twice today (map item 4). The change makes `_choose` the one home by splitting it into a no-I/O step that returns the questions needed (which parks, and which text) and an asking step. `_file` keeps its no-terminal refusal and `capture_session.discard_typed_input` before the first question, now decided by the first step, so the tests at `tests/test_auto_file.py:379-393` keep passing. `_needs_question` is dropped. | existing classification | ingest |
| New seam `register_with` on `auto_file.main` (default `register_parks.register`) | `auto_file.py` (`:270-277`) | the existing `ask`, `file_with`, `is_terminal` seams | ingest |
| ADR and docs | section 3 | | docs |

**Why two paths, not one.** Today's path stays for at most one company park to register, and the several-park path
runs only for two or more. Gain: every existing auto-file test and pinned string stays as it is, as the ruling "one new
park keeps today's COUNT_AS path unasked" asks. Cost: two ways to reach `register_parks`, through after-play and
through `several_parks`; both call the same registration code, so the rule still has one home.

**Why a new `start_year.py`.** `register_parks.py` is 496 lines, and the gate allows 500 (`docs/CONVENTIONS.md`
section 3; `scripts/check_file_sizes.py`). The earlier spec named this split for the moment the file would pass 500
(`docs/ai-dlc/specs/play-launcher-autofile.md`, placement plan). Gain: room for `check_registrations` and `register`,
and the year rules in one file. Cost: callers and tests change their imports in the same ticket
(`after_play.py:113`, `auto_file.py:210`; of the tests only `tests/test_register_parks_start_year.py` uses a moved name, R12).

**Why a pure plan in `domain/`.** The ruling asks for "a pure plan, simulated registration of earlier parks". Managed
days count only for registered parks (`domain/company_years.py:75-83`), so park 2's year cannot be read from files
before park 1 is registered; the plan adds park 1's planned row to the registrations it passes to
`managed_years_by_park`. Gain: the plan is tested without files, and `register_parks._floor` and the plan share
`floor_year`. Cost: one more module.

Dependents that change in the same change: `after_play.py` (imports for the move, plus the optional argument of R7) and
`auto_file.py`;
`tests/test_register_parks_start_year.py` (the `next_start_year` calls, R12; its `_order` and `_lock` siblings do not
change); `tests/test_auto_file.py` (split, section 5). No dbt
model, contract, plugin file, Makefile line or launcher line changes. No dependency is added.

### 2.2 Behaviour of `make auto-file DATA_SET=company COUNT_AS=<x>`

Steps 1 to 4 are today's (ADR 0051): the refusals before any question, reading the waiting sessions, the registry and
`converted-before.json`, and classifying each park once. Then:

5. **Stored answers.** A readable `answers.json` gives a waiting park its stored choice with no question. A registered
   park of this play whose stored answer equals its registration gets no conflict question. An unreadable file prints
   its one line (R8) and is ignored.
6. **Choose.** The no-I/O step returns the questions needed. If any is needed, the no-terminal refusal and
   `discard_typed_input` run first, as today; then the asking step asks. Earlier-play parks and conflicts are asked as
   today. When two or more new parks remain, each is asked the R1 question; otherwise the one new park takes `COUNT_AS`.
7. **Order check** (R3) over the parks asked the R1 question.
8. **Path.** `_file` reads the registered parks (the "before" set of R7). With at most one company park to register:
   - the R6 lines, and `answers.json` written when a per-park question was asked (R8);
   - today's one after-play call;
   - on a non-zero code or an error, the R7 read: parks registered now and not before are reported (R7, R10).

   With two or more company parks to register:
   - `plan_start_years` over every park to register, in first-recorded-session order, each with its choice (park ID, practice flag): a Sandbox park takes no year and no origin check, and its days never count (R4.1, R4.2 year checks; R5);
   - `check_registrations(project_dir, today, count)` (R4.2), and `after_play.check_can_start` again with the waiting
     parks of its status compared with the answered parks (R7);
   - the R6 lines;
   - write `answers.json` (R8);
   - for each park in order, `register_with(...)`;
   - `file_with(["--data-set", "company", "--parks", <every waiting park>], registrations_landed=True)`;
   - on any failure or interrupt after the first write, the R7 read and lines.
9. **After exit 0**, `converted-before.json` and `answers.json` are removed.

## 3. Files to change

- `src/openrct2_analytics/domain/start_year_plan.py` (new), `src/openrct2_analytics/ingest/start_year.py` (new),
  `src/openrct2_analytics/ingest/several_parks.py` (new).
- `src/openrct2_analytics/ingest/auto_file.py`, `register_parks.py`, `managed_years.py`, `after_play.py` (imports for the move, and one optional
  argument `registrations_landed` on `main`, R7; no behavior change at its default).
- Tests: `tests/test_auto_file.py` (split), `tests/auto_file_support.py` (new), `tests/test_auto_file_several_parks.py`
  (new), `tests/test_start_year_plan.py` (new), `tests/test_managed_years.py` (for
  `played_game_days`), `tests/test_dbt_two_parks_company.py` (new, R14) with `tests/two_park_support.py` (new
  parameters), and the `next_start_year` lines of `tests/test_register_parks_start_year.py` (R12).
- `docs/adr/0055-file-several-new-parks-in-one-play.md` (new; next free number after 0054). It amends:
  - ADR 0050 decision 6: one register run still takes at most one non-sandbox park, but `make auto-file` chains several
    runs, so "register one with `make register-parks PARKS=...` first" is no longer the only way;
  - ADR 0050 decision 7 ("every refusal leaves the folder tree unchanged"): a refusal or failure after the first
    registration of an auto-file run now leaves the earlier rows written and exits 1 (R7); `make register-parks` keeps
    the decision as it is;
  - ADR 0051 decision 2: with two or more new parks, each is asked instead of all taking `COUNT_AS`;
  - ADR 0051 decision 3: with two or more company parks, auto-file registers them itself, one at a time, before one
    after-play call;
  - ADR 0051 decision 4 (the record file's life): `answers.json` lives beside `converted-before.json` and is removed
    with it (R8).
  ADRs 0050 and 0051 are not edited (ADRs are superseded or amended by a new record, not changed).
- `AGENTS.md` lines 49 (`make register-parks`), 51 (`make after-play`) and 52 (`make auto-file`); `ARCHITECTURE.md`
  lines 364-368, 492 and 601-609; `README.md` lines 74 and 78; `docs/CONVENTIONS.md` line 67 (the module map line
  "`auto_file.py` files a launcher play through after-play" gains the several-park path, `start_year.py` and
  `several_parks.py`; line 66 names `company_years.py` as the domain example and gains `start_year_plan.py`) (line
  numbers on `ed85773`).
- `CHANGELOG.md`: one entry, as the earlier filing change added one.
- `docs/ai-dlc/roadmap/park-company.md` lines 171-175: the item's status, in the final ticket, by the roadmap procedure.

## 4. Contracts and pinned test strings

- **Unchanged contracts.** Exit codes 0, 1, 2, 130 (map item 1); every refusal text that exists today; the auto-file
  command line and the Makefile target (`Makefile:298-301`, pinned by `tests/test_makefile_guards.py:264-292`);
  `converted-before.json`'s format; the registry delivery format and the data contracts.
- **Pinned strings that stay byte for byte:** `tests/test_auto_file.py` lines 22-34 (`EARLIER_A`, `NOT_NOW_A`,
  `RERUN_COMPANY`, `MISSING`), 243-250 (conflict text), 283 and 305, 390-393 (no terminal), 404-415 (interrupt before
  any registration), 459-463 (`not-converted`); `tests/test_register_parks_start_year.py` 146-149, 359, 446
  (`SEVERAL`); `tests/test_after_play.py` 307-314. No existing auto-file test has two new parks from one play (the
  fixtures at `tests/test_auto_file.py` lines 198-448 were read), so none sees the new question.
- **New pinned strings** (each asserted exactly by a new test): the R1 question, the R3 `order` refusal, the R7 lines,
  and the line printed for an unreadable `answers.json` (R8's test).
- **One changed behavior of today's path:** after a registration landed and a later after-play step failed, the
  player now also sees the R7 lines and, for an after-play exit 2, exit 1. No existing test plants that case; the
  existing `[(1, True), (2, True), (0, False)]` parametrization at `tests/test_auto_file.py:433` uses a fake that
  writes no registry row, so nothing landed and its output and codes stay.
- **"Nothing was changed."** stays on every refusal before the first registration and is never printed after one (R7).
- **New local file:** `local/auto-file/answers.json` (git-ignored, under the already ignored `local/`). It is not a
  data contract; it lives only between a failed filing and its successful rerun.

## 5. Test seams

- **Split first.** `tests/test_auto_file.py` is 463 lines against the 500-line limit (map "Test seams"). Before new
  tests are added, its fakes and helpers (`Asked`, `Filed`, `_sessions`, `_register`, `_before`, the `data` fixture,
  `_run`; lines 37-118) move to `tests/auto_file_support.py`, like `tests/two_park_support.py`; the new tests go to
  `tests/test_auto_file_several_parks.py`. Gain: neither file passes 500 lines and no helper is duplicated. Cost: one
  move-only commit to review.
- **Injecting a failure between two registrations.** The new `register_with` seam (default `register_parks.register`).
  The fakes wrap the real function, so every row written is a real delivery:
  - a wrapper that calls the real `register` for park 1 and raises `register_parks.Refused` for park 2;
  - a wrapper that creates the landing lock file before park 2's call, so the real `register` raises `LockTaken`
    (the pattern of `tests/test_auto_file.py:418-432` and `tests/test_register_parks_start_year_lock.py`);
  - for the under-lock re-check (R5), not a wrapper but a patch of `lock.hold_lock` that lands a row raising the
    floor once the lock is held, as `tests/test_register_parks_start_year_lock.py:43` does; a row landed before the
    call is refused by the pre-lock year check and proves nothing;
  - a wrapper that raises `OSError`, `csv.Error`, `register_parks.CheckFailed` or `KeyboardInterrupt` for park 2;
  - for today's path (R7, R10), a `file_with` fake that really registers the chosen parks through
    `register_parks.register` and then returns 1 or 2, because the plain `Filed` fake writes no registry row, so
    nothing would be seen to land.
- **Planted data.** `plant` and `park_one` from `tests/test_register_parks_start_year.py:41-131` plant the seq audit,
  `session_start`, `park_snapshot`, saves and registry; new parks for R1 to R10 are planted the same way, with distinct
  `emitted_at` values to fix the first-session order and with `park_snapshot` rows (the existing auto-file fixtures
  plant only `session_start`, `tests/test_auto_file.py:68-75`, and R2 needs snapshots or a missing-file case).
- **after-play.** `file_with` stays a recording fake in the several-park tests (no `make` runs); one test per path also
  runs with the real `after_play.main` only where today's tests already do.
- **Pure plan.** `tests/test_start_year_plan.py` feeds `plan_years` lists of `SnapshotDay` and `Registration` values,
  with no files.

## 6. Out of scope

- Changing `make register-parks` or `make after-play` to accept several company parks (ruling: after-play keeps its
  refusal).
- The "Say the park and its company year" item (roadmap line 176), which follows this one in Lane A.
- Any change to the launcher, the Makefile, the data contracts, dbt models, the plugin, stored values or the registry
  note.
- A way to undo a registration; a wrong row is still removed with `make delete-company-data` before go-live (ADR 0050
  decision 8).

## 7. Constraints

Repo invariants (`AGENTS.md`, "Never break"), verbatim:
- Every event carries `park_id`, `session_id`, `seq`, `event_id`, game date, and `emitted_at`; `seq` has no gaps or duplicates within a session. (From contract v1; the 2026-09-27 capture is schema 0.)
- Raw captures are append-only; every fix happens downstream in dbt. The one exception: before go-live, `make delete-company-data` archives and then rewrites or removes company raw captures and registry deliveries (ADR 0033).
- Money stays in the game's tenths of a dollar until one staging conversion; every metric names its unit and its clock (game day, company date, or wall-clock hour).
- Build previews and client-side predictions never count as player actions.
- Never commit RollerCoaster Tycoon files, game screenshots or video frames, the GPL type definitions, or private machine paths. Game footage lives on a video hosting site and the site links to it (ADR 0047).
- The contract is versioned: adding fields is a minor bump; a breaking change is a major bump and a new landing path.
- Analyses state their sample (parks, players) and say "observational" unless an experiment design backs a causal claim.
- The plugin compiles to ES5 and stays within its measured per-tick cost budget.

How they bind here: registry deliveries stay append-only (one new file per registration, never a rewrite); played game
days name their clock (game days); no plugin change. `DATA_SET` and `COUNT_AS` come only from the command line.
Engineering standards (`~/.claude/rules/engineering-standards.md`): one home per rule, no catch-and-continue (each
caught error in the sequential loop is reported and ends the run), files at or under 500 lines, every new test seen to
fail first, no new dependency.

## 8. Golden paths

- Pure logic: `src/openrct2_analytics/domain/company_years.py` (golden example, `docs/CONVENTIONS.md` section 5) for
  `start_year_plan.py`.
- An ingest module with refusals and exit codes: `src/openrct2_analytics/ingest/auto_file.py` and `after_play.py` for
  `several_parks.py` and `start_year.py`.
- Tests: `tests/test_listener.py` (golden example); for this change, `tests/test_auto_file.py` fixtures and
  `tests/test_register_parks_start_year_lock.py` for lock timing; `tests/test_dbt_two_parks.py` and
  `tests/two_park_support.py` for the dbt case;
  `tests/two_park_support.py` as the model for `tests/auto_file_support.py`.

## 9. Outcome measure

From the roadmap item: plays refused for several company parks, 1 seen on 2026-11-15, target 0; read from
`make auto-file` exits.

## 10. Verify by

Run in the ticket worktree:
1. `.venv/bin/python -m pytest tests/test_dbt_two_parks_company.py -k registered_as_company` first and alone (R14).
2. `.venv/bin/python -m pytest tests/test_start_year_plan.py tests/test_auto_file.py tests/test_auto_file_several_parks.py tests/test_register_parks.py tests/test_register_parks_start_year.py tests/test_register_parks_start_year_order.py tests/test_register_parks_start_year_lock.py tests/test_after_play.py`.
3. The new tests against the `ed85773` source, each seen to fail (R15); the failures are listed in the ticket report.
4. `git diff --exit-code develop -- Makefile tests/test_makefile_guards.py launcher/` prints nothing (R13).
5. `wc -l src/openrct2_analytics/ingest/*.py tests/test_auto_file*.py tests/test_dbt_two_parks*.py` shows no file above
   500 lines (the gate checks this too).
6. `env -u VIRTUAL_ENV make check` exits 0 (R17).
7. One real filing of a play that opened two new parks needs the project owner's Mac (macOS, OpenRCT2 0.5.6, the
   company data set). It is recorded as an `open: awaiting project owner` row in the review ledger, not claimed as
   passed.

## 11. Definition of done

Done means all of these hold: every criterion of R1 to R17 passes; `env -u VIRTUAL_ENV make check` exits clean;
nothing outside section 3 changed; ADR 0055 and the doc lines of section 3 describe the new behaviour in the same
change; and the real-play check of section 10 step 7 is named as an owner check with its conditions.

## 12. Decisions taken

Each point is decided; the choice taken is in brackets and the other readings are kept to show what was given up.
1. **What "opened second" counts when a Sandbox park is among the new parks.** [Ranks count every asked park, Sandbox
   included: the order the parks were opened in.] Gain: matches the words "opened first". Cost: with a Sandbox park
   opened first, the only company park must be answered "opened second". The other reading (ranks among company parks
   only) costs a player who thinks in opening order a refusal.
2. **Ask per park even when `COUNT_AS=practice`.** [Yes, as the ruling is worded.] Gain: one rule. Cost: a Sandbox play
   that opened two parks asks two questions whose answer is already known. The alternative files them all as Sandbox
   unasked.
3. **Exit code after a failure that follows a registration.** [1, or 130 for an interrupt; after-play's exit 2 is
   mapped to 1.] Gain: exit 2 keeps meaning "nothing changed". Cost: after-play's exit code is not passed on after a
   landed registration; the launcher reads only zero or non-zero.
4. **Remembering answers for a rerun in `local/auto-file/answers.json`.** [Yes.] Gain: a rerun cannot file a park
   answered Sandbox as company because only one new park is left. Cost: one more local file to keep in step, and a
   failed filing followed by a new launch loses the answers (the parks are then asked as an earlier play's).
5. **An earlier-play park answered Company plus a new company park.** [Filed by the same chain, in first-session order,
   with no order question for the earlier park.] Gain: the outcome measure counts this as a refused play today. Cost:
   it reaches a little past "new parks in one play".
6. **Played game days over all of a park's converted sessions.** [All sessions.] Gain: the simplest reading of the
   ruling. Cost: a new park with an earlier unregistered session shows days from both.

## 13. Open risks

- R14 tests whether the build and the year close accept two company registry rows, the second with a later start year
  while the first park has an unfinished year. No dbt model filters by data set (`int_park_registry__current.sql` has no
  such filter; the data-set singular test checks only the `rehearsal` and `company` targets), so a failure there would
  be a year-close or helper problem, and it stops the slice as planned. The probe may pass before the change (R15).
- Moving the start-year functions to `start_year.py` must not create an import cycle; `start_year.py` imports no
  `register_parks` name. `Refused` lives in `start_year.py` and is reached as `register_parks.Refused` by
  `play_status`, `after_play` and `auto_file`; a small `refusal.py` would be the cleaner home, and is not done here to
  keep the move small.
