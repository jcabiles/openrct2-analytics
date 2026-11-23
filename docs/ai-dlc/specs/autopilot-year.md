# Spec: run a finished park headless for one game year, and label every session

**Bottom line.** One new command, `make autopilot-year DATA_SET=company PARK=<id>`, takes a finished company park's
last recorded save from the never-overwritten backup archive, plays it in the game with no window (headless) with the
analytics plugin, and stops on 1 March of the next game year, right after the plugin sends October's statement. It
records into its own work folder, checks the capture there, and only then appends it to the company data, labels the
new session `autopilot`, and copies the end-of-year save to the archive and to the game's save folder. Every row of
`staging.stg_session_start` gains a `play_mode` column, `managed` or `autopilot`; sessions not listed by the command
stay `managed`. The plugin and the 14 event contracts do not change. Building it needs no game: every test uses a
stand-in game process, except one end-to-end test on a copy of the benchmark park that is run by hand.

- **Gain:** Park 1 keeps producing company months while Park 2 is played by hand, so the company can show two parks
  in one month, as the v1 site promises.
- **Cost:** about two days of agent build and review across eight new modules, one new delivery feed with its own
  reference contract, and one new ADR (0049, reserved). One run of the real game, by hand, checks the year-end stop on
  OpenRCT2 0.5.6.
- **Open risk, now mostly closed:** the real-game probe of the year-end stop ran on 2026-11-13. It failed once (the
  game played four days of the next year after its save), was fixed by the helper pausing the game right after its
  save, and passed a re-probe of two chained sessions. The game binary reports v0.5.7, not 0.5.6. The full end-to-end
  run on a finished company park stays a hand check (section 12, step 3).

Status: revised after blind review, 2026-11-13. Roadmap item: `docs/ai-dlc/roadmap/park-company.md`, section
"Second-park readiness", the autopilot item (line 125; pass/fail line 127) and the label item (line 136; pass/fail
line 137). Contract maps: `docs/ai-dlc/contracts/autopilot-year.md` and `docs/ai-dlc/contracts/session-label.md`.
Review record: `docs/ai-dlc/ledger/autopilot-year.md`. Two kinds of ruling are cited: "run ruling N" is the run's
numbered rulings file (1 source save, 2 stage and check, 3 the missing backup, 4 tests out of `make check`, 5 the label
source, 6 the load limit, 7 the ready mark, 8 the shared managed-year logic); "review ruling N" is a director ruling of
the ledger.

## 1. Goal and requirements

The goal is a theme park company whose finished parks keep running on the company calendar while the next park is
built by hand (repo `AGENTS.md`: "A portfolio analytics stack for a theme park run as a business"; roadmap :92).

| # | Requirement | Source |
|---|---|---|
| R1 | One command takes a company park's last recorded save and runs it headless with the plugin from its current game date to the end of that game year. | roadmap :127 |
| R2 | The run stops on 1 March of the next game year, right after the plugin emits October's statement, before any day of the next year is played, and saves there. | roadmap :127; `plugin/src/finance.ts:43-57` |
| R3 | It lands the raw capture, the save-file records and the end-of-year save the way `make play` lands them. | roadmap :127 |
| R4 | It copies the end-of-year save to the never-overwritten archive and to the game's save folder under a dated name, and never overwrites a file in the game's save folder. | roadmap :127; ADR 0048 |
| R5 | It refuses: a running game; a park that is not a registered company park; a practice park; a park's first autopilot run without the ready mark; a year the rules forbid. | roadmap :127 |
| R6 | The ready mark is a typed confirmation that the park is profitable and its scenario challenge is complete, recorded with the run. | roadmap :127; run ruling 7 |
| R7 | Year rule: an autopilot park runs only a company year the managed park runs, and never past that year's end. Four cases, each with a test (section 5). | roadmap :92, :127 |
| R8 | The source save is the park's last recorded save, taken from the archive (`OPENRCT2_BACKUP_DIR/<park_id>/`); no archive copy is a refusal with a clear message; no `--source` option. | run ruling 1 |
| R9 | The run records into its own work folder; the capture is checked there (`seq` audit, contracts, registry) and only then appended under the landing lock with names that cannot clash. A label or record file may land without its session; a raw session never lands in part or without its label. | run ruling 2; review ruling 5 |
| R10 | Every row of `staging.stg_session_start` carries `play_mode`, `managed` or `autopilot`, with dbt `not_null` and `accepted_values` tests; sessions captured before this change are `managed`; a session started by the command is `autopilot`. | roadmap :137 |
| R11 | The label comes from a delivery file beside the park registry, keyed by `session_id`, written by the command after capture; a session missing from it is `managed`; no plugin or event-contract change; the command fails loudly if the label write fails. | run ruling 5 |
| R12 | The "latest managed company year of a park" logic is built here, works before `make transform` (converted Parquet plus the registry), counts only managed sessions once the label exists, and never counts practice parks. | run ruling 8 |
| R13 | `make check` never starts the game; a stand-in game process covers the command; one end-to-end test on a copy of the benchmark fixture is skipped by `make check` and run by hand. | run ruling 4 |
| R14 | The 3.0 load limit, the live-autosave check, the port checks and the process check are reused unchanged. | run ruling 6 |
| R15 | Agent test: a run on a copy of the benchmark fixture stops on 1 March of the next game year with October's statement captured and no next-year day played, its `seq` audit is clean, `make contracts` passes, and the kept timeline continues the source save with the same park ID. | roadmap :127 |
| R16 | Owner test: after the real run and `make after-play`, `marts.fct_park_month` holds Park 1's months 0 to 7 of that year and the year's close status is complete. | roadmap :127 |
| R17 | Outcome measures: company months with two or more parks holding a kept statement (0 today, `marts.fct_park_month`); share of sessions with a play-mode label (0% today, 100% after, `staging.stg_session_start`). | roadmap :130, :139 |
| R18 | Investigate why the 2026-11-12 company run wrote no dated backup; fix a visible code defect, or say none is visible. | run ruling 3 |

## 2. Decisions

Each decision states what it gains and what it costs. ADR 0049 (reserved; the build writes it) records decisions 1
to 8 and 11.

1. **Source save: the newest archive copy, proven to be the last recorded save** (run ruling 1; review ruling 7).
   - *Which copy.* The command lists `<archive dir>/<park_id>/` and takes the `.park` file with the latest time parsed
     from the end of its name (`-YYYY-MM-DD-HHMMSS.park`, `save_backup.py:283`), not the full-name sort of
     `_archive_files` (`save_backup.py:95-103`), because the name starts with the park's name, which the player can
     change (`save_backup.py:274`).
   - *The proof.* Across all company runs, the park's latest `save_written` event (by `emitted_at`) must be paired with
     exactly one save-file record, using the per-run pairing loop of `judge_saves` (`save_pairing.py:216-221`),
     extracted into one public function that both use. The chosen copy's size must equal that record's `size_bytes`,
     and its modified time must be at or after the record's `modified_at`: the copy is written after the save and
     `copy_checked` does not keep the source's time (`save_backup.py:199-200`). The time in the name is never compared
     with `emitted_at`: it is local time with no zone (`capture_session.py:383`).
   - *The source's game date and `seq`* are read from `save_written.parquet` by the paired event's `event_id`;
     `read_save_written` and `SaveWrittenRow` carry neither (`save_files.py:167-193`, `save_pairing.py:48-60`).
   - Gain: an archive copy is never modified (ADR 0048), and the proof stops a stale copy from silently cutting off the
     managed play recorded after it (ADR 0024 decision 3a). Cost: size and time are a cheap match, not a byte proof; a
     run whose backup was skipped blocks autopilot until one healthy `make play` run makes a new backup.
