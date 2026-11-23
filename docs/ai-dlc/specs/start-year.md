# Spec: a start-year option for `make register-parks`

**Bottom line.** `make register-parks` and `make after-play` gain one option, `START_YEAR=<year>`, so Park 2 can be
registered with its real company start year instead of the hard-coded 2000 (`register_parks.py:172`). The option is
required when a non-practice company park is already registered and a non-practice park is being registered; the first
company park keeps 2000, and practice parks never take one. The command refuses a year that overlaps another company
park's years, reading those years with the shared managed-year logic the autopilot item builds, not a copy of it. A
run registers at most one non-practice park. No data contract, dbt model, plugin file or event contract changes.

- **Gain:** Park 2's registry row carries the year the project owner typed, so its months land on the right company
  calendar and the site can show two parks in one month.
- **Cost:** about half a day of agent build and review when the autopilot item's shared modules exist (decision 7 gives the cost when
  they do not): one new refusal family in `register_parks.py`, a pass-through in
  `after_play.py`, one Makefile guard, a new test file, ADR 0050 (reserved; it amends ADR 0038) and two doc entries.
- **Open risk:** none blocks the build, and no owner decision remains. Two refusals go beyond the ruling's wording (a
  year after the expected one, and several non-practice parks in one run); both are director rulings, recorded in
  decision 3 and refusal 5. Play abandoned after a park's closing 1 March can raise the floor (decision 9).

Status: draft, revised after review, 2026-11-13. Roadmap item: `docs/ai-dlc/roadmap/park-company.md`, section "Second-park readiness", the
start-year item (lines 120-124). Contract map: `docs/ai-dlc/contracts/start-year.md`. Builds after the autopilot item
(`docs/ai-dlc/specs/autopilot-year.md`, review record `docs/ai-dlc/ledger/autopilot-year.md`). "The start-year ruling"
below is the run's accepted-defaults ruling "Start-year design" in the git-ignored `docs/ai-dlc/local/authorizations.md`.

## 1. Goal and requirements

The goal is a company whose second and later parks are dated from the right company year, so the portfolio view and
the v1 site can show two parks in one month (roadmap :120 outcome-link; :116).

| # | Requirement | Source |
|---|---|---|
| R1 | `make register-parks DATA_SET=company PARKS="<id>:company" START_YEAR=<year>` writes a registry row with that company start year. | roadmap :121 |
| R2 | The command refuses a start year at or before the latest company year in which another registered company park has a managed day: when Park 1's last managed year is Y, Y is refused and Y + 1 accepted. | roadmap :121; start-year ruling |
| R3 | `START_YEAR` is required when at least one non-practice company park is registered and a non-practice park is being registered. | roadmap :121 ("Answer in spec"); start-year ruling |
| R4 | The first company park keeps start year 2000. | start-year ruling; roadmap :92 |
| R5 | Practice parks do not count as registered company parks, and take no `START_YEAR`. | start-year ruling |
| R6 | Park 1's last managed year comes from its `park_snapshot` game dates in converted Parquet, through the shared logic of the autopilot spec (sections 3 and 5) and its review Ruling 1; this item never redefines it. | start-year ruling; autopilot spec §3, §5; ledger Ruling 1 |
| R7 | `START_YEAR` applies to exactly one park, and a run registers at most one non-practice park, so two company parks never share a year. | start-year ruling ("several refused"); roadmap :92 |
| R8 | A mistyped year is fixed only by hand: `make delete-company-data` before go-live. No correction command is built. | start-year ruling; ADR 0033 |
| R9 | Exit codes stay 0 written or nothing to do, 1 failed, 2 refused, 130 interrupted; every refusal leaves the folder tree unchanged. | start-year ruling; `register_parks.py:1-7` |
| R10 | The year check runs again under the landing lock. | start-year ruling; contract map §3 |
| R11 | `make after-play` passes `START_YEAR` through to the register step and repeats it in its rerun line. | roadmap :121; start-year ruling |
| R12 | A test shows each refusal and the accepted year; `make check` passes. | roadmap :121 |
| R13 | Park 2's start year follows the business rules with no exception: it is the company year after Park 1's last managed year, typed by the project owner, for a park whose game-year origin is 1 (refusal 11 checks the origin). | roadmap :92, :116 |
| R14 | Outcome measure: Park 2's registry row carries the start year the project owner typed, read in `data/company/registry/v1/`. | roadmap :123 |
| R15 | Touches: `register_parks.py`, `after_play.py`, `Makefile`, `AGENTS.md`, tests, a short ADR amending ADR 0038. | roadmap :124 |

