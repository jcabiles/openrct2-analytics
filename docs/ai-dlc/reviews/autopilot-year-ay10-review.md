verdict: FAIL

# AY-10 review: run and land one autopilot year (b650b6b against ae29e56)

The run order is sound, but two test gaps and one broken hand-run test stop a pass.
- The order is right: refusals, then the run, the registry re-check, the landing (label, then records, then raw), the convert and backup, and the report.
- Exit texts match spec section 4. Signals are ignored from the first link onwards and restored on every exit.
- Problem 1: an assertion was loosened. The "later run with an empty READY prints no ignored line" case lost its protection.
- Problem 2: the worker's new "success needs an archive copy" rule has no test.
- Problem 3: the hand-run real-game test cannot pass as written. Its planted second-park day has no save, so step 2 is refused by refusal 17a.

Deterministic checks run:
- The baseline suite ran against a scratch copy of `src/`: 98 passed, 1 skipped.
- `check_test_weakening.py` exit 1: it flags the skipif and the assertion count drop, both judged below.
- Three planted breaks were each run against the 4 stand-in test files: all three stayed green (98 passed each).
- The repo stayed clean at b650b6b. The scratch folder was removed.

## Answers

### 1. Test weakening (tests/test_autopilot_year_refusals.py)
The four removed assertions:
- The placeholder test `(1, [NOT_BUILT])` became `tests/test_autopilot_year_refusals.py:391-392`: `reached_the_run` plus `len(world.runs) == 1`. This is stronger, because it proves the run is reached exactly once and that nothing is written (`World.run` compares folder listings).
- `test_a_kept_older_work_folder_does_not_block` moved to `tests/test_autopilot_year_refusals_data.py:251-256`. It has the same strength.
- `test_a_relative_backup_dir_...` moved to `tests/test_autopilot_year_refusals_data.py:259-269`. It has the same strength.
- `test_a_relative_data_dir_...` moved to `tests/test_autopilot_year_refusals_data.py:272-281`. It has the same strength for the refusals. It does not cover the new run and landing phase (see AY10R-4).

Two assertions in the data file were also loosened in place. The script cannot see these:
- `tests/test_autopilot_year_refusals_data.py:155-161` (later run with a wrong READY). The "READY was ignored" check now lives in `tests/test_autopilot_year.py:326-333`, a full run with `lines.count(IGNORED) == 1`. That is stronger. Covered.
- `tests/test_autopilot_year_refusals_data.py:164-169` (later run with an empty READY, "without an ignored line"). Protection was lost. The old assertion `(1, [NOT_BUILT])` was exact. The old code printed the ignored line before the placeholder when `ready_ignored` was truthy, so an empty-string leak would have failed it. The new assertion stops at the recorder, before the report, so it cannot see the line. No full-run test uses an empty READY.
  - Plant result: `if cleared.ready_ignored:` was changed to `if cleared.ready_ignored is not None:` at `autopilot_year.py:295`. The 4 test files gave 98 passed. The plant was not caught (AY10R-1).
  - This case is realistic: a Makefile target that always passes `--ready "$(READY)"` sends an empty string.

### 2. The skipif on tests/test_autopilot_real_game.py
The skip is gated only on the environment variable:
- The marker is at `tests/test_autopilot_real_game.py:43-46`: `os.environ.get("OPENRCT2_AUTOPILOT_REAL_GAME") != "1"`.
- The file has no `importorskip`, no other `skip` or `xfail`, and no conditional return. Missing settings make `load_settings` fail rather than skip.
- R13 requires this skip, so the flag is justified.
- WEAKENED-OK approved: tests/test_autopilot_real_game.py

### 3. The rule that success needs an archive copy (`autopilot_year.py:327-338`)
- **Reading:** this is a faithful reading of R4, not a change to an agreed requirement.
  - R4 says the run copies the end-of-year save to the archive.
  - Section 4 gives exit 1 for "a ... backup problem".
  - A skipped backup leaves the next run refused (refusals 14 to 16 need a proven archive copy).
  - So exit 0 with no archive copy would break R4 and the "next run" promise. No project-owner decision is needed.
- **Recovery text:** it matches section 4 word for word (`autopilot_year.py:333-337` against spec section 4, the backup bullet).
- **Two extensions beyond the spec, both harmless:**
  - The recovery text is also printed after a failed convert. That recovery (load the save under make play) fixes that case too.
  - A dated-copy-only failure (archive copy made) exits 1 without the recovery text. The text says "refused until then", which would be false there, so leaving it out is correct. It is still a literal deviation from "A backup failure adds the recovery steps" (AY10R-6).