2. **Stage, check, then append** (run ruling 2). The game runs with `--user-data-path` inside a new work folder, as the
   rehearsal chain does (`bench_play.py:158-188`). Only a capture that passes every check in section 6 is appended to
   `data/company/`. Gain: a failed run never reaches company raw data, which is append-only (invariant 2). Cost: a new
   landing function, because `rehearsal_land.land` refuses a non-empty data set (`rehearsal_land.py:393-400`).
3. **Label source: a delivery file in the registry folder** (run ruling 5). Files
   `data/<set>/registry/v1/session_play_mode_<YYYY-MM-DD>_<NN>.csv` sit beside `park_registry_*.csv`, so dbt reads
   them through the existing `registry_root` variable and the publish and delete paths already visit that folder.
   Gain: no plugin change, no 14-contract version bump and no `make bench` (`session-label.md` section 3). Cost: a new
   reference contract, checker, staging model and wiring; and an autopilot session whose label row is lost would count
   as `managed`, the direction that pollutes lever analysis, so the label lands first (decision 6).
4. **The ready mark lives in the same delivery row as the label** (run ruling 7). A park's first autopilot run writes
   the typed phrase into `ready_confirmation`. "First run" means the park has no `autopilot` label row whose session is
   in the converted `session_start.parquet`, so an orphan label row (decision 6) never makes the next run look like a
   later one. On a later run, a given `READY` is ignored whatever it holds, and the report says so. Gain: one feed and
   one contract instead of two, and the mark is "recorded with the run" by construction. Cost: the mark exists only
   once a run lands; a first run that fails must be confirmed again.
5. **One session per label row, no restating deliveries.** The checker refuses a `session_id` that appears twice across
   all deliveries. Gain: staging needs no repeat-delivery filter (and so no new cleaning-rule count row). Cost: a wrong
   label is fixed only by the pre-go-live rewrite of `make delete-company-data` (ADR 0033).
6. **Landing order: label, then save-file records, then one raw file** (review ruling 5). The work folder's raw files
   are joined in order into one raw file per session, so the raw step is a single link and a raw session never lands in
   part. Gain: a crash part-way leaves at most a label row, or a label row and record files, that name no landed
   session; it never leaves an unlabeled or partial autopilot session. Cost: an orphan label row stays in the feed
   until `make delete-company-data SESSION=<id>` removes it (section 7).
7. **The stop year is rendered into the helper text** (review ruling 4). `rehearsal_helper(filename, target_year=None)`
   takes the save-file stem without `.park` (as `rehearsal_chain.py:173` passes it; the stand-in adds the suffix,
   `tests/bench_standin_game.py:228`). With a target year, the helper arms on the day callback of 1 March of that year
   and saves 200 ticks later (`SAVE_DELAY_TICKS`, `rehearsal_helper.py:21`); the command passes g + 1, where g is the
   source save's game year. Without one, today's rule stays (ignore the first day callback, arm on a later 1 March), so
   the rehearsal chain and `tests/test_rehearsal_helper.py:73` are unchanged. In every mode, with or without a target
   year, the helper pauses the game right after its save (`pausetoggle`, commit `73099c1`), so no later day is played.
   Gain: a source saved on 31 October stops
   after one night instead of a whole extra year (`autopilot-year.md` section 4, "A subtle trap"); nothing reads the
   year at run time, so no tick-versus-day-callback race (`rehearsal_helper.py:31-51`); the stand-in reads the same
   target from the helper text. Cost: one more placeholder in the helper text.
8. **Abandoned play before transform is counted, both ways** (review ruling 2). The year rule reads converted Parquet,
   as the start-year ruling fixes ("Park 1's last managed year comes from its park_snapshot game dates in converted
   Parquet"), so it cannot tell kept days from abandoned ones (ADR 0024). Abandoned managed days can refuse a run (a
   try-out branch that played into a later year raises that park's latest managed year) and can also allow one (Park 2
   tries a branch into Y + 2, abandons it and reloads its Y + 1 save; Park 1 may then run Y + 2 although Park 2's kept
   timeline is in Y + 1). ADR 0049 and the `AGENTS.md` command entry record the second case. Gain: no kept-timeline
   read, so the rule works before `make transform`. Cost: the allowed-wrong-run case is guarded only by documentation.
9. **The game-folder copy never replaces a file.** `BackupPlan` gains `replace_own_copy: bool = True`; the autopilot
   passes `False`, so an existing same-day dated copy, even the command's own, gets a `-HHMMSS` sibling instead
   (`save_backup.py:239-244`). Gain: the roadmap's "never overwrites a file in the game's save folder" holds literally.
   Cost: one extra file in the game's save folder when two runs of one park end on one day.
10. **The dated name keeps the wall-clock date** (`<park name>-last-plugin-save-YYYY-MM-DD.park`, ADR 0048). Gain: the
    pre-play warning and `is_own_copy` already know it. Cost: the name does not say which game year it holds.
11. **The label column is added in staging, as the roadmap names it** (roadmap :137): `stg_session_start` left-joins a
    new `stg_session_play_mode` on `session_id` and fills `managed` when no row matches. Gain: the pass/fail line holds
    as written. Cost: a staging-to-staging join, which `docs/CONVENTIONS.md` section 4 reserves for intermediate; ADR
    0049 records the departure.
12. **The real-game test is switched by an environment variable** (`OPENRCT2_AUTOPILOT_REAL_GAME=1`), not a pytest
    marker. Gain: `pyproject.toml` (a hotspot) is not touched. Cost: the skip reason shows only in `-ra` output.
13. **The work folder is removed after a fully successful run and kept after any failure; a kept folder never blocks.**
    Its name holds the UTC time, so `check_work_folder` (`bench_setup.py:240-251`) is given only that name; the report
    lists the park's kept folders. Gain: every failure keeps its evidence without stopping the next run. Cost: kept
    folders pile up until removed by hand.

**R18, the missing 2026-11-12 backup: no code defect is visible.** Every path that skips the backup prints its own
line and matches the safe-play spec (`docs/ai-dlc/specs/safe-play.md`, Part 2). Likely causes, from the code alone:
one ambiguous save anywhere in the run fails the whole run's pairing (`save_pairing.py:227-232`) and skips every
park's backup with "No backup made: this run had a capture problem" (`capture_session.py:380-382`); or a write after
the last paired save (for example the save offered on quit, if its `save_written` event did not land) skips that park
with "No backup made for park ... newer unrecorded play may exist" (`save_backup.py:150-161`); the other four
candidates of `autopilot-year.md` section 5 each print a distinct line. The 2026-11-12 report's "Save files" and
"Backup" lines settle which one happened; the overnight run writes that question as a waiting-on-owner row (section
14), and the build does not wait for it. Until one healthy `make play` run of Park 1 ends with a "Backup:" line, the
command refuses Park 1 (refusals 14 to 16).

## 3. Placement plan

One owner per rule. "Layer" is the package or dbt layer that holds it.