**Answer to the roadmap's question** (roadmap :121, "whether `START_YEAR` is required once one company park is
registered"): **yes, with two limits.** It is required when at least one non-practice company park is registered and
the park being registered is not a practice park. A registered practice park does not make it required, and a practice
park being registered never takes it (start-year ruling).

## 2. Decisions

Each decision states its gain and its cost. ADR 0050 records decisions 1 to 6 and 9.

1. **Required rule as ruled** (R3 to R5). "Registered company park" means a park whose latest registry row has
   `data_set` = `company` and a note other than `register_parks.NOTE`, read with the autopilot item's registry reader
   (decision 7). Gain: no silent 2000 for a second park, while the first-park path stays one bare command. Cost: one
   registry read that `registered_parks` already does today.
2. **The floor is the latest company year of the other registered company parks.** For each registered company park,
   its year is the larger of its `company_start_year` and its latest managed company
   year; the floor F is the largest such year across those parks. With managed days, F is Park 1's last managed year Y,
   so R2 holds as written. The start year enters only for a registered park with no managed day yet (no recorded save),
   because a park's first company year is its own by the business rules (roadmap :92). Gain: a second park can never be
   given a year a registered park already holds, even before that park has a recorded save. Cost: one comparison; it
   differs from the plain R2 reading only in that no-save case.
3. **Accept exactly F + 1; refuse a later year too** (R13). The start-year ruling and roadmap :121 state only the
   lower bound; the upper bound comes from roadmap :92 and :116, and the director ruled to keep it. By the business
   rules the next park starts "the following March" after the managed park goes to autopilot (roadmap :92), and a gap
   year has no managed park, so the autopilot park cannot run it (autopilot spec §5 verdict) and its close register
   stays open (contract map §2). Gain: a typo such as 2005 for 2001 is caught before it lands, and such a row could
   otherwise be fixed only by a pre-go-live delete (R8). Cost: the typed year is then a confirmation of a value the
   command knows; a deliberate gap needs a code change.
4. **The first company park accepts only 2000.** `START_YEAR=2000` there is accepted; any other value is refused. Gain:
   a typed 2000 is not punished, and Park 1 cannot be moved off 1 March 2000 (roadmap :92). Cost: one more refusal text.
   A typed `START_YEAR` is checked like any typed year, origin rule included (refusal 11), while the bare command for a
   first company park keeps 2000.
5. **A given `START_YEAR` with nothing to register is not used, not refused.** Both commands print a line saying so and
   exit as today. Gain: the after-play rerun line (R11) still runs after the register step succeeded and a later step
   failed. Cost: a mistyped year on such a rerun goes unnoticed, which is harmless because nothing is written.
6. **after-play checks the year before any step** by calling the same `register_parks.start_years` (section 3) with
   the parks it is about to register. Gain: a bad year is refused with exit 2 and "Nothing was changed." instead of a
   failed register step (exit 1) in the middle of the chain. Cost: the managed-year read runs once more (it runs twice
   inside register already, R10).