- **The rule is untested.**
  - Plant: `if code == 0 and archived:` changed to `if code == 0:`. The 4 test files gave 98 passed. Not caught.
  - The only backup test (`tests/test_autopilot_year_failures.py:256`) makes `convert_and_report` return 1, so it never reaches the new branch (AY10R-2).

### 4. Guesses in the real-game test, checked against the repo
- **Schema `intermediate.int_sessions__lineage`: right.**
  - `dbt_project.yml:15-16` sets `+schema: intermediate`.
  - `macros` `generate_schema_name` uses the custom schema with no target prefix.
  - The columns `parent_session_id` and `is_on_kept_path` exist (`models/intermediate/int_sessions__lineage.yml:42,60`).
- **The `--vars` keys `parquet_root` and `registry_root`: right, at the right folder level.**
  - `models/staging/_sources.yml:11` reads `{parquet_root}/v1/<t>.parquet`.
  - `models/staging/_sources.yml:1223-1229` reads `{registry_root}/v1/park_registry_*.csv`.
  - The test passes `company/parquet` and `company/registry`.
  - The `dbt()` helper requires `parquet=False, registry=False` when the caller passes its own `--vars` (`tests/test_dbt_environments.py:40-55`). The test does this.
  - `ci.duckdb` under `OPENRCT2_CI_DIR` is right (`profiles.yml:15-17`).
- **Step-1 shortcut: right as far as it goes.**
  - `run_autopilot` takes `options=None` and `planned_days` (`autopilot_run.py:181-193`).
  - `reached_stop` does not depend on problems (`autopilot_run.py:262`), so `park_id="unchecked"` and blank lineage keys only add problems, which the test ignores.
- **Park-b start 2001 means game year 9 is company year 2009: the arithmetic is right.**
  - `company_year = start + (g - origin)` (`company_years.py:52-54`).
  - Park-a's T = 2000 + (10 - 1) = 2009.
- **The planted park-b day: WRONG.**
  - `plant_second_park_day` (`tests/test_autopilot_real_game.py:66-77`) copies only a `park_snapshot` row and a `session_start` row for `sess-b`, with no `save_written`.
  - "A session with no save has no managed day" (`company_years.py:68-70`). `managed_years.py:104-110` builds `last_save_seq` from `save_written`.
  - Proof: calling `managed_years_by_park` with that day and no save gives `{}`. The verdict for park-a in 2009 is `17a`. With a save at seq 41 it gives `{'park-b': {2009}}`.
  - So `main(...)` at line 142 returns 2 (refusal 17a), not 0 (AY10R-3).
- **Plugin built in `REPO_ROOT`: right.** `main`'s default build is `partial(pi.build_plugin, project)` with `project_dir=REPO_ROOT`. It writes the plugin build output in the checkout, as the spec allows for capture commands.

## Lens notes (no finding unless listed)
- (a) Safety and order:
  - The run, `reached_stop`, problems, the registry re-check (`autopilot_year.py:365-370`), then `land`.
  - The guard re-checks the write boundary under the lock.
  - Label, then records, then raw: asserted at `tests/test_autopilot_year.py:215-218`.
  - `SIG_IGN` is set inside `write_label` after the checker and before the first link (`autopilot_land.py:225-231`).
  - Nothing after landing re-arms signals. `convert()` sets `raise_interrupted` only in its own `main` (`convert.py:459`), and `convert_and_report` and `save_backup` set no handlers.
  - `main`'s `finally` restores the saved handlers (`autopilot_year.py:443-445`).
  - The work folder is removed only in `_report` (success).
- (b) The texts match section 4. The failed-checks text is printed one problem per indented line, a shape the spec leaves open.
- (c) Every case listed in section 8 and the ticket exists, except an empty-READY full run and a skipped-backup run (AY10R-1 and AY10R-2).