| Rule | Owner (new or changed) | Reuses | Read by | Layer |
|---|---|---|---|---|
| Company year of a game date; managed days with the 1 March year-end rule; the autopilot year verdict | `src/openrct2_analytics/domain/company_years.py` (new, pure) | nothing | `managed_years.py`, `autopilot_year.py`; the start-year item | domain |
| Each park's latest registry row: start year, game-year origin, data set, practice flag | `src/openrct2_analytics/ingest/registry_feed.py` (changed: one reader, latest row by delivery file as `int_park_registry__history.sql:86-91` orders it) | `FILE_GLOB` | `managed_years.py`; `register_parks.registered_parks` (`register_parks.py:69`, rebuilt on it, so the latest-row rule has one owner) | ingest |
| Read the year rule's inputs before transform: converted `park_snapshot`, `save_written` and `session_start`, the registry, the label feed; the stale-Parquet scan of refusal 12 | `src/openrct2_analytics/ingest/managed_years.py` (new; public: `unconverted_raw_file(raw_dir: Path, parquet_dir: Path) -> Path \| None`, which treats a missing raw folder as clean and raises nothing for a stale file, so each caller raises its own refusal; and `latest_managed_year(parquet_dir: Path, registry_dir: Path, park_id: str) -> int \| None`, the park's latest managed company year, where a missing `park_snapshot.parquet` or `save_written.parquet` means no managed days) | the registry reader; `play_mode_feed` reader | `autopilot_year.py`; the start-year item | ingest |
| Label and ready-mark delivery: name shape, reading, checking, check command | `src/openrct2_analytics/ingest/play_mode_feed.py` (new) | `registry_feed.refuse_aliases`, `registry_dir`, `absolute_path`, `INCOMING`, the contract-lint pattern of `registry_feed._check_files` | Makefile `check`, `contracts`, `transform`; `publish_contracts.py`; `publish_snapshot.py`; `delete_plan.py`; `delete_apply.py`; `managed_years.py`; `autopilot_land.py` | ingest |
| Per-run pairing of records and `save_written` rows | `src/openrct2_analytics/ingest/save_pairing.py` (changed: the loop of `judge_saves`, lines 216-221, becomes one public function) | `cut_rows`, `pair_run` | `judge_saves`, `autopilot_source.py` | ingest |
| The park's last recorded save across runs, and the archive copy that proves it | `src/openrct2_analytics/ingest/autopilot_source.py` (new) | `save_files.read_records`, `read_save_written`; the public pairing function; `save_backup._archive_files` (made public) | `autopilot_year.py` | ingest |
| The run: work folder, helper, watcher, play to the stop, work-folder checks | `src/openrct2_analytics/ingest/autopilot_run.py` (new) | `bench_setup.make_run_folder`, `RunInputs`, `AUTOSAVE_NEVER`, `file_sha1`; `bench_play.play`, `Bench`, `Options`; `bench_sample.SaveLanded`; `rehearsal_chain._raw_problems` (made public); `save_watch.SaveWatcher`, `watch_folders`; `capture._start_time` (made public); `convert.convert`; the contract check of `make contracts`; `save_files.check_folder`; `save_pairing.judge_saves` | `autopilot_year.py` | ingest |
| When the helper plugin arms and saves | `src/openrct2_analytics/ingest/rehearsal_helper.py` (changed: optional target year) | nothing | `rehearsal_chain.py` (no target), `autopilot_run.py` | ingest |
| Append a checked capture to company data | `src/openrct2_analytics/ingest/autopilot_land.py` (new) | `lock.hold_lock`, `convert.landing_lock_path`, `set_signal_handlers`, `Interrupted`; `play_mode_feed` checker | `autopilot_year.py` | ingest |
| The command: options, refusals in order, exit codes, report | `src/openrct2_analytics/ingest/autopilot_year.py` (new) | `capture.refuse_unless_closed`; `bench_setup.check_no_live_game`, `check_work_folder`, `check_ports`, `wait_for_low_load`, `game_version`; `plugin_install.build_plugin`; `capture_session.convert_and_report`; `save_backup.BackupPlan`, `back_up` | Makefile `autopilot-year` | ingest |
| The success report: the dated copy to load and the end lines | `src/openrct2_analytics/ingest/autopilot_report.py` (new; split from `autopilot_year.py` for the line limit) | `capture_session.say`; `save_backup.BACKUP_MARK` | `autopilot_year.py` | ingest |
| Settings without the benchmark fixture | `src/openrct2_analytics/ingest/bench_setup.py` (changed: `load_settings(system, *, park=None)`, below) | existing setting names | `autopilot_year.py` | ingest |
| The game-folder copy never replaces a file | `src/openrct2_analytics/ingest/save_backup.py` (changed: `BackupPlan.replace_own_copy`) | `_game_copy` | `capture.py` (default `True`), `autopilot_year.py` (`False`) | ingest |
| The label in the warehouse | `models/staging/stg_session_play_mode.sql` and `.yml` (new); `models/staging/stg_session_start.sql` and `.yml` (changed); `models/staging/_sources.yml` (generated) | `scripts/generate_dbt_sources.py` registry branch (lines 44-58) | every model that reads `stg_session_start`; nothing reads `play_mode` yet | staging |
| House rules accept the new staging model | `scripts/dbt_rules.py` (changed: the registry model becomes a set of reference-feed models) | `REGISTRY_MODEL` handling | `scripts/check_dbt_rules.py` | scripts |
| Company year Y + 1 stays open until both parks hold all its statements | `models/intermediate/int_park_years__year_close__unit_tests.yml` (one case added; no model change expected) | `int_park_years__year_close.sql` (`close_status`, lines 196-206; `is_company_year_closed`, lines 208-217) | dbt | intermediate |

**Settings.** `load_settings` gains a keyword `park: Path | None = None`. A given path replaces `OPENRCT2_BENCH_PARK`
and skips its file check (`bench_setup.py:155,159-160`), because the caller proves its own source; `BenchSettings.park`
stays a required `Path`, so other callers are unchanged. The command passes the park's archive folder path (computed,
not read) at refusal 3 and swaps in the chosen copy with `dataclasses.replace` after the source proof. Gain: no new
settings type and no data read before the settings check. Cost: for a short span the field holds a folder. A relative
`OPENRCT2_BACKUP_DIR` (`config.py:118` keeps it relative) is resolved against `project_dir`, not the caller's folder.
`config.py` is at its 200-line cap and gains nothing; every new file stays under 500 lines.

Golden examples to imitate (`docs/CONVENTIONS.md` section 5; paths under `src/openrct2_analytics/ingest/` unless
given): the command and its seams, `rehearsal_capture.py` (`main`, lines 311-316; refusal order, lines 276-302); the
staged landing, `rehearsal_land.py` (lines 365-390, 420-465); a delivery written through the landing protocol,
`register_parks.py` (lines 108-116, 205-214); a feed checker, `registry_feed.py` with
`contracts/reference/park_registry.odcs.yaml`; pure logic, `src/openrct2_analytics/domain/example_service.py`; stand-in
game tests, `tests/bench_standin_game.py` with `tests/test_rehearsal_capture.py`; the helper's test,
`tests/test_rehearsal_helper.py` with `tests/rehearsal_helper_context.mjs`; staging,
`models/staging/stg_save_written.sql` and `stg_park_registry.sql`; dbt unit tests,
`models/intermediate/int_park_years__year_close__unit_tests.yml`.

## 4. The command

`make autopilot-year DATA_SET=company PARK=<park id> [READY="<phrase>"]`, which runs
`python -m openrct2_analytics.ingest.autopilot_year --data-set company --park <id> [--ready "<phrase>"]`.

- `autopilot-year` joins `DATA_SET_GOALS` (`Makefile:10`), so it takes `DATA_SET` on the command line only. The
  Makefile refuses an exported `PARK` or `READY`, as it refuses an exported `PARKS`.
- The ready phrase is exactly `<park id> is profitable and its scenario challenge is complete`. It is needed only on
  a park's first autopilot run (decision 4).
- Exit codes, as every data command: 0 landed, 1 a run, check, landing or backup problem, 2 refused (nothing written),
  130 interrupted. Through `make`, any failure is make's own non-zero code.
- The success report names the dated copy in the game's save folder as the file to load for a refurbish, and says the
  park's older saves are now one game year behind: loading one under `make play` starts a newer session on the older
  branch, and the autopilot year leaves the kept timeline (ADR 0024 lines 24-25). Its last line is `autopilot-year:
  park <id> played company year <T> to 1 March of game year <g + 1>; landed session <session id> (<N> events) and
  labeled it autopilot.`