7. **Reuse, never redefine, the managed-year logic** (R6). This item calls the autopilot item's modules as their spec
   places them (autopilot spec §3): `domain/company_years.py` owns the company year of a game date, the managed day and
   the 1 March year-end rule; `ingest/managed_years.py` reads converted `park_snapshot`, `save_written` and
   `session_start`, the registry and the label feed before `make transform`; `ingest/registry_feed.py` owns each
   park's latest registry row. So days after a session's last save never count, a 1 March save day counts toward the
   year before, and, once the label feed exists, `autopilot` sessions never count (ledger Ruling 1). The roadmap's
   cross-park question, "the latest company year in which another registered company park has a managed day", is a
   **thin wrapper here** (decision 2): a maximum over the per-park values that `managed_years.latest_managed_year`
   already computes for the autopilot verdict. It is not a change to the autopilot design. The 1 March rule includes
   the fix of the autopilot item's review row S-2 (a 1 March day counts toward the year before when the same session
   has a managed day in it or its `session_start` is dated in it); this item only tests it (section 5).
8. **The stale-Parquet guard is the autopilot item's function.** Before it computes F, the command calls
   `managed_years.unconverted_raw_file(raw_dir, parquet_dir) -> Path | None` and refuses (refusal 7) on a path,
   because a stale Parquet understates Park 1's last managed year. A missing raw folder is clean. Gain: one owner for
   the rule. Cost: one scan of the company raw files, made only on the required path, so the first-park path reads
   nothing new. This item adds no code to `managed_years.py`.
9. **Abandoned play is inherited, not fixed here.** The floor reads converted Parquet, so abandoned managed days of
   another park raise it (autopilot spec decision 8), because autosaves are saves and nothing tells them apart
   (`contracts/save_written.odcs.yaml:18`). The director kept the Parquet read and ruled that there is no override.
   Gain: one rule for both commands. Cost: if Park 1 recorded a save in a try-out branch that reached Y + 1, Park 2
   must start in Y + 2. Refusals 8 to 10 therefore name the park and the year F that set the floor and point to ADR
   0050, which explains the abandoned-play case and the pre-go-live fix by hand. They cannot name the session and game
   date that set F: the fixed reader returns only the year, and reading the dates here would redefine the managed-day
   rule (R6). ADR 0050 must also say how to find which session set F: the `make results` sessions list, or the
   converted `park_snapshot` dates of that park. It also says that a park relabelled from practice to company by a hand-written delivery bypasses
   the check; that is out of scope.

## 3. Placement plan

One owner per rule.

| Rule | Owner (new or changed) | Reuses | Read by | Layer |
|---|---|---|---|---|
| Shape of a typed year: digits only; blank means not given | `register_parks.parse_start_year(text: str \| None) -> int \| None` (new, public) | nothing | `register_parks.main`, `after_play._run` | ingest |
| The year written for each chosen park, and every start-year refusal of section 4 | `register_parks.start_years(chosen: dict[str, bool], start_year: int \| None, *, parquet_dir: Path, raw_dir: Path, feed: Path) -> dict[str, int]` (new, public) | the registry reader (`registry_feed.py`, autopilot §3); `managed_years.latest_managed_year(parquet_dir, registry_dir, park_id) -> int \| None` and `managed_years.unconverted_raw_file(raw_dir, parquet_dir) -> Path \| None` (autopilot §3 and its review row S-1; decision 8) | `register_parks._run` (before and under the lock), `after_play._to_register` | ingest |
| The first company park's year | `register_parks.FIRST_START_YEAR = 2000` (new constant; replaces the literal at line 172) | nothing | `start_years`, `_delivery` | ingest |
| Writing the delivery row | `register_parks._delivery(rows, years, today)` (changed: column 2 from `years`) | `registry_feed.HEADER` | `_run` | ingest |
| Pass-through, rerun line, not-used note | `after_play._run`, `_to_register`, `_steps` (changed) | `register_parks.parse_start_year`, `start_years`, `main` | `make after-play` | ingest |
| Command-line guard | `Makefile` (changed: a `START_YEAR` block beside the `PARKS` block, lines 35-42; both recipes, lines 239-242 and 249-252) | the `PARKS` guard pattern | both targets | build |