## Findings
AY10R-1 · blocker · tests/test_autopilot_year_refusals_data.py:164-169 · An assertion was loosened in place: "a later run with an empty READY passes without an ignored line" no longer checks for the ignored line (the recorder stops before the report), and no full-run test covers an empty READY, so a leak of "READY was ignored" on every later run would ship. · Plant `autopilot_year.py:295` `if cleared.ready_ignored is not None:` gave 98 passed on the 4 stand-in files (the old exact assertion `(1, [NOT_BUILT])` would have failed). · Add a `Full` case in `tests/test_autopilot_year.py`: `earlier_autopilot_run(full)`, `full.args["--ready"] = ""`, assert code 0 and `IGNORED not in lines`. Either drop the "without an ignored line" claim from the data test's name or keep it only where it is asserted.

AY10R-2 · major · src/openrct2_analytics/ingest/autopilot_year.py:327-338 · The new rule "exit 1 when the archive does not hold the end-of-year save, even though convert_and_report returned 0" has no test, so reverting it to exit 0 (no archive copy, next run refused) stays green. · Plant `if code == 0 and archived:` changed to `if code == 0:` gave 98 passed. · Add a failures case where the backup is skipped, not failed. For example, make the archive copy step skip by an unpaired later write of the end-of-year save in the run's watched folder, or monkeypatch `back_up` to print its skip line and return True. Assert exit 1, the skip line, the exact recovery text and a kept work folder.

AY10R-3 · major · tests/test_autopilot_real_game.py:66-77,140-142 · The hand-run test cannot pass. The planted `sess-b` day has no `save_written`, so it is not a managed day (`company_years.py:68-70`), and `main` refuses with 17a (exit 2) at line 142. The section 12 step 3 hand check would fail on the test, not on the code. · `managed_years_by_park([SnapshotDay('park-b','sess-b',40,9,1,5)], {...}, {}, {'sess-b':9})` gave `{}` and verdict `17a`. With `{'sess-b':41}` it gave `{'park-b': frozenset({2009})}`. · Also plant one `save_written` row for `sess-b` (copied from step 1's, `park_id`/`session_id`/`event_id` replaced, `seq` at or above the planted snapshot's), then re-read the test once more before the first hand run.

AY10R-4 · minor · src/openrct2_analytics/ingest/autopilot_year.py:365 · The `with chdir(project)` around the re-check, landing and convert has no test: every full-run test sets an absolute `OPENRCT2_DATA_DIR`. A relative `OPENRCT2_DATA_DIR` with a working folder other than the project would land into the wrong folder. Real use runs from the repo root, so the impact is low. · Plant: replace the `with chdir(project):` by `if True:` gave 98 passed. · Add one `Full` run with `monkeypatch.chdir(elsewhere)` and a relative `OPENRCT2_DATA_DIR`, as the refusal test does.

AY10R-5 · minor · src/openrct2_analytics/ingest/autopilot_year.py:290-299 · `_report` finds the dated copy with its own glob plus `filecmp`, next to `save_backup.newest_own_copy` (`save_backup.py:125-140`), which does a similar search; it is a possible second home for "which dated copy to load". It also prints "No dated copy was found." inside a success report, which the spec's success report does not foresee. · Read only. · Either reuse `newest_own_copy`, or keep the bytes comparison and note why (the park's label is not known here). Treat a missing dated copy as a backup problem or document the line.

AY10R-6 · minor · src/openrct2_analytics/ingest/autopilot_year.py:332 · A failure of the dated copy alone (archive copy made) exits 1 without the recovery steps. Spec section 4 says "A backup failure adds the recovery steps". Leaving them out is the better wording, because their "refused until then" sentence would be false, but it departs from the spec text. · Read only. · Record the reading in the spec or ledger.

AY10R-7 · nit · src/openrct2_analytics/ingest/autopilot_year.py:374-375 · An interrupt between the refusals and the creation of the work folder prints "the run folder is kept at <path>" for a folder that does not exist. The recorder tests assert exactly this. · Read only. · Optional: say "kept" only when the folder exists.

AY10R-8 · nit · src/openrct2_analytics/ingest/autopilot_year.py:365-371 · The registry re-check runs before the landing lock wait (up to 120 s). A registration as practice during the wait is not caught by `guard`, which re-checks only the write boundary. The spec's "before the first link" is met only loosely. · Read only. · Optional: move the registration check into `guard`.

risky: yes
brief-defect: the AY-10 brief did not ask for a full-run case for each READY branch the placeholder tests used to pin (first, wrong, empty, absent), so the empty-READY protection was dropped when the placeholder went.
brief-defect: the brief listed the real-game test's step 2 ("plants one managed day of a second park") without saying that a managed day needs the session's save_written (company_years.py:68-70).