### Refusals, in order (exit 2; each ends "Nothing was written.")

Order (review ruling 6): cheap checks, then the checks that guard the folders, then the game checks, then the data
reads; the load-average wait (up to 300 s) and the plugin build come last, so no data refusal waits on the load.

| # | Refusal | Text |
|---|---|---|
| 1 | `--data-set` missing or not `company` | "autopilot-year runs only on the company data set; give DATA_SET=company." |
| 2 | `--park` missing | "Give PARK=<park id>." (no data is read to list parks) |
| 3 | Settings missing or invalid; work folder nests with the player's OpenRCT2 folder | the existing `bench_setup.load_settings` text |
| 4 | Write boundary (section 6): a landing folder is a link or aliases another data set or a protected folder; the work folder overlaps a protected folder | new text naming the folder |
| 5 | A `.incoming-*` leftover in a company landing folder (as `register_parks.py:112-115`) | "Staged file <name> already exists in <folder>; a killed landing left it." |
| 6 | The new work folder's name already exists (`check_work_folder` with that name only) | the existing `check_work_folder` text |
| 7 | The game binary does not answer `--version` (where `rehearsal_capture.py:292` has it) | the existing text |
| 8 | The game is running (process check) | the existing `capture.refuse_unless_closed` text |
| 9 | The player's newest autosave is under 10 minutes old | the existing `bench_setup.check_no_live_game` text |
| 10 | Port 8765 or 11799 busy | the existing `bench_setup.check_ports` text |
| 11 | `data/company/parquet.lock` present | "data/company/parquet.lock is present: a convert, landing or delete is running, or a killed run left it." |
| 12 | The converted Parquet or its audit is missing, or any `raw/v1/events-*.jsonl` holds a `session_id` missing from `session_start.parquet` (review ruling 7; the command calls `managed_years.unconverted_raw_file` for this and raises the refusal itself) | "<file> holds a session that was never converted; run make convert DATA_SET=company first." (or "No converted data; run make convert DATA_SET=company first.") |
| 13 | Park not in the company registry; or registered as practice (`register_parks.NOTE`) | "Park <id> is not a registered company park; register it with make register-parks DATA_SET=company first." / "Park <id> is registered as a throwaway practice park; autopilot runs only company parks." |
| 14 | No archive copy | "Park <id> has no backup in <archive dir>/<id>/. Play and save it with make play DATA_SET=company, quit normally, and check that the report prints a Backup: line." |
| 15 | The park's latest `save_written` is not paired with exactly one file | "The last save of park <id> (recorded <time>) was not matched to exactly one save file, so its last recorded save is unknown. Play and save it once with make play DATA_SET=company." |
| 16 | The newest archive copy fails the proof (decision 1) | "The newest backup of park <id> (<file>) is not its last recorded save (<file name>, recorded <time>); starting from it would drop the play recorded after it. Play and save once with make play DATA_SET=company so a new backup is made." |
| 17a | Year rule: no other park has a managed day in T (section 5) | "Park <id> would play company year <T>, but no other registered company park has a managed day in <T> yet. An autopilot park runs only a company year the managed park runs; play the managed park into <T> first." When parks wait to register, it adds: "Waiting to register (they count once registered): <id> (<park name>), ...." |
| 17b | Year rule: the park itself has a managed day in T | "Park <id> is itself the managed park of company year <T>. Play it by hand to 1 March of the next game year, save, and quit, with make play DATA_SET=company." |
| 18 | First autopilot run (decision 4) without `READY`, or with a different phrase | "This is park <id>'s first autopilot run. Confirm it is ready with READY=\"<id> is profitable and its scenario challenge is complete\"." |
| 19 | One-minute load average stays at or above 3.0 for 300 s | the existing `bench_setup.wait_for_low_load` text |
| 20 | The plugin does not build | the existing text |

When both 17a and 17b hold, 17b is shown (the verdict order of section 5).

### Exit 1 and 130 texts

- The game stopped, timed out or never saved: "The autopilot run did not reach 1 March of game year <g + 1>:
  <reason>. Company data was not touched; the run folder is kept at <path>."
- A work-folder check failed, including the staged label check: "The autopilot run failed its checks: <one line per
  problem>. Company data was not touched; the run folder is kept at <path>."
- The landing lock stayed taken past the wait (section 6): "The company landing lock is held (<holder line>); nothing
  was landed. The run folder is kept at <path>; rerun make autopilot-year when the other command ends."
- A landing step failed: "Landing failed at <step>: <error>. Landed: <list>; no raw session landed. The run folder is
  kept at <path>." (Decision 6 says how the listed files are removed.)
- The convert, report or backup after landing failed: the existing `convert_and_report` and `back_up` lines, including
  "The recorded data is fine; only the backup copy failed." A backup failure adds the recovery steps: "To make the
  backup: copy <path of the end-of-year save in the run folder> into <game save folder>, load it with make play
  DATA_SET=company, save while paused, and quit. The next autopilot run of this park is refused until then."
  A failure of the dated copy alone (the archive copy was made) exits 1 without the recovery steps, because the next
  run is not refused.
- Interrupted (130) before the first link: "Interrupted; company data was not touched; the run folder is kept at
  <path>." From the first link to the end of the report, signals are ignored (as `capture_session.py:342` does after
  a quit), so no interrupt text can claim untouched data after the landing began.

## 5. Year rules

Definitions (owned by `domain/company_years.py`; review ruling 1):

- **Company year of a game year** = the park's `company_start_year` + (game year − `game_year_origin`), from the
  park's latest registry row (roadmap :92, "The company timeline").
- **Managed day**: a `park_snapshot` of a registered company park (not practice) in a session the label feed does not
  list as `autopilot`, whose `seq` is at or below that session's last `save_written` `seq`. Play after a session's last
  save is never kept (ADR 0024 line 20), so it never counts; a session with no `save_written` has no managed day. Both
  inputs are in the converted Parquet, so the rule works before `make transform`. Before any label exists, every
  session is managed (R12).
- **The 1 March year-end day**: a managed day dated 1 March of game year g counts toward g − 1 when the same session
  also has a managed day in game year g − 1 (by its game date) or its `session_start` is dated in game year g − 1;
  otherwise it counts toward g. The `session_start` test is needed because the plugin emits `park_snapshot` only on a
  day change (`plugin/src/main.ts:58`, `:136`), never on load, while `session_start` carries the game date the save
  loaded at (`plugin/src/emit.ts:52-54`; `contracts/session_start.odcs.yaml:21`): a session resumed from a late-October
  save has no managed day before 1 March. Basis: roadmap :127 calls a stop on 1 March of the next game year "before
  any day of the next year is played".
- **"A managed session in Y + 1"** (roadmap :127) is read as "a managed day in Y + 1": a session shorter than one game
  day has no `park_snapshot`, so it cannot be placed in any year.
- **Latest managed company year of a park** = the largest company year of its managed days.
- **Target year T of a run** = the company year of the source save's game date (read by `event_id`, decision 1). A
  source saved on 1 March of game year g gives T = the company year of g, the year the run plays.
- **Verdict**: a run of park P is allowed when P has no managed day in T and some other registered company park Q has
  at least one managed day in T. The run never passes T's end, because the helper stops on 1 March of game year g + 1.

Unit cases in `tests/test_company_years.py`, on plain values. Park 1 has origin 1 and start year Y; Park 2 has origin 1
and start year Y + 1; "day (g, M D, seq s)" is a `park_snapshot`, "save s" a `save_written` at `seq` s.