- **What is passed.** `_select` returns a list of `(park, origin, time, practice)` tuples; `_run` converts it with
  `{row[0]: row[3] for row in chosen}` to build `chosen` for `start_years`, maps each park to its practice flag.
  `start_years` reads the origins (for refusal 11) itself through `register_parks._source_rows`, with the audit and
  `session_start.parquet` paths derived from `parquet_dir` as `_run` does, because `after_play` holds no origins.
  `start_year` is the parsed value; `parquet_dir` is
  `landing_dirs("company").parquet` and `raw_dir` its raw folder, both resolved against `project_dir` as `_run`
  resolves them (`register_parks.py:183-188`); `feed` is the registry `v1` folder. For each registered company park,
  `start_years` calls `latest_managed_year` (a missing `park_snapshot.parquet` or `save_written.parquet` means no
  managed days, so it returns `None`). `OSError` and `duckdb.Error` from the shared reader stay exit 1 through the
  existing handler (`register_parks.py:268`); this item adds no handler.
- **If the autopilot item is parked before its shared modules exist** (its Verify-by step 0 lets the start-year item
  still build): the first ticket of this item builds `domain/company_years.py`, `managed_years.py` (including the two
  functions above) and the registry reader exactly as autopilot spec §3 and §5 define them, with every session managed
  (no label feed), so the autopilot item later reuses them unchanged. Cost: this item then carries the autopilot
  item's shared modules and their two test files (`tests/test_company_years.py`, `tests/test_managed_years.py`), so
  the half-day figure no longer holds, and the section 5 autopilot-days case is deferred (the PR says so).
- **Hotspots.** `Makefile` only. `contracts/` is not touched: `company_start_year` is a required integer with no bounds
  (`contracts/reference/park_registry.odcs.yaml:34-38`), so any year already passes the contract and the overlap rule
  lives in Python (contract map §1). `models/staging/` is not touched: `stg_park_registry.sql` casts any integer year
  and every later model reads it (contract map §1). The plugin and the 14 event contracts are not touched.
- **File sizes.** `register_parks.py` is 281 lines and stays under 500. `tests/test_register_parks.py` is 398 lines, so
  the new cases go in a new file (section 6).
- **Golden example:** the `--parks` option in the same module and its tests (`register_parks.py:126-163`,
  `tests/test_register_parks.py:324-398`, the refusal table at `:163-191`), the guard at `Makefile:35-42`, and the
  in-process pass-through at `after_play.py:108-123` (contract map §6).

## 4. The command

`make register-parks DATA_SET=company [PRACTICE=yes | PARKS="<id>:company,<id>:practice"] [START_YEAR=<year>]` runs
`python -m openrct2_analytics.ingest.register_parks --data-set company [...] [--start-year=<year>]`.
`make after-play DATA_SET=company [PARKS="..."] [START_YEAR=<year>]` runs `after_play` with `--start-year=<year>`.