| Case | Inputs | Expected | Source |
|---|---|---|---|
| Days after a session's last save never count | One Park 1 session: days of game year 1, then 1 March of year 2 (seq 900), save 905, then 2 March of year 2 (seq 910) | 2 March is not a managed day; Park 1's latest managed year is Y | review ruling 1; ADR 0024:20 |
| A session that ends on 1 March closes the year before | As above without the 2 March day | 1 March of year 2 counts toward year 1; latest managed year Y | review ruling 1 |
| A session that starts on 1 March | A second Park 1 session loads the 1 March save: day (2, 1 March, seq 1) ... day (2, 20 March, seq 200), save 210 | its 1 March counts toward year 2; latest managed year Y + 1 | review ruling 1 |
| A session resumed from 31 October closes the year before | A Park 1 session loads a 31 October save of game year 1 (its `session_start` is dated 31 October, year 1; no `park_snapshot` is emitted on load), plays to 1 March of year 2 (seq 40) and saves there (seq 45) | its 1 March counts toward year 1, not year 2; latest managed year Y | review ruling 1 (S-2 amendment); `plugin/src/main.ts:58` |
| Park 2's first session starts on 1 March of game year 1 | Park 2: day (1, 1 March, seq 1) ... day (1, 10 March, seq 90), save 95 | every day counts toward game year 1 = company year Y + 1 | review ruling 1 |
| A park that plays several years | One session from 1 March of year 1 to 1 March of year 4, saved there | the 1 March days of years 2, 3 and 4 count toward 1, 2 and 3; the 1 March of year 1 counts toward 1; latest managed year Y + 2 | review ruling 1 |
| Roadmap 1: Park 1 is refused Y + 1 until Park 2 has a managed session in Y + 1 | Park 1 managed to its save on 1 March of game year 2 (T = Y + 1); Park 2 registered, no session | refused, 17a | roadmap :127 |
| Roadmap 2: Park 1 may then run Y + 1 | as above, plus one Park 2 managed day in Y + 1 | allowed | roadmap :127 |
| Roadmap 3: Park 1 is refused Y + 2 while Park 2's latest managed year is Y + 1 | Park 1's `autopilot` session through 1 March of game year 3 (T = Y + 2); Park 2 managed days only in Y + 1 | refused, 17a | roadmap :127 |
| Roadmap 4: company year Y + 1 stays open until both parks hold all its statements | dbt unit case in `int_park_years__year_close__unit_tests.yml`: Park 2 holds Y + 1 months 0 to 7; Park 1 holds months 0 to 3 | Park 1's Y + 1 `close_status` is `open` and `is_company_year_closed` is false on both parks' Y + 1 rows; with Park 1's months 0 to 7, Park 1 is `complete` and `is_company_year_closed` is true on both | roadmap :94, :127 |

Further cases: the park is itself the managed park of T (17b); a practice park and an unregistered park never count
as Q; an `autopilot` session never counts as managed; Park 1's own managed days never let Park 1 run. Roadmap cases 1
to 3 also run through `main` in `tests/test_autopilot_year_refusals.py`.

## 6. The run and the landing

### Work folder and play

1. The work folder is `<OPENRCT2_BENCH_DIR>/autopilot-<park id>-<UTC time>/`, created fresh by `make_run_folder`
   (`bench_setup.py:371-392`) with `RunInputs(..., AUTOSAVE_NEVER, rehearsal_helper(<park id>-autopilot-<g + 1>,
   target_year=g + 1), debugging_tools=True)`, as `rehearsal_chain.py:168-175` builds them. The built plugin and the
   helper go only into its own plugin folder. The source is copied in; its SHA-1 is checked before and after the run.
2. Write boundary (a company variant of `rehearsal_capture.check_write_boundary`, `rehearsal_capture.py:150-196`): the
   work folder must not equal, contain or lie inside the player's OpenRCT2 folder, the archive folder, `data/sample/`,
   `data/rehearsal/`, `data/company/` or `plugin/src/`; the company landing folders (`raw/v1`, `save_files/v1`,
   `registry/v1`) must not be links or alias another data set. The only other writes are the landing into those
   three folders, the company convert, the archive copy and the dated copy in the game's save folder.
3. In this order: `started = capture._start_time()` (made public as `start_time`; whole milliseconds, as
   `received_at` is, `capture.py:184-187`); a `SaveWatcher` on the work folder's `user-data`
   (`save_watch.watch_folders`) is started with `started` and writes its records into the work folder;
   `bench_play.play` runs the game on port 8765 into the work folder's raw folder with stop condition `SaveLanded` on
   `<park id>-autopilot-<g + 1>.park`; then `watch = watcher.stop()` (`save_watch.py:230-258`), before any check reads
   a record. The same `started` and `watch` go to the report after landing, so pairing finds this run
   (`save_pairing.py:216-222`).
4. Timeout: 3.0 s per planned game day plus 300 s (`rehearsal_chain.py:43-44`), where planned days run from the source
   date to 1 March of game year g + 1 (at most 245).

### Checks in the work folder (all must pass before landing)

- `convert` succeeds with no schema error, no `seq` violation and no malformed line (`ConvertResult.ok` ignores
  malformed lines, `convert.py:82-85`; `rehearsal_land.py:244` checks them).
- `raw_problems` (made public from `rehearsal_chain.py:116-158`): exactly one `session_start` and one `session_id`, and
  every non-warm-up `plugin_stats` line at game speed 8. New code: every converted row's `park_id` equals the park
  (`_raw_problems` does not check it).
- Continuation: the session's `loaded_save_id` and `loaded_save_session_id` equal the source save's `save_written`
  event (ADR 0024 decision 2a).
- October: a `finance_month` row with `statement_year` = g and `statement_month` = 7 (`finance.ts:55-57`).
- The stop: one `save_written` dated 1 March of game year g + 1, and no `park_snapshot` dated after 1 March of g + 1
  with a `seq` below that event's `seq`.
- The contract check of `make contracts` passes on the work folder's Parquet, and `save_files.check_folder` on its
  records.
- `judge_saves` on the work folder's records and Parquet is not failed and holds exactly one pair, the end-of-year
  save.
- Registry (run ruling 2): the park's latest registry row is still a company, non-practice row, and the staged label
  delivery passes the `play_mode_feed` checker together with the existing deliveries (so the one-row-per-session rule
  is tested) before the first link. A failure means nothing landed.

### Landing (`autopilot_land.py`), under the company landing lock

The landing takes `convert.landing_lock_path` with `lock.hold_lock`, which fails at once when the lock exists
(`lock.py:67-83`), so it retries every second for up to 120 seconds before the lock text of section 4. Gain: a
`make convert` that is running when the game stops no longer wastes the run. Cost: up to two minutes of waiting.
Signals are ignored from the first link to the end of the report. Then, in order:

1. The label delivery `registry/v1/session_play_mode_<local date>_<NN>.csv` (next free `NN`, as `register_parks.py`
   numbers deliveries) with one row: the session, the park, `autopilot`, the ready phrase on a first run, `company`,
   the date.
2. The work folder's record files, each keeping its own stem plus `-autopilot-<session id>`
   (`save_files/v1/save_file_observation_<date>-autopilot-<session id>.jsonl`); a run across UTC midnight has two
   (`save_watch.py:312-314`).
3. One raw file, `raw/v1/events-<UTC date of the first file>-autopilot-<session id>.jsonl`: the work folder's raw
   files joined in name order.

Both names match the existing globs (`convert.py:392`, `save_pairing.py:24`). Each file is written under a temporary
name starting `.incoming-` in its target folder and placed with a hard link, which fails when the name exists. The
lock is then released and `capture_session.convert_and_report` runs on the company folders with `started`, `watch`,
and a `BackupPlan` whose source folders are the run's watched folders, whose game-folder target is
`<OPENRCT2_USER_DIR>/save`, and whose `replace_own_copy` is `False`: the same convert, report, pairing and backup that
`make play` runs (`capture.py:269-274`).

## 7. The label feed and the warehouse

- **Reference contract** `contracts/reference/session_play_mode.odcs.yaml`, version 1.0.0, outside the event version
  line (as `park_registry.odcs.yaml`). CSV header: `session_id,park_id,play_mode,ready_confirmation,data_set,
  delivered_on`; every field but `ready_confirmation` is required. Rules: `play_mode` in (`managed`, `autopilot`);
  `session_id` unique across every delivery of the folder; `ready_confirmation` empty or exactly the ready phrase for
  its `park_id`; each park's first `autopilot` row in delivery order (file name, then row) carries the ready phrase;
  `data_set` equals the folder's data set; `delivered_on` equals the date in the file name; name shape
  `session_play_mode_YYYY-MM-DD_NN.csv`, `NN` 01 to 99.
- **Checker** `python -m openrct2_analytics.ingest.play_mode_feed` (`--data-root` or `--data-set`; exit 0 clean, 1
  failed, 2 refused), run by `make check` on the sample (beside `Makefile:113`), by `make contracts` (beside
  `Makefile:178`), by `make transform` (beside `Makefile:187`) and by the publish contract step
  (`publish_contracts.py:24`). A folder with no label file is clean.
- **Sample**: one header-only file `data/sample/rehearsal/registry/v1/session_play_mode_2026-11-13_01.csv`, so the
  sample build and the zero-row build (which uses the sample registry, `Makefile:126-132`) read a real file. Three
  tests read that folder with `next(...glob("*.csv"))`, which then depends on directory order on the Linux CI runner:
  `tests/test_delete_data_run.py:113-119` and `tests/test_delete_data.py:339-342` and `:386-389` change to glob
  `park_registry_*.csv`.
- **dbt source** `registry.session_play_mode`, generated into `models/staging/_sources.yml` by an extended
  `scripts/generate_dbt_sources.py`, reading `<registry root>/v1/session_play_mode_*.csv` with the same `read_csv`
  options as the registry source. The generator emits the registry-root expression (today only inside
  `REGISTRY_LOCATION`, `generate_dbt_sources.py:48-52`) once, as a macro or a source `meta` value, used by both
  sources and by the guard below, so the default never has two copies.
- **A data set with no label file must still build** (company before its first autopilot run; rehearsal). DuckDB's
  `read_csv` fails on a pattern that matches no file, and it binds every CTE of a query, used or not. So the executed
  SQL of `stg_session_play_mode` names the source only in the branch taken when DuckDB's `glob()` finds a file (a
  `run_query` inside `{% if execute %}`); the other branch is a typed zero-row select. Lineage comes from the parse
  pass (`{% if not execute %}` emits the source) or a `-- depends_on:` comment; if a comment is used, the worker
  checks that `scripts/dbt_rules.py` still sees the source, since it strips comments (`dbt_rules.py:284-292`). The
  worker's DuckDB test proves the behavior first.
- **Staging**: `stg_session_play_mode` (one row per labeled session; key `session_id`; `unique` on `session_id`;
  `not_null` on every required contract field, `session_id`, `park_id`, `play_mode`, `data_set`, `delivered_on`;
  `accepted_values` on `play_mode`; `meta.contract_version: 1.0.0`), as `scripts/dbt_rules.py:195-211` and `:264-281`
  require. `stg_session_start` reads `ref('stg_session_play_mode')` in its own import CTE and adds `play_mode` =
  `coalesce(label.play_mode, 'managed')` by a left join on `session_id` in `final`, after the dedupe
  (`docs/CONVENTIONS.md:148`). Its YAML adds the column with `not_null` and `accepted_values: [managed, autopilot]` and
  a description that passes rule b (unit and clock), modeled on `headless` (`stg_session_start.yml:75-77`).
  `meta.contract_version` stays 1.8.0. Its two existing unit tests (`stg_session_start.yml:93` and `:465`) each gain a
  `ref('stg_session_play_mode')` input and the `play_mode` column in their expected rows.
- **Publish**: `publish_snapshot.py:47` copies `session_play_mode_*.csv` as well as `park_registry_*.csv`.
- **Delete** (`make delete-company-data`): `delete_plan.py:194-200` rewrites label files under `PARK=` (through
  `_registry_change`, which keys on `park_id`) and under `SESSION=` (a new filter on `session_id`). `_selected`
  (`delete_plan.py:145-151`) counts label changes before it refuses `unknown-id`, so `SESSION=<id>` removes an orphan
  label row that no raw line carries. `delete_apply.apply` runs the registry and label checks whenever
  `plan.scope.named`, not only under `PARK=` (`delete_apply.py:114-117`). `_company_candidate`
  (`delete_apply.py:25-42`) reads only `park_registry_*.csv`, so a header-only label file never hides a candidate. The
  "not its park's latest" note orders sessions by the latest `received_at` of their raw lines, not by file name
  (`delete_plan.py:182`, `:212-215`), because `events-<date>-autopilot-...jsonl` sorts before `events-<date>.jsonl`.
  Gain: the note names the right session. Cost: the plan reads one more field per raw line.
  `named_plan` also refuses, before any change (as `PublishRefused("ready-phrase-row", ...)`, like `unknown-id`), a
  `SESSION=<id>` delete of an autopilot session whose label row holds its park's ready phrase while another autopilot
  session of that park remains: "session <id> holds the ready phrase of park <park_id>; other autopilot sessions of
  that park remain: delete them all with PARK=<park_id>." Gain: the label check cannot fail after files changed.
- **Not touched**: the plugin, the 14 event contracts and their 1.8.0 line, `convert.py`, the committed Parquet
  sample, `dbt_project.yml`, `pyproject.toml`, `package.json`.

## 8. Tests and seams

**Seams.** `autopilot_year.main(argv, *, options=None, build=None, project_dir=REPO_ROOT, game_check=None)`; the
command line never sets the keywords. Tests point `OPENRCT2_BINARY` at `tests/bench_standin_game.py` (as the
rehearsal tests do), `OPENRCT2_DATA_DIR`, `OPENRCT2_BACKUP_DIR`, `OPENRCT2_BENCH_DIR` and `OPENRCT2_USER_DIR` at
temporary folders, and shrink ports, timeouts and the lock wait through the options. Stand-in scripts set `speed: 8`
(`tests/bench_standin_game.py:33-34`). The stand-in gains script keys for a start game date, `finance_month` rows on
each day 1 and `session_start` lineage keys read from the loaded park's marker; it reads the target year from the
helper text, as it reads `SAVE_FILENAME` (`tests/bench_standin_game.py:225-228`), and saves on 1 March of that year.

Every test is first run against a deliberately broken version and seen to fail (`engineering-standards.md`, Tests).

- `test_company_years.py`: the cases of section 5, including a session whose `session_start` is dated 31 October of
  game year g − 1 and which plays to 1 March of g with a save there (that 1 March counts toward g − 1).
  `test_managed_years.py`, on planted Parquet, registry and label
  files: practice and unregistered parks ignored; `autopilot` sessions and days after a session's last save excluded;
  no label file means every session is managed; the registry reader's latest row wins; a session resumed from a 31
  October save counts its 1 March toward the year before, read from its `session_start` date.
- `test_play_mode_feed.py`: each checker rule passes a good file and fails a planted bad one (including a first
  `autopilot` row without the phrase); an empty folder is clean.
- `test_autopilot_source.py`: the newest copy by the time at the end of its name, also after a park rename; the proof
  by size and modified time; refusals 14 to 16 from real files. `test_save_pairing.py`: the extracted per-run function
  leaves `judge_saves` unchanged.
- `test_autopilot_year_refusals.py`: every refusal of section 4 in order, nothing written (folder listings compared);
  refusal 12 for a missing Parquet, a missing audit and an unconverted managed raw file; 17a with a waiting park; 17b;
  a later run with a wrong `READY` runs and reports it ignored.