- **Makefile.** For both targets: an exported `START_YEAR` is refused ("START_YEAR must be given on the command line
  (make register-parks DATA_SET=company PARKS=\"<id>:company\" START_YEAR=<year>), not read from the environment"), a
  value holding a dollar sign is refused ("START_YEAR must not contain a dollar sign"), and the recipes pass
  `$${START_YEAR+--start-year="$$START_YEAR"}`, as they pass `PARKS`. Python checks the digits (one owner). An empty
  `START_YEAR=` means not given, as an empty `PARKS=` does.
- **Rows written.** The one non-practice park a run registers gets the typed year (`START_YEAR`) when one is given; the first company park gets
  2000; a practice park gets 2000, as today (it has no company calendar role). `game_year_origin` is unchanged: the
  park's first `session_start` game year.
- **Report.** After today's line `Registered <N> park(s) in <name>.`, a run that used `START_YEAR` prints
  `Park <id>: company start year <S> (START_YEAR).` A run with nothing to register and a given `START_YEAR` prints
  `START_YEAR=<S> not used: no park waits to register.` after today's "All captured parks are already registered."

### Refusals, in order (exit 2; each prints `register refused: <reason>: <detail>. Nothing was changed.`)

Refusals 1 and 2 run before any data is read. Refusal 3 is today's set from `_prepare` and `_select`; refusals 3 to 11
run before the lock and again under it (R10). A refusal under the lock is final: the lock does not wait
(`lock.py:80-89`). F is the floor of decision 2; `<ids>` lists park ids.

| # | Reason | When | Detail text |
|---|---|---|---|
| 1 | `start-year` | the value is not ASCII digits only, `[0-9]+` as in `registry_feed.py:43,107` (after trimming spaces), or is longer than 50 digits | `START_YEAR must be a year written in digits, such as 2001; got '<value>'` |
| 2 | `start-year-practice` | `START_YEAR` with `--practice` (register-parks only; after-play has no `--practice`) | `Practice parks take no START_YEAR; give PARKS="<id>:company" START_YEAR=<year> for the company park` |
| 3 | today's refusals | `not-converted`, `leftover`, `mixed-session`, `no-session-start`, `registry-check`, `mismatch`, `no-free-name`, `parks`, `unknown-park` | unchanged |
| 4 | `start-year-practice` | `START_YEAR` given and every chosen park is a practice park | `Practice parks take no START_YEAR, and every park being registered is a practice park (<ids>)` |
| 5 | `several-company-parks` | more than one non-practice park chosen, whether or not a company park is registered or `START_YEAR` is given | `Only one company park can be registered per run, and <n> would be (<ids>); register one at a time with PARKS="<id>:company"` |
| 6 | `start-year-first-park` | no company park is registered, and `START_YEAR` is given and is not 2000 | `Park <id> is the first company park, which starts in company year 2000; drop START_YEAR` |
| 7 | `not-converted` | a company park is registered and one non-practice park is chosen: a company raw file holds a session missing from `session_start.parquet` (decision 8) | `<file> holds a session that was never converted, so the latest managed year is unknown; run make convert DATA_SET=company first` |
| 8 | `start-year-required` | a company park is registered, one non-practice park chosen, no `START_YEAR` | `Park <id> is not the first company park (registered: <ids>), so give its company start year with START_YEAR=<year>; by the business rules it is <F + 1>; if <F> looks too high, see ADR 0050 (play abandoned after the closing 1 March)` |
| 9 | `start-year-overlap` | S ≤ F | `Company year <S> overlaps park <id>, whose latest company year is <F>; park <new id> starts in <F + 1>; if <F> looks too high, see ADR 0050 (play abandoned after the closing 1 March)` |
| 10 | `start-year-gap` | S > F + 1 | `Company year <S> would leave company year <F + 1> with no managed park; the next park starts the March after <F>, which park <id> sets, so START_YEAR must be <F + 1>; if <F> looks too high, see ADR 0050 (play abandoned after the closing 1 March)` |
| 11 | `start-year-origin` | `START_YEAR` is given and passed refusals 6, 9 and 10, and the park it applies to has a `game_year_origin` other than 1 (roadmap :116) | `Park <id> has game-year origin <o>; a company start year needs a park that began in game year 1, so capture the park from a new game before registering it` |

In refusals 9 and 10, `<id>` is the park that sets F; when two parks share F, the lowest id is named. Refusal 5 also catches
several first parks with no company park registered (they would both get 2000).

### `make after-play`

- `after_play._run` parses the value with `parse_start_year` (refusal 1 prints with the `after-play refused:` prefix,
  as `after_play.py:176-178` does for register refusals). When parks are to be registered, `_to_register` calls
  `start_years` before any step (decision 6), after `_check_registered`, so the existing order (lock-taken,
  warehouse-busy, parks-missing, choice-conflict, as `tests/test_after_play.py:149-166` shows) stays first and refusals
  4 to 11 then exit 2 before any step. Refusal 2 cannot occur here as the `--practice` flag, but its practice-only form can: a `START_YEAR` with every park to register chosen practice exits 2 with `start-year-practice` before any step.
- The register step's argument list gains `--start-year=<S>`; its printed command (`after_play.py:118`) gains
  ` START_YEAR=<S>`; the rerun line (`after_play.py:143-145`) gains ` START_YEAR=<S>` whenever it was given.
- When no listed park needs registering (a rerun after a later step failed), it prints
  `after-play: register: no waiting park needs registering; START_YEAR=<S> not used` and runs the other steps. The
  suffix prints only when `START_YEAR` was given and no listed park waits to register; when a park is being
  registered, the register step's own report line is used.
- Exit codes are unchanged: 0, 1, 2, 130.

## 5. Year cases

Fixture: Park 1 registered with start year 2000 and origin 1; Y is Park 1's latest managed company year from the
shared logic. "Day (g, date, seq s)" is a `park_snapshot`, "save s" a `save_written` at `seq` s.

| Case | Inputs | Expected | Source |
|---|---|---|---|
| Accepted year | Park 1 days through 1 March of game year 2, save there (Y = 2000); Park 2 pending, `START_YEAR=2001` | exit 0; Park 2's row has `company_start_year` 2001 and origin 1 | roadmap :121, :116 |
| Y refused | as above, `START_YEAR=2000` | refusal 9 | roadmap :121 |
| Before Park 1 | as above, `START_YEAR=1999` | refusal 9 | contract map §2 |
| Gap refused | as above, `START_YEAR=2002` | refusal 10 | decision 3 |
| Days after the last save do not count | Park 1 also has day (2, 2 March, seq after the save) | 2001 still accepted | ledger Ruling 1 |
| A later managed year raises Y | Park 1 has a second session, saved on 20 March of game year 2 (Y = 2001) | 2001 refused (9); 2002 accepted | ledger Ruling 1 |
| No managed day yet | Park 1 has days but no `save_written` | F = 2000: 2000 refused, 2001 accepted | decision 2 |
| Third park | Park 2 registered 2001 with managed days in 2001 | Park 3: 2001 refused, 2002 accepted | roadmap :92 |
| Origin not 1 | Park 2's first `session_start` has game year 5; `START_YEAR=2001` | refusal 11 | roadmap :116 |
| Load near the year end | Park 1's session loads a 31 October save of game year 1 (its `session_start` is dated in game year 1), has no `park_snapshot` in game year 1 and plays to 1 March of game year 2 with a save there; `START_YEAR=2000` and 2001 | Y = 2000: 2000 refused (9), 2001 accepted; the rule is the autopilot item's row S-2 and is only tested here | autopilot row S-2 |
| Autopilot days do not count | the third-park case plus a Park 1 session in 2001 listed `autopilot` in the label feed (once the feed exists) | 2002 still accepted; applies when the label feed exists, deferred under the section 3 fallback | ledger Ruling 1 |

## 6. Tests and seams

Seams stay as today: `register_parks.main(argv, *, project_dir, today)` and `after_play.main(argv, *, project_dir)`,
with `OPENRCT2_DATA_DIR` pointing at `tmp_path`; Parquet is planted with DuckDB `COPY ... TO PARQUET` and registry rows
with the `_delivery` helper pattern (contract map §4). No test reads `data/company/`. Every refusal test asserts exit
2, its reason and an unchanged tree (`_tree`). Every new test is first run against a deliberately broken version and
seen to fail (`engineering-standards.md`, Tests).

- **`tests/test_register_parks_start_year.py` (new):** each case of section 5; refusals 1, 2 and 4 to 11 each from
  its own planted state, including refusal 5 with no `START_YEAR` and no registered company park (two non-practice
  parks), and the refusal 9 tie-breaker (two registered parks share F; the lowest id is named); a registered
  practice park alone does not make `START_YEAR` required (the new park gets 2000); with `PARKS="<practice>:practice,
  <company>:company"` beside a registered company park, the company park gets S and the practice park 2000, and only
  with the practice park marked `:practice` does the practice park need no `START_YEAR`; `START_YEAR=2000` accepted
  for the first park; blank `START_YEAR` treated as not given; `START_YEAR` with nothing pending exits 0, prints the
  not-used line and changes nothing. Two under-the-lock tests, in the pattern of
  `test_delivery_landing_during_lock_wait_is_not_duplicated` (`tests/test_register_parks.py:284`, hooking
  `lock.hold_lock`): a registry delivery that lands during the lock wait and registers a company park turns a
  first-park run into refusal 8 under the lock; a convert that lands during the lock wait and raises Park 1's
  managed year (new `park_snapshot` and `save_written` rows) turns an accepted year into refusal 9 under the lock.
- **`tests/test_register_parks.py` (changed).** Since refusal 5 now refuses two non-practice parks in one run and
  refusal 8 refuses a non-practice park beside a registered company park, these tests change their setup, never an
  assertion that checks behavior:
  - `test_registered_park_skipped_and_nothing_to_do` (:97): `_delivery` gains a `note` parameter and the planted
    park-a is registered as practice, so park-b is the first company park; its assertions are unchanged.
  - `test_next_free_name` (:113), `test_rejected_and_unaccepted_name_do_not_register` (:195),
    `test_bad_year_fails_check_and_removes_stage` (:206), `test_sigterm_at_check_removes_stage` (:218),
    `test_misnamed_delivery_is_warned_and_park_registers_again` (:252),
    `test_delivery_landing_during_lock_wait_is_not_duplicated` (:284) and
    `test_failed_check_leaves_no_registry_folder` (:309): the call gains `--practice` (two parks, both practice); every
    assertion is unchanged, because none reads the practice note.
  - `test_refusals_leave_folder_tree_unchanged` (:163): only its `lock` case gains `--practice`, so refusal 5 does not
    fire before the lock refusal; reasons and the unchanged-tree check are unchanged.
  - `test_empty_park_list_is_no_list` (:387): the first call becomes `--practice --parks ""` (an empty list is still
    no list, because `--practice` with a real list is refused), so the expected notes become `register_parks.NOTE`;
    the second call and its assertions are unchanged.
  - Unchanged: `test_two_parks_in_clock_order_and_practice_note` (uses `--practice`), the park-list tests at
    :324-384 (one non-practice park at most) and `test_registers_the_committed_sample_layout` (one park).
- **`tests/test_after_play.py`:** no existing test changes (each registers one company park and one practice park, and
  the choice-conflict case is refused before `start_years`). New: `START_YEAR` reaches the register step (Park 2's row
  holds S; the fixture gives Park 2 game year 1); refusal 8 exits 2 before any step runs; two company parks in
  `PARKS` exit 2 before any step; `START_YEAR=abc` exits 2 with nothing waiting; the printed register command and the
  rerun line hold `START_YEAR=<S>`; a rerun with the park already registered prints the not-used line and runs the
  later steps, and no not-used line prints when a park is registered.
- **`tests/test_makefile.py` (changed):** `test_register_parks_runs_its_module_through_run` (:221) and
  `test_play_status_and_after_play_run_their_modules_through_run` (:230) assert the exact recipe text; the expected
  `register-parks` and `after-play` recipes gain ` $${START_YEAR+--start-year="$$START_YEAR"}` after the `PARKS`
  part; the `play-status` assertion is unchanged.
- **`tests/test_makefile_guards.py`:** for both targets, an exported `START_YEAR` is refused; a dollar sign is refused;
  the recipe text holds `${START_YEAR+--start-year="$START_YEAR"}`; an empty `START_YEAR=` is accepted; an exported
  `START_YEAR` does not stop other targets.
- **Shared logic:** this item adds no test of the managed-day rule itself; `tests/test_company_years.py` and
  `tests/test_managed_years.py` (autopilot spec §8) own it. If the fallback of section 3 applies, those two files are
  built here as the autopilot spec lists them.

## 7. Files

- **New:** `tests/test_register_parks_start_year.py`, `tests/test_register_parks_start_year_lock.py`, `tests/test_register_parks_start_year_order.py`; `docs/adr/0050-company-start-year-from-the-register-command.md`.
- **Changed:** `src/openrct2_analytics/ingest/register_parks.py`, `src/openrct2_analytics/ingest/after_play.py`,
  `Makefile`, `tests/test_register_parks.py`, `tests/test_after_play.py`, `tests/test_makefile.py`,
  `tests/test_makefile_guards.py`. `managed_years.py` is the autopilot item's file and is not changed here.
- **Docs, in the same change:** ADR 0050 (decisions 1 to 6 and 9; the fix-by-hand rule of R8; the abandoned-play case and how to find which session set F (the `make results` sessions list, or the converted `park_snapshot` dates of that park); hand-written deliveries are out of scope); ADR 0038 gains one status
  line pointing to ADR 0050 and no other edit; `AGENTS.md` command entries for `make register-parks` and
  `make after-play` (both say "company start year 2000" and list options and refusals); `ARCHITECTURE.md`, "Registry
  feed landing" (line 486) and the after-play paragraph (near line 583).

## 8. Out of scope

- A command to correct a landed start year; the pre-go-live delete stays the only fix (R8, ADR 0033).
- A per-park year in `PARKS` (such as `<id>:company:<year>`); one park per run instead (R7).
- Any change to the registry contract, `stg_park_registry` or later models, or a dbt test of one managed park per
  company year.
- Changing the managed-day, 1 March or abandoned-play rules (owned by the autopilot item).
- Showing a start year in `make play-status`.
- Guarding against a hand-written registry delivery that relabels a park from practice to company.

## 9. Constraints

Every repo invariant (`AGENTS.md`, "Never break") binds this item. How it meets the ones it touches:

- Raw captures are append-only: the command reads raw files (decision 8) and never writes one; registry deliveries are
  still only added, and the pre-go-live delete keeps its ADR 0033 exception.
- Versioned contracts: no contract changes, so no version bump.
- Every metric names its clock: the start year is a company calendar year, as the contract describes it.
- No private machine paths or game files in git; tests use `tmp_path`.
- One owner per hotspot per ticket: `Makefile` only; `contracts/` and `models/staging/` untouched (section 3).
- Exit codes and the unchanged-tree refusal rule are kept (R9).

## 10. Verify by

Run from the worktree, with `UV_CACHE_DIR` set to a folder under `$TMPDIR`.

1. While building: `.venv/bin/python -m pytest tests/test_register_parks.py tests/test_register_parks_start_year.py
   tests/test_after_play.py tests/test_makefile.py tests/test_makefile_guards.py -ra`
2. The gate: `make check` (about 20 minutes).
3. The project owner, when Park 2 is registered (not a build step): `make after-play DATA_SET=company
   PARKS="<park 2 id>:company" START_YEAR=<Y + 1>`, then read Park 2's row in `data/company/registry/v1/` (R14).

## 11. Definition of done

- `check:` `make check` passes on the branch.
- `check:` each case of section 5 has a passing test in `tests/test_register_parks_start_year.py`; the autopilot-days case
  applies when the label feed exists and is deferred under the section 3 fallback, which the PR says.
- `check:` each refusal of section 4 (1, 2, 4 to 11) has a test that shows its reason, exit 2 and an unchanged tree,
  and refusals 8 and 9 each have an under-the-lock test.
- `check:` every existing test that section 6 lists as changed passes with its assertions unchanged, except the
  expected notes in `test_empty_park_list_is_no_list`.
- `check:` `tests/test_after_play.py` shows the pass-through, an exit-2 refusal before any step, `START_YEAR=<S>` in the
  printed command and the rerun line, and the not-used line on a rerun.
- `check:` `tests/test_makefile_guards.py` shows the environment and dollar-sign refusals for both targets.
- `check:` `grep -n "park_snapshot\|save_written" src/openrct2_analytics/ingest/register_parks.py` prints nothing (the
  managed-day rule is not redefined here).
- `check:` `grep -n "2000" src/openrct2_analytics/ingest/register_parks.py` prints only the `FIRST_START_YEAR` line.
- `check:` `git diff --stat <base>...HEAD`, where `<base>` is the autopilot build's tip this item stacks on, shows no
  change under `contracts/`, `models/`, `plugin/src/`, and none to `pyproject.toml` or `package.json`.
- `judgment:` a reviewer reads every refusal text as plain and actionable, each naming what to type next.
- `judgment:` a reviewer confirms ADR 0050, the ADR 0038 status line, the two `AGENTS.md` entries and `ARCHITECTURE.md`
  describe the option as built, including the abandoned-play effect of decision 9.