- `test_autopilot_year.py` (stand-in game): a full run lands label, records, then one raw file; the report pairs the
  end-of-year save; the archive and dated copies exist; a same-day dated copy is left byte-identical beside a
  `-HHMMSS` sibling; the report names the file to load; the work folder is removed. Failures: an early exit; no
  October statement; a `seq` gap; a malformed line; a wrong `park_id`; lineage keys that do not match; a staged label
  that fails the checker (nothing lands); a run across UTC midnight (two record files, one joined raw file); a failure
  between two links (label and records landed, no raw); a taken lock (nothing lands); an interrupt during play
  (nothing lands; folder kept); an interrupt after the first link (ignored; the run finishes and reports).
- `test_save_backup.py`: `replace_own_copy=False` never replaces; the default still does. `test_rehearsal_helper.py`:
  with a target year, arming on 1 March of that year, from a start on 31 October and from a start whose first day
  callback is 1 March of the source year; the test at line 73 stays for the no-target mode. `test_makefile*.py`: the
  target, `DATA_SET_GOALS`, the refusal of exported `PARK` and `READY`.
- `test_delete_data*.py`: `SESSION=` removes an orphan label row; the label check runs after a `SESSION=` rewrite; a
  candidate with a header-only label file is still recognized; the latest-session note on a date with a managed and an
  autopilot raw file; a `SESSION=` delete of the autopilot session that holds the ready phrase while another autopilot
  session of that park remains is refused with the text of section 7 and changes no file; `PARK=<id>` removes them all.
- dbt: a unit test on `stg_session_start` (`format: sql` inputs) with one labeled and one unlabeled session; the two
  changed unit tests; the year-close case of section 5; a build over a registry folder with no label file
  (`tests/test_dbt_environments.py` pattern), which also runs the SQL lint and the docs build on that folder.
- **Real game, by hand**: `tests/test_autopilot_real_game.py`, skipped unless `OPENRCT2_AUTOPILOT_REAL_GAME=1`.
  - Step 1 lands a managed session: it plays a copy of the benchmark fixture (which starts on 6 March of game year 9,
    `docs/FINDINGS.md:31`) to 1 March of year 10 with a `SaveWatcher`, then runs `convert_and_report` with a
    `BackupPlan` on temporary company folders, as `make play` does after a quit. That gives a `save_written`, a paired
    record and an archive copy, and no label row.
  - Step 2 registers that park as company, plants one managed day of a second park in the same company year, and runs
    `main` with `READY` to 1 March of year 11: the park's first autopilot run, continuing step 1's save.
  - It asserts R15: the stop day and October statement, a clean `seq` audit, the contract check passing on the
    temporary data set, the ready phrase on the label row, and, from a dbt build of `int_sessions__lineage` over it,
    step 2's session kept as the child of step 1's save with the same `park_id`. It prints the game version. About two
    game years at speed 8: a few minutes.

## 9. Files

- **New:** the eight new modules of section 3; `contracts/reference/session_play_mode.odcs.yaml`;
  `models/staging/stg_session_play_mode.sql` and `.yml`; the sample header file; the new test files of section 8.
- **Changed:** every "changed" owner of section 3; `capture.py` and `rehearsal_chain.py` (a function made public each);
  `publish_snapshot.py`, `publish_contracts.py`, `delete_plan.py`, `delete_apply.py`; `tests/bench_standin_game.py`,
  `tests/test_delete_data_run.py`, `tests/test_delete_data.py`, `tests/test_rehearsal_helper.py` (new cases only);
  `Makefile` (target, `DATA_SET_GOALS`, the checker in `check`, `contracts`, `transform`).
- **Docs, in the same change:** ADR 0049 (decisions 1 to 8 and 11, with the allowed-wrong-run case of decision 8);
  `AGENTS.md` (the command entry, with that case); `ARCHITECTURE.md` ("Pipeline as built", "Environments and
  publishing"); the `docs/CONVENTIONS.md` module map and the departure of decision 11; a `docs/FINDINGS.md` row after
  the hand-run test.

## 10. Out of scope

- Changing the plugin, an event contract or the contract version line.
- A `--source` option, or starting from anything but the archive (run ruling 1).
- Using `play_mode` in any intermediate model or mart (`session-label.md` section 5 lists the later consumers).
- A kept-timeline read in the year rule (review ruling 2).
- Who owns the one kept day of the next company year (`docs/FINDINGS.md:84` follow-up).
- Deleting the archive folder or dated copies on `make delete-company-data` (ADR 0048 consequences).
- Automatic or scheduled runs; running several years in one command; retrying or re-landing a failed run.
- A pre-play warning when a park's newest recorded save is an autopilot save (named follow-up; the success report
  covers the case for now).
- Fixing the 2026-11-12 backup gap, beyond the finding of section 2.

## 11. Constraints

Every repo invariant (`AGENTS.md`, "Never break") binds every ticket. How this item meets the ones it touches:

- `seq` with no gaps or repeats: the work-folder audit enforces it before landing.
- Raw captures are append-only: the command only adds new raw, record and label files and never rewrites one; the
  pre-go-live exception stays with `make delete-company-data` (ADR 0033).
- No game files or private machine paths in git: no `.park` file, work folder or archive is committed; tests use
  temporary folders and the fixture by path only.
- Versioned contracts: the new reference contract starts at 1.0.0 on its own line; no event contract changes.
- ES5 plugin within its tick budget: the plugin is unchanged; the helper is ES5 and lives only in the run folder.
- The 3.0 load limit and the live-autosave, port and process checks are reused, never loosened (run ruling 6). Money,
  build previews and sample statements are not affected.
- One owner per hotspot per ticket: `Makefile`, `contracts/`, `models/staging/`.

## 12. Verify by

Run from the worktree, with `UV_CACHE_DIR` set to a folder under `$TMPDIR`.

0. **The roadmap's cheapest test, first** (roadmap :128; review ruling 3). Before the build, when the game is free: one
   headless run on OpenRCT2 0.5.6 of a copy of the benchmark fixture with the existing rehearsal helper, in a scratch
   folder outside the repo, then `make convert` and the kept-timeline models on the copy. Pass: one `save_written`
   dated 1 March of game year 10, October's statement of year 9, no `park_snapshot` after 1 March of year 10 below the
   save's `seq`, a clean `seq` audit, and the session kept by `int_sessions__lineage`; the result is a FINDINGS row.
   Result (2026-11-13): the first probe failed R2, because 701 events followed the save, including `park_snapshot` for
   2 to 5 March of year 10 (a four-day overrun). The one fix round made the helper pause the game right after its save.
   The re-probe, two chained sessions, passed every check: no event dated after either save's 1 March, a clean `seq`
   audit, and session 2 loaded session 1's save, kept the park and played 1 March of year 10 to 1 March of year 11.
   The FINDINGS row records the numbers.
   The run's standing rulings: with no quiet window, the build proceeds on stand-in tests and the real run stays the
   hand check of step 3; a failed probe gets one fix round and one re-probe, and a second failure parks the autopilot
   and label items (the start-year item may still build).
1. Offline tests while building:
   `.venv/bin/python -m pytest tests/test_company_years.py tests/test_managed_years.py tests/test_play_mode_feed.py
   tests/test_autopilot_source.py tests/test_save_pairing.py tests/test_autopilot_year_refusals.py
   tests/test_autopilot_year.py tests/test_save_backup.py tests/test_rehearsal_helper.py tests/test_makefile.py
   tests/test_delete_data.py tests/test_delete_data_run.py -ra`
2. The gate: `make check` (about 20 minutes). It must pass with `tests/test_autopilot_real_game.py` reported as
   skipped.
3. By hand, on a machine with the game and the benchmark settings (`OPENRCT2_BINARY`, `OPENRCT2_BENCH_PARK`,
   `OPENRCT2_GAME_PATH`, `OPENRCT2_USER_DIR`), with the game closed:
   `OPENRCT2_AUTOPILOT_REAL_GAME=1 .venv/bin/python -m pytest tests/test_autopilot_real_game.py -ra`
   Record the result and the game version as a `docs/FINDINGS.md` row.
4. The project owner's hand test (`verify: owner-later`), after the start-year item has merged: Park 1 played and
   saved through `make play` with its last managed save dated 1 March of Y + 1 (a later save makes Y + 1 Park 1's own
   managed year, so refusal 17b fires and Park 2's start year Y + 1 is refused) and a "Backup:" line in the report;
   Park 2 registered with start year Y + 1 and played and saved for at least one managed day; then
   `make autopilot-year DATA_SET=company PARK=<park 1 id> READY="<park 1 id> is profitable and its scenario challenge
   is complete"`, `make after-play DATA_SET=company`, and the queries of the Definition of Done.

## 13. Definition of done

- `check:` `make check` passes on the branch, with the real-game test skipped.
- `check:` each case of the section 5 table has a passing test; every refusal of section 4 has a test that shows its
  text, exit 2 and no file written.
- `check:` the stand-in run tests show the landing order, one raw file per session, the non-clashing names, the
  archive copy, an existing same-day dated copy left byte-identical, and the three landing failure cases (between
  links, taken lock, interrupt after the first link).
- `check:` a `SESSION=` delete of a ready-phrase autopilot session with later autopilot sessions of its park is refused
  before any change and names `PARK=<id>`; `PARK=<id>` removes them all.
- `check:` `stg_session_start.yml` declares `not_null` and `accepted_values: [managed, autopilot]` on `play_mode`, and
  the dbt unit test proves a labeled session is `autopilot` and an unlabeled one is `managed`.
- `check:` a build over a registry folder with no label file passes, labels every session `managed`, and passes the
  SQL lint and the docs build.
- `check:` `grep -rn 'registry/v1").glob("\*.csv")' tests/` prints nothing: no test reads the sample registry folder
  through `*.csv`.
- `check:` `git diff --stat` shows no change under `plugin/src/`, no event contract change and no change to
  `pyproject.toml`, `package.json`, `dbt_project.yml` or `src/openrct2_analytics/config.py`.
- `check:` by hand: `tests/test_autopilot_real_game.py` passes on OpenRCT2 0.5.6 (R15), with a FINDINGS row.
- `check:` owner, after the hand test: `select statement_month from marts.fct_park_month where company_year = <Y + 1>
  and park_id = '<park 1>'` returns 0 to 7, and `select park_id, close_status, is_company_year_closed from
  intermediate.int_park_years__year_close where company_year = <Y + 1>` returns `complete` for Park 1 and, once Park 2
  holds months 0 to 7, `is_company_year_closed` true on both rows.
- `judgment:` a reviewer reads the refusal and exit texts as plain and actionable, and confirms no message names a
  private machine path in committed text.
- `judgment:` a reviewer confirms ADR 0049, `AGENTS.md`, `ARCHITECTURE.md` and the `CONVENTIONS.md` module map
  describe the command and the feed as built, including the allowed-wrong-run case of decision 8.

## 14. Resolved after review, and the one owner row

Nothing here blocks the build: the draft's six owner questions are settled by the review record
(`docs/ai-dlc/ledger/autopilot-year.md`), and one becomes a waiting-on-owner row.

1. **The 1 March year-end day**: review ruling 1 (section 5); the roadmap's own meaning of the stop settles it.
2. **Where the label column lives**: in `staging.stg_session_start`, as the roadmap names it (decision 11); ADR 0049
   records the departure from the staging no-join rule.
3. **What the 2026-11-12 report printed** under "Save files" and "Backup": a waiting-on-owner row, written by the
   overnight run, not by the build (section 2, R18).
4. **"The year's close status is complete"**: Park 1's `close_status` and the company-wide `is_company_year_closed`
   (section 5, roadmap case 4; section 13).
5. **Order on the roadmap**: the run's order ruling: this item first, the start-year item stacked on it; the roadmap's
   `after:` line is left as is.
6. **Abandoned play before transform**: review ruling 2 (decision 8).

## 15. Game settings (amendment, 2026-11-13)

**Bottom line.** The game settings are found the way the Dock app finds the game, so nothing has to be typed or
exported for `make autopilot-year`, `make bench`, `make bench-sample`, `make capture-rehearsal` or the real-game test,
with one exception: `make capture-rehearsal` still needs `OPENRCT2_REHEARSAL_PARK2` exported, because it is not one of
the three game settings and the settings file refuses it as an unknown key.
The project owner asked for this in chat on 2026-11-13, after the design below was proposed. Gain: no exports. Cost:
one more place a setting can come from, so a wrong value can hide in a file; the refusal texts name the sources.

1. **Precedence.** For each of `OPENRCT2_BINARY`, `OPENRCT2_GAME_PATH` and `OPENRCT2_BENCH_PARK`: an exported
   environment value wins; else a value in `local/game-settings.env`; else the automatic default; else the command
   refuses.
2. **The settings file.** `local/game-settings.env` at the repo root, which is git-ignored. It holds `KEY=value` lines;
   `#` comments on their own lines and blank lines are allowed; one pair of matching single or double quotes around
   a value is removed (an unmatched quote stays in the value); a leading `~/` is expanded. A `#` comment after an
   unquoted value, a repeated key (the refusal names both lines), an empty value and a file that cannot be read are
   refused naming the file. Only the three keys above are accepted. Any
   other key, in particular `DATA_SET`, `PARKS` and `START_YEAR`, is refused with a message naming the file and the
   line, because data-set choices stay on the command line. A missing file is fine. Code reads the file and never
   writes it.
3. **Automatic defaults.** `OPENRCT2_BINARY` keeps the macOS app location. `OPENRCT2_GAME_PATH` is the `game_path` key
   of the `[general]` section of `config.ini` in the player's OpenRCT2 folder (the folder `resolve_user_dir` returns);
   only that file is read, read-only; a missing file, a missing key or a value that is not an existing folder means
   "not found". `OPENRCT2_BENCH_PARK` has no automatic default.
4. **One loader.** `load_settings` in `src/openrct2_analytics/ingest/bench_setup.py` does the lookup (the two files
   are read by `src/openrct2_analytics/ingest/game_settings.py`), so `make bench`,
   `make bench-sample`, `make capture-rehearsal`, `make autopilot-year` and the real-game test all get it.
5. **Refusals.** A value still missing is refused with what is missing and where to put it, for example
   "OPENRCT2_BENCH_PARK is not set. Add a line OPENRCT2_BENCH_PARK=<path to the benchmark .park file> to
   local/game-settings.env, or export it. Nothing was written." For `OPENRCT2_GAME_PATH` the text also says it was not
   found in OpenRCT2's own settings. A value that names no file, folder or executable is refused naming where it
   came from: exported, `local/game-settings.env` line N, or OpenRCT2's own settings. Exit codes are unchanged (a
   refusal exits 2).
6. **`make autopilot-real-test`.** Runs `tests/test_autopilot_real_game.py` with `OPENRCT2_AUTOPILOT_REAL_GAME=1`,
   outside `make check`. The test reads the settings file and the real OpenRCT2 `config.ini` before it swaps
   `OPENRCT2_USER_DIR` for a temporary folder (`settings_for_real_run` in `tests/conftest.py`), and the isolation
   fixture leaves the real sources alone only while that opt-in is set. The test still refuses cleanly when
   `OPENRCT2_BENCH_PARK` is found nowhere.
