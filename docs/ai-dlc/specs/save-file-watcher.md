# Spec: save-file watcher

status: draft 2026-10-19, rewritten after its first review (all findings accepted), then amended with two rulings
from its fix check (FC-1, unreadable record lines: R12, R13, A20; FC-2, the exit code of a first-scan failure: D1, R5,
R6, A6, Files table); written from the run's preflight rulings (Gate 1). Contract map:
`docs/ai-dlc/contracts/save-file-watcher.md`. Roadmap item: "Save-file watcher" in
`docs/ai-dlc/roadmap/park-company.md:361`.

## Bottom line

While `make capture-data` runs, a background thread checks three save folders once a second and writes one small
record for every `.park` file that is created or changed: its name without `.park`, which folder it is in, and when.
At the end, the capture report matches each save event from the game of this run to one such record of this run within
5 seconds. A save with no matching file, or a save with two possible files, makes the run exit 1 as a capture failure. The report also warns
when a `<park-name>-main` save changed while no capture was running. The records get their own contract and their
own folder, `data/<set>/save_files/v1/`; nothing in the warehouse reads them yet. No plugin change and no new
package are needed.

## Goal

The stated goal is "showing two parks on one company calendar running through the whole data stack". The project
owner duplicates saves to try ride designs, then saves the final build over `<park-name>-main`
(`park-company.md:361`). The plugin cannot see file names, because the save hook takes no arguments
(`docs/architecture/openrct2-facts.md:43`), and names cannot be recovered after play. So the capture must record which
file each save went to while play happens, or the later rules that follow a park's main save have nothing to read.
This slice records and checks; it builds no warehouse rule (`park-company.md:361`, "Stop").

## Owner rulings (binding, Gate 1)

The Gate 1 record (preflight rulings R5, R27 to R29) sets: "stdlib polling once a second, no new dependency; 5-second
match window; contract under contracts/reference/ (feed precedent); landing under data/<set>/ so data/company/
delete-all covers it; folders from OPENRCT2_USER_DIR or the platform default (never committed); the save, autosave and
parent folders watched; start-time -main modified times recorded and flagged when changed since the last paired
write; the report lists unpaired save_written events and two-candidate windows as capture failures; a clock seam for
tests. Out: the real-play save tests (split off, R29)."

## Decisions settled by this spec

Each decision states what it gains and what it costs. Points the sources leave open are under "Open points".

- **D1. A thread inside `run_session`, never in the listener.** The watcher runs as its own daemon thread, started
  after the listener thread starts (`capture_session.py:225-232`) and stopped in the same `finally` that cleans up
  (`capture_session.py:244-248`), after `_clean_up` returns. Stopping runs one final scan, because the quit save lands
  up to a second before the once-a-second game check sees the quit (`capture_session.py:143-160`). The thread shares
  no object or lock with the listener's `Lander` (`listener.py:100-103`) and writes to other files, so it cannot delay
  or drop an event. After the first scan, it catches and stores an `OSError` (every scan and write failure is one),
  stops watching, and the run then exits 1 (precedence in R6); a first-scan failure is raised instead (R5). Stopping
  a watcher that never started is a no-op (R6).
  Gain: event capture never waits on the disk scan, and the plugin is removed before the watcher's last scan.
  Cost: a third thread in the session, and a watcher that dies mid-run loses every later save record (reported, not
  hidden). A loop inside `_watch` was rejected: it would tie the scan to the game-check interval and put scan errors
  on the path that ends the session.
- **D2. The record carries no `park_id`; pairing ties it to a park.** The watcher sees only the file system. The park's
  identity lives in park storage inside the `.park` file (`openrct2-facts.md:30`), and reading the game's file format
  is out of scope (no new dependency, invariant 5). Each record is tied to a park through the `save_written` event it
  pairs with: that event's envelope carries `park_id` and `session_id` (invariant 1), and its payload `save_id`
  (`contracts/save_written.odcs.yaml:29`). Park identity is then checked in the report (R16). Gain: no parsing of
  game files. Cost: an unpaired record has no park, and a park-scoped delete cannot find it (D4).
- **D3. "Paired" is a strict one-to-one match on the plugin's clock.** A distinct file (folder kind plus name) is a
  candidate for a `save_written` event when one of its created or modified records has a modified time in `[emitted_at,
  emitted_at + 5 s]`. `emitted_at` is set when the event is built (`plugin/src/emit.ts:56`) inside the save hook
  (`plugin/src/main.ts:73`, subscribed at `:109`), and the file appears 0.001 to 0.136 s after the hook
  (`openrct2-facts.md:43`; `docs/FINDINGS.md:36,55`, where each hook matched exactly one file within 5 seconds).
  `received_at` is not used, because the plugin's queue can hold a line back. Gain: one rule, the one the findings
  measured. Cost: two saves within 5 seconds of each other fail (Open point 2). Pairing runs within one capture run only
  (R12). The first-received dedupe follows the staging model's existing tie rule (`received_at`, then `_raw_file`, then
  `_raw_line`, `models/staging/stg_save_written.sql`); three things are new in `save_pairing.py`: the window and
  pairing rule, the cut of rows to one capture run by `received_at`, and the first-received dedupe done within that cut
  run (staging dedupes over all rows, so an `event_id` delivered in two runs keeps the later run's row here and the
  earlier run's row there). The later warehouse item must match all three.
- **D4. Landing is `data/<set>/save_files/v1/`, append-only, read by no pipeline step tonight.** Convert, the event
  contract check and dbt never read it (R14). `make contracts` checks it against its contract (R10). Delete-all covers
  it because it removes every file under `data/company/` except the parquet lock (`delete_apply.py:66-76`). A named park
  or session delete touches only raw event files and registry rows (`delete_plan.py:186-199`), so it leaves these
  records (Open point 4). Gain: the records survive like raw captures and are removed with the rest of the company data.
  Cost: one more folder kind the delete command does not scope.
- **D5. A missing `save` folder refuses; a missing `autosave` folder is waited for.** `save` joins the folders
  `_check_folders` requires (`capture.py:86-92`), so the refusal changes nothing, as the others do. `autosave` may not
  exist until the game's first autosave, so the watcher checks for it on every scan. The parent folder is the user
  folder, which is already required. A folder that disappears mid-run prints one line and is watched for its return;
  a disappearance alone is not a failure (a save into it would surface as unpaired). Gain: the watcher can never run
  blind on the main save folder. Cost: a new refusal, and the capture test fixture (`tests/test_capture.py:178`) must
  create `save/`.
- **D6. The `-main` check uses pairing history, computed in the report.** At start the watcher writes a `start` record
  for each `*-main.park` file it finds (R5). The report, after convert, pairs each earlier run's records with that run's
  `save_written` events (R12, each run on its own) and compares each `start` record's modified time with that of the
  same file's last paired record from an earlier run. Gain: no mutable state file, nothing derived in an append-only
  folder, and the rule reads "paired write" literally. Cost: one DuckDB read of the data set's `save_written` Parquet
  per report; a run interrupted before convert never gets its own pairing verdict (R17). A later run's convert reads
  that run's events too, so a later report does pair the interrupted run's records with them and uses the result for the
  `-main` and park lines (R15, R16), but it never prints that run's pairing failure lines or pairing notes, and they
  never fail the later run (an unreadable line from an earlier run prints as a note and does not change the exit code)
  (Open point 3 gives the simpler alternative).

## Requirements

### Watching

- **R1. Folders.** The watcher derives three folders from the user folder that `pi.resolve_user_dir` returns
  (`plugin_install.py:126-130`, `OPENRCT2_USER_DIR` or the platform default): `save` (`<user>/save`, where
  `context.saveGame` writes, `openrct2-facts.md:42`), `autosave` (`<user>/save/autosave`) and `parent` (`<user>`, where
  the Save As dialog first opens, `openrct2-facts.md:45`). It scans each folder's own entries only, not deeper.
  No folder path is ever written to a record or to any committed file (invariant 5).
- **R2. What counts.** A regular file whose name ends in `.park`, directly in a watched folder. Symlinks and other
  entries are ignored. A file that disappears between listing and `stat` is skipped, with a comment saying why (an
  autosave rotation can remove it).
- **R3. Polling.** One scan per `Options.poll_seconds` (default 1.0 s, `capture_session.py:38`; the existing
  `--poll-seconds` flag, `capture.py:236-238`, also sets it), timed with `threading.Event.wait` so a stop is not held up
  by a sleep. stdlib only; no package is added to `pyproject.toml` or `uv.lock`.
- **R4. Change detection.** The first scan takes a baseline of every counted file's modified time (nanoseconds) and
  size. Each later scan writes a `created` record for a path absent from the previous scan and a `modified` record for
  a path whose modified time or size differs. Deletions and renames are not recorded (Open point 6).
- **R5. Start records.** The first scan writes a `start` record for every counted file whose base name ends in
  `-main`, in any of the three folders. `start()` runs the first scan synchronously on the calling
  thread, before it starts the polling thread, so the first scan completes, and its records are written, before the
  line "Open OpenRCT2 now and play" is printed (`capture_session.py:234-238`). A failure in the first scan stops the
  session before that line and exits 1, never 130. `start()` does not store that `OSError`; it lets it out, and
  `run_session` raises it as `WatcherStartFailed`, a new exception defined in `capture_session.py` next to `Refused`
  (`capture_session.py:46-47`; `Interrupted` is defined at `lock.py:37-38`), with the error in its message. The raise
  leaves `run_session`'s `try`, so the existing `finally` (`capture_session.py:244-248`) still cleans up and removes
  the plugin, and prints the removal line because the game did not quit; the watcher's stop is the R6 no-op, as its
  thread never started. `run()` catches `WatcherStartFailed` around the `run_session` call (`capture.py:197-199`),
  ahead of the did-not-quit check (`capture.py:200-202`, which returns 130 whenever the game did not quit), prints the
  error and returns `EXIT_PROBLEM` (1). `main()` (`capture.py:261-266`) is unchanged.
- **R6. Lifecycle and errors.** As D1. `run()` builds the watcher (it knows the data set, the user folder and
  `started`, `capture.py:184-191`); building it reads and writes nothing, so a refusal still changes nothing. `run()`
  passes it to `run_session`; `run_session` starts it after `serving.start()` and stops it after `_clean_up` in its
  `finally`. Stop on a watcher that never started (a `Refused` from `_remove_leftover` or `_install`, or an `Interrupted`,
  before `start()`) is a no-op: no join, no final scan, no record, like the serving-thread guard at
  `capture_session.py:187`. Otherwise stop sets the event; the thread runs one final scan, then ends; stop joins it with a
  5-second limit.
  The watcher catches and stores `OSError` only, with the time it happened; scanning stops; the listener keeps running.
  A later error (after the first scan) prints its error line when it happens, so the player can quit. A thread that
  ended before stop was asked, from any other exception, counts as a watcher error (stop checks `is_alive()` and a
  stopped flag). A join that times out counts as a watcher error and makes the report skip pairing (R17).
  **Exit precedence:** a refusal (2) wins, then an interrupt (130), then a stored watcher error (1); the watcher error
  is always printed, whichever code the run exits with. A first-scan failure (R5) keeps this order because it is
  raised, never stored, so it never meets the other two: every refusal inside `run_session` (`_remove_leftover`,
  `_install`) happens before `start()`, so a refusal and a first-scan failure cannot both occur; a signal during the
  first scan makes the handler raise `Interrupted` out of the scan, so the interrupt wins and the run exits 130; and
  once `WatcherStartFailed` is raised, cleanup ignores signals (`capture_session.py:245`), so no interrupt follows it.
- **R7. Missing folders.** As D5. The refusal reads "`<folder>` does not exist. Open OpenRCT2 once so it creates its
  folders, or set OPENRCT2_USER_DIR. Nothing was changed." through the existing `_check_folders` loop. A watched
  folder that vanishes prints "`<kind>` save folder is gone; watching for it to return." once, and "`<kind>` save
  folder is back." when it returns; its files then count as `created` only if absent from the last scan before it
  vanished, otherwise as `modified` when changed.

### Records and contract

- **R8. Record fields.** One JSON object per line, every field required:

  | Field | Type | Meaning |
  |---|---|---|
  | `run_started_at` | timestamp | The capture run's start, `started` from `capture.py:163-166`; groups one run's records |
  | `observation` | string | `start`, `created` or `modified` |
  | `file_name` | string | Base name without `.park`; never a path |
  | `folder_kind` | string | `save`, `autosave` or `parent` |
  | `modified_at` | timestamp | The file's modified time from `stat`, UTC, cut to milliseconds |
  | `size_bytes` | integer | The file's size from `stat`, in bytes |
  | `observed_at` | timestamp | The watcher's clock when the scan saw the change, UTC |

  Timestamps use `format_received_at` (`listener.py:54-55`), the `emitted_at` text format. `modified_at` is what
  pairing reads: a save copied in Finder keeps its old modified time and so is never a false candidate.
- **R9. Landing.** Records append to `data/<set>/save_files/v1/save_file_observation_<YYYY-MM-DD>.jsonl`, the date
  being the UTC date of `observed_at`, as the listener dates raw files (`listener.py:125`). Files are opened in append
  mode and never rewritten (invariant 2). The folder comes from a `save_files_dir(data_set)` function in the new
  `save_files.py`, derived as `landing_dirs(data_set).raw.parent / "save_files"`. It refuses a folder that equals,
  contains or lies inside any of: both data sets' raw and Parquet folders, both registry feeds and their `v1`, and the
  other data set's `save_files` and its `v1`, as `registry_dir` does (both call `refuse_aliases` in `registry_feed.py`). The check works one
  way: `registry_dir` and the delete command (`delete_data.py:70-71`) stay unchanged and do not compare against
  `save_files` (out of scope; the ADR says so). `run()`
  calls it next to `landing_dirs` (`capture.py:186`), so a bad folder refuses before any change. Nothing is added to
  `config.py`, which is at its 200-line golden-example cap (`docs/CONVENTIONS.md:209`).
- **R10. Contract and its check.** `contracts/reference/save_file_observation.odcs.yaml`, version `1.0.0`, describes
  R8, shaped like `contracts/reference/park_registry.odcs.yaml`. Quality rules: `observation` and `folder_kind` take
  only the values in R8; a `start` row's `file_name` ends in `-main` (dropped in version 1.2.0 by ADR 0048, which
  writes start records for every `.park` file); `size_bytes` is at least 0; `file_name` holds no
  `/` and is not empty (the watcher strips one `.park` suffix, so `Twice.park.park` is recorded as `Twice.park`, its base
  name, and macOS allows `\` in a name; neither is a path). Its description states it sits outside the event version line, the event
  envelope and the `seq` audit. `python -m openrct2_analytics.ingest.save_files` takes exactly one of `--data-set`,
  `--data-root` or `--file`, reads every column as text and casts only whole cells of the right shape (as
  `registry_feed.py:85-100`), runs the checks through `run_contract` (`registry_feed.py:103-120`) and exits 0 clean,
  1 failed, 2 refused (`registry_feed.py:147-172`). Unlike `check_feed` (`registry_feed.py:138-139`), an absent or
  empty folder passes with the line "No save-file records in `<folder>`.", because a data set captured headless, such
  as the sample, has none. The check fails on an unreadable line, naming the file (R12 counts them separately).
  The checker runs in `make check` on the committed sample, right after the registry feed check (`Makefile:74` is the
  precedent), and in `make contracts` after the registry feed check (`Makefile:134-138`).
- **R11. Reference contracts stay out of the event path.** The new contract is parsed by `load_reference_fields`
  (`contracts.py:158-172`), so its logical types stay within `REFERENCE_TYPES` (`contracts.py:49-50`). The dbt source
  generator reads only the `park_registry` schema (`generate_dbt_sources.py:102-105`), so generated sources do not
  change. The breaking-change check treats a new reference file as an addition in the reference scope
  (`check_contract_breaking.py:9-10,101-104`). The comment at `contracts.py:49` and the docstring at
  `contracts.py:159-162` say the reference folder holds feeds from outside processes; both are reworded to cover this
  in-repo record.

### Pairing and the report

- **R12. Pairing rule.** A pure function in `save_pairing.py` takes file records and `save_written` rows (`event_id`,
  `save_id`, `park_id`, `session_id`, `emitted_at`, `received_at`) and returns pairs, events with no candidate,
  two-candidate windows and unpaired records. Before pairing, the rows are cut to one capture run (row cut, same rule as
  the report: `received_at` at or after the run's `started`, and before the next run's start for an earlier run) and
  reduced to the first-received row per `event_id` (staging's rule, `docs/CONVENTIONS.md:108`, because the converter
  does not deduplicate, `convert.py:249`). Pairing runs within one capture run only: this run's rows against the
  records whose `run_started_at` equals this run's `started`; a record of one run never pairs with an event of another.
  Candidates of an event are the distinct files (`folder_kind`, `file_name`) with a `created` or `modified` record whose
  `modified_at` lies in `[emitted_at, emitted_at + 5 s]`; several records of one file in one window count as one
  candidate, its latest record standing for it. An event with exactly one candidate that is no other event's candidate is
  paired. An event with no candidate is "no candidate". An event with two or more candidates, or one whose single
  candidate is also another event's candidate, forms a two-candidate window; all events in it stay unpaired, and the
  categories "no candidate" and "two-candidate window" are disjoint. `start` records never pair. The 5-second window is
  a named constant. The report runs this function once for this run, and once for each earlier run that has records, over
  that run's records and its rows of `<parquet>/v1/save_written.parquet` (an absent file means no rows); R13 reads this
  run's result, and R15 and R16 read the earlier runs' results, each computed within its own run. The record reader
  treats a line it cannot read as JSON with the R8 fields as unreadable, and still reads and pairs the rest of that
  file. A torn line has no readable `run_started_at`, so an unreadable line is attributed by its file: one in a record
  file whose modified time is at or after this run's `started` belongs to this run; one in any other record file
  belongs to earlier runs. The reader returns each unreadable line's file name and line number with that attribution.
  A consequence of the rule: an earlier run's unreadable line in a file this run also appended to counts as this run's.
- **R13. Report lines.** `convert_and_report` (`capture_session.py:252-272`) gains the watcher's result. After the
  existing report (`capture_session.py:264-265`) and before its exit decisions (`:266-271`) it prints a "Save files"
  section from R12's result for this run: records whose `run_started_at` equals `started`, and `save_written` rows cut
  to this run (R12):
  1. one line per pair: file name, folder kind, `save_id` and `park_id`;
  2. one "capture failure" line per event with no candidate: `save_id`, `emitted_at`, and "no file record within
     5 s";
  3. one "capture failure" line per two-candidate window with an event of this run, naming its events and files; an
     event in a window gets this line and no line of item 2;
  4. one "note" line per `created` or `modified` record of this run that paired with nothing (not a failure;
     Open point 5);
  5. the `-main` lines of R15 and the park lines of R16;
  6. the watcher error, if any, with its time;
  7. one "capture failure" line per unreadable record line attributed to this run (R12), naming the record file and
     the line number, and one "note" line, also naming file and line number, per unreadable line in any other record
     file (they are skipped; R10 still fails on them).
  The run exits 1 when item 2, 3, 6 or a failure line of item 7 has a line, and otherwise keeps the existing exit decision;
  precedence with other exits is R6's. Every line prints before the function returns.
- **R14. No warehouse reads.** Convert, `make contracts`' event check (`contracts.py:269-271` reads only
  `contracts/*.odcs.yaml`), dbt and publish never read `save_files/`. No staging model or source is added.
- **R15. `-main` check.** For each `start` record of this run, the report finds, in the earlier runs' results (R12),
  the same file's latest paired record from an earlier run (`run_started_at` before `started`). There are three
  outcomes:
  1. no earlier paired record exists, and no unpaired record of the case below: the note "`<name>`: no earlier paired
     write on record";
  2. the paired record's `modified_at` differs from the `start` record's: the flag "`<name>` changed since its last
     paired write at `<time>`; that play was not captured";
  3. an unpaired `created` or `modified` record of the same file from an earlier run has the `start` record's
     `modified_at`: the line "`<name>`: last write was recorded but its save event was lost", printed instead of
     outcome 1 or 2.
  Every outcome is a warning line: the exit code does not change (Open point 7).
- **R16. Park identity.** Each pair line names the `park_id` (R13 item 1). A `-main`
  base name written in this run (a pair or an unpaired record of this run) whose pairs across the data set's history
  carry more than one `park_id` prints the flag "`<name>` was written by parks `<ids>`". A warning line, as R15.
- **R17. Every other way out.** On an interrupt, a stuck connection thread, zero events, a converter failure, or a
  watcher join that timed out (`capture.py:200-210`, `capture_session.py:255-263`), no pairing runs; the line "Save
  pairing skipped: <reason>. The save-file records were kept." prints, followed by the watcher error if any. The exit
  codes stay as today, with R6's precedence for a watcher error.

### Records to update

- **R18. Documents.** In the same change: `ARCHITECTURE.md` capture section (`:270-300`: the watcher, its folders, the
  new refusal, the report section, the exit rule) and its delete section (`:551` onward: delete-all covers the
  records; named scopes leave them); `docs/CONVENTIONS.md` module map rows for `ingest/` (`:65`, the three new modules)
  and `contracts/` (`:67`, the second reference contract and its checker), and its gate sequence (the new checker step
  after the registry feed check); `CLAUDE.md` command lines for `make contracts` and `make capture-data`, and its
  `make check` step list; the `--poll-seconds` help text (`capture.py:237`, "Between game checks"), which
  now also sets the watcher's interval; and a new ADR, `docs/adr/0037-save-file-records-outside-the-event-envelope.md`,
  recording D2, D3, D4 and the reference-folder choice. The ADR also records: `registry_dir` and the delete command do
  not compare against `save_files` (R9); interrupted runs never get a pairing verdict (R17); and `save_pairing.py`'s
  rule is the one the later "Main-save anchor in the warehouse" roadmap item (`park-company.md:372`) must match in dbt,
  so the rule is not implemented twice.

## Files and owning modules

| File | Change | Owner |
|---|---|---|
| `src/openrct2_analytics/ingest/save_watch.py` | New: folder set, scan, change detection, record writer, thread | `ingest/` (writes data files) |
| `src/openrct2_analytics/ingest/save_files.py` | New: `save_files_dir`, record and `save_written` reading, contract check command | `ingest/` |
| `src/openrct2_analytics/ingest/save_pairing.py` | New: pure pairing rule and report lines (no file or network I/O) | `ingest/` |
| `src/openrct2_analytics/ingest/capture.py` | `save` in `_check_folders`; build the watcher; pass it on; map `WatcherStartFailed` to exit 1 (R5); R17 lines | `ingest/` |
| `src/openrct2_analytics/ingest/capture_session.py` | `WatcherStartFailed` next to `Refused`; start and stop the watcher; the report section | `ingest/` |
| `src/openrct2_analytics/ingest/contracts.py` | Comment and docstring only (R11) | `ingest/` |
| `contracts/reference/save_file_observation.odcs.yaml` | New contract, 1.0.0 | `contracts/` |
| `Makefile` | `check` runs the new check after the registry feed check; `contracts` target runs it too | build |
| `tests/test_save_watch.py`, `tests/test_save_pairing.py`, `tests/test_save_files.py`, `tests/test_capture_saves.py` | New (`test_capture_saves.py` holds the end-to-end save cases) | `tests/` |
| `tests/test_capture.py`, `tests/test_capture_refusals.py`, `tests/test_delete_apply.py`, `tests/test_makefile.py` | Extended (`test_capture.py` only gains the fixture's `save/` line) | `tests/` |
| `ARCHITECTURE.md`, `docs/CONVENTIONS.md`, `CLAUDE.md`, `docs/adr/0037-…` | R18; updated in the same change | docs |

Pairing lives in `ingest/`, not `domain/`. Gain: `domain/` holds only the template placeholder
(`src/openrct2_analytics/domain/example_service.py:3`), and its first real module forces the golden-example row to be
repointed (`docs/CONVENTIONS.md:202-205`), which is not this slice's work. Cost: no import boundary proves the module
pure; review does. Every file stays at or under 500 lines (`docs/CONVENTIONS.md:99`); `capture_session.py` (272
lines) and `capture.py` (270) grow by about 30 lines each; `tests/test_capture.py` (451 lines) gains one line, and the
new end-to-end cases live in `tests/test_capture_saves.py` so it stays under the cap.

## Contracts and regeneration

The event contracts in `contracts/` do not change: `save_written` stays at 1.5.0 (`contracts/save_written.odcs.yaml:5`),
and the plugin is not rebuilt. The new reference contract starts at 1.0.0 outside the event version line; a later added field is a minor
bump and a breaking change a major bump with a new `v2/` folder (invariant 6). `scripts/generate_dbt_sources.py` is not
rerun for a change, and the dbt source drift step in `make check` must show no difference.

## Test seams

- **Clock.** The watcher takes `clock: Clock = utc_now`, the listener's seam (`listener.py:46`, `:100-102`), for
  `observed_at`. Tests set `modified_at` with `os.utime`, so pairing tests need no sleep.
- **One scan without a thread.** `scan()` is public and callable directly, so unit tests run create, change, vanish and
  return cases step by step; the thread only calls `scan()` on its interval.
- **Temp player folder.** Tests set `OPENRCT2_USER_DIR` to a temp folder holding `plugin/`, `save/` and, where
  needed, `save/autosave/` (the fixture at `tests/test_capture.py:175-181` gains `save/`; the same fixture serves `tests/test_capture_saves.py`). No real player folder is
  read.
- **A save without the game.** A test writes a few placeholder bytes (never game file content, invariant 5) to
  `save/<name>.park`, sets its modified time to `emitted_at + 0.1 s`, and sends a `save_written` line with that
  `emitted_at` through the socket helper (`tests/test_capture.py:139-141`), running the command as
  `command_argv` does (`:144-159`, `--poll-seconds 0.05`).
- **A failing watcher.** A test makes a scan raise (a watched folder replaced by an unreadable one, or a write into a
  read-only landing folder) and proves events still land and the run exits 1; a start-time variant proves the run
  stops before the "Open OpenRCT2 now" line, removes the plugin and exits 1, not 130 (A6).

## Golden paths

- `save_files.py` follows `registry_feed.py`: folder derivation and alias refusal (`:45-82`), text-then-cast view
  (`:85-100`), `run_contract` (`:103-120`), command line and exit codes (`:147-172`).
- `save_watch.py` follows `listener.py`'s `Lander` for the clock seam and dated append-only files (`:92-125`) and
  `capture_session._watch` for the polling loop (`:143-160`).
- `save_pairing.py` follows `capture_report.py`'s split of judgment from rendering (`judge_cost` `:111`, `render`
  `:319`).
- The contract follows `contracts/reference/park_registry.odcs.yaml`.
- Tests follow the golden test `tests/test_listener.py` (`docs/CONVENTIONS.md:211`), and `tests/test_registry_feed.py`
  and `tests/test_capture.py` for their kinds.

## Out of scope

- The warehouse rules that use the records: staging, save lineage by file, the main-save timeline
  (`park-company.md:361`, "Stop").
- The real-play save tests: a Save Game, a quit save, a Save Game As, an overwrite and an autosave close together
  (the roadmap item "Check: real-play save tests for the save-file watcher", `park-company.md:363`; split off by ruling
  R29). The real-play check of whether the hook fires for plain Save Game and the quit save belongs to Full capture part
  3b (`park-company.md:355`).
- Any plugin change (invariant 8 is untouched), and any change to `make delete-company-data`'s code or to `registry_dir`.
- The project owner's play instructions (`park-company.md:356`: "The instructions are updated when the save-file watcher
  and the clean start land") are updated at merge time, not by this slice's tickets.
- Recording deletions, renames, or saves in folders other than the three of R1.

## Constraints

- stdlib only (`os.scandir`, `os.stat`, `threading`, `json`); DuckDB, already a dependency, only in `save_files.py`.
- Polling once a second by default; 5-second window; both named constants.
- The eight invariants of `CLAUDE.md`. In particular: the record is outside the event envelope and the `seq` audit, so
  invariant 1 does not apply to it and the converter never sees it; invariant 2 (append-only, removed only by the
  pre-go-live company delete); invariant 5 (no private machine path, no game file content, in code, tests or docs);
  invariant 6 (R10 versioning); invariant 8 (no plugin change).
- No swallowed error (`docs/CONVENTIONS.md:87-88`): the two deliberate skips (R2, R7) catch only
  `FileNotFoundError` and say why in a comment; the watcher catches and stores `OSError` only (no blind `except`, no
  `noqa`), a thread that ended from any other exception is detected at stop (R6), and the stored error is printed and
  fails the run.
- Committed text never names the project owner.

## Verify-by

Offline (run by the build and stated in the PR):

1. `make check` exits 0.
2. `uv run pytest tests/test_save_watch.py tests/test_save_pairing.py tests/test_save_files.py
   tests/test_capture_saves.py tests/test_capture.py tests/test_capture_refusals.py tests/test_makefile.py
   tests/test_delete_apply.py -q` passes.
3. `uv run python -m openrct2_analytics.ingest.save_files --data-root data/sample/rehearsal` prints the "No save-file
   records" line and exits 0.
4. `git diff --name-only origin/develop...HEAD` lists only the files in "Files and owning modules" plus process
   records; `git diff origin/develop...HEAD -- pyproject.toml uv.lock plugin/` is empty.
5. `git diff origin/develop...HEAD -- . ':(exclude)docs/ai-dlc' | grep -nE '^\+.*(/Users/|/home/)'` prints nothing (process records are left out because this spec quotes the pattern itself).
6. `uv run python scripts/generate_dbt_sources.py --check` (the drift step of `make check`, `Makefile:75`) passes.
7. `CI=1 env -u VIRTUAL_ENV uv run python scripts/check_contract_breaking.py` exits 0 and prints its usual line,
   "no breaking change without a major bump"; it does not list the new file (scope verification only; see A12).

Deferred to real play (not run tonight; ruling R29, `park-company.md:363`): the five real-play saves each pair exactly
once; the clean start's first session ends with a paired save of `<park-name>-main` (`park-company.md:369`); the dress
rehearsal pairs every save (`park-company.md:367`).

## Acceptance

| # | Criterion | Tag | Req |
|---|---|---|---|
| A1 | `make check` exits 0 on the branch head | check: Verify-by 1 | all |
| A2 | A `.park` file created, then changed, in each of the three folders yields one `created` and one `modified` record with R8's fields; a non-`.park` file, a symlink and a file in a subfolder of `save` other than `autosave` yield none | check: `test_save_watch.py` | R1, R2, R4, R8 |
| A3 | `start` records are written for every `-main` file (every `.park` file since ADR 0048) before the "Open OpenRCT2 now" line | check: `test_save_watch.py`, `test_capture_saves.py` | R5 |
| A4 | Records append to the dated file of R9; an earlier day's file is never rewritten (its bytes are unchanged after a second run) | check: `test_save_watch.py` | R9 |
| A5 | Missing `save` refuses with exit 2 and changes nothing; a missing `autosave` is picked up when created; a vanished folder prints its two lines and is not a failure; a `Refused` from `_remove_leftover` still exits 2 and leaves `save_files/` absent, and stop on a watcher that never started is a no-op | check: `test_capture_refusals.py`, `test_save_watch.py` | R6, R7 |
| A6 | A scan error after start stops the watcher, events keep landing, and the run exits 1 with the error line printed when it happens; a first-scan failure stops the session before the "Open OpenRCT2 now" line, the plugin is removed, and the run exits 1, not 130, with the error printed (`WatcherStartFailed`, R5); a thread that ended from a non-`OSError` exception counts as a watcher error at stop | check: `test_capture_saves.py`, `test_save_watch.py` | R5, R6, R13 |
| A7 | Pairing: one candidate pairs; none is unpaired; two files in a window, or one file in two windows, is a two-candidate window; repeated records of one file are one candidate; `start` records never pair; the bounds `emitted_at` and `emitted_at + 5 s` are inside the window; a repeated delivery of one `save_written` (same `event_id`) is reduced to its first-received row and still pairs; an event with no candidate and an event in a two-candidate window land in disjoint categories; two adjacent runs where only the later run records a file within 5 s of an earlier run's unpaired event do not pair | check: `test_save_pairing.py` | R12 |
| A8 | An end-to-end capture with one save and its file exits 0 and prints the pair line with `park_id`; one save with no file exits 1 with a capture-failure line; one save with two candidate files exits 1 with the window line and no "no file record" line | check: `test_capture_saves.py` | R13 |
| A9 | The `-main` flag fires when the start time differs from the last paired write of an earlier run, is a note with no history, prints "last write was recorded but its save event was lost" when an earlier run's unpaired record has the start time, and leaves the exit code unchanged | check: `test_save_pairing.py`, `test_capture_saves.py` | R15 |
| A10 | Two parks pairing to one `-main` name print the park flag | check: `test_save_pairing.py` | R16 |
| A11 | The contract check passes the records the watcher itself writes in A2's test, fails each quality rule with a named line, and passes an absent folder | check: `test_save_files.py`, Verify-by 3 | R10 |
| A12 | Generated dbt sources and event contracts are unchanged. The breaking check is scope verification only (it skips a new file and runs only while `CI` is set); the new contract's lint and its negative quality tests (A11) are the acceptance evidence | check: Verify-by 6, Verify-by 7, `make check` | R11, R14 |
| A13 | The watcher shares no object or lock with the `Lander` and never runs on the listener's threads | judgment: reviewer reads `save_watch.py` and `run_session` | D1, R6 |
| A14 | A delete-all plan for `data/company/` includes a save-file record, whose path the test builds with `save_files_dir("company")` under the same `OPENRCT2_DATA_DIR` the delete reads | check: a case in `tests/test_delete_apply.py` | D4 |
| A15 | Documents updated as R18; no owner name or private path | judgment: reviewer reads each against R18; check: `make check`'s docs step and Verify-by 5 | R18 |
| A16 | `make check` runs the save-file checker on the committed sample right after the registry feed check, and `make contracts` runs it after the registry feed check | check: `tests/test_makefile.py` asserts both step positions | R10 |
| A17 | A `save_files` folder that is a symlink to the raw folder (or aliases another folder of R9's list) refuses with exit 2 and changes nothing | check: `test_save_files.py`, `test_capture_refusals.py` | R9 |
| A18 | An interrupted run prints the "Save pairing skipped" line and the watcher error if any | check: `test_capture_saves.py` | R17 |
| A19 | Exit precedence: an interrupt after a stored watcher error exits 130 and prints the error; a refusal wins over both | check: `test_capture_saves.py`, `test_capture_refusals.py` | R6 |
| A20 | An unreadable record line (a torn line, and a JSON line missing an R8 field) in a record file whose modified time is at or after this run's `started` prints a capture-failure line naming the file and line number, and the run exits 1; one in an older record file prints a note naming file and line number and leaves the exit code unchanged; the rest of each file is still read and pairs; the contract check fails naming the file; a join timeout skips pairing | check: `test_save_pairing.py`, `test_save_files.py`, `test_save_watch.py` | R10, R12, R13 |

## Definition of Done

The slice is done when A1 to A20 hold on the branch head, Verify-by steps 1 to 7 have run with their results stated in
the PR, and the PR is merged into `develop` after its reviewer passes. The deferred real-play steps stay on the
roadmap line until the project owner plays them; the roadmap item is not ticked by this slice.

## Open points

Recommended defaults are what the build does unless the project owner rules otherwise.

1. **The contract map is stale in four places.** Its overlap warning (map line 9) is already resolved: commit
   `0c14105`, "Add a two-park rehearsal capture command (#92)", is this branch's base. `run_session` starts at
   `capture_session.py:220` and the listener thread starts at `:232`, not `:233`; the scope rule is at
   `check_contract_breaking.py:101-104`; the named-scope globs are at `delete_plan.py:190-191,196-199`. Default: this
   spec's citations stand.
2. **Settled at Gate 1 (two-candidate windows fail); recorded question for real play. Strict pairing against the real-play test.** Gate 1 says every window holding two candidates is a capture failure;
   the roadmap's real-play test expects "an overwrite and an autosave close together each pair exactly once"
   (`park-company.md:363`). If the two land within 5 seconds, R12 fails them. Default: keep R12 strict tonight. The
   alternative, pairing the k-th event with the k-th file in time order when a cluster holds as many files as events,
   gains a pass for close saves and costs a guess about write order that only the real-play test can confirm.
3. **"Last paired write" or "last recorded write".** R15 reads the roadmap literally and needs pairing history (D6).
   The simpler rule, comparing with the file's latest record of any kind, gains independence from the Parquet and
   costs a silent pass when a `-main` write during capture never paired (already reported as a failure in that run).
   Default: literal.
4. **Settled at Gate 1 (delete-all is the only covered delete); recorded question for real play. Named-scope delete leaves save-file records.** `delete_plan.py:186-199` reads only raw event files and registry
   rows, and records carry no `park_id` (D2). Default: leave them and say so in `ARCHITECTURE.md` and the ADR; they
   hold file names and times only. The alternative, a plan note listing them, costs a `delete_plan.py` change and test.
5. **Settled at Gate 1 (a record with no event is a note); recorded question for real play. Records with no event.** A Finder copy, or a save type whose hook does not fire, makes a record that pairs with
   nothing. Default: a note line, not a failure, because the roadmap lists only unpaired events and two-candidate
   windows as failures. If Full capture part 3b finds plain Save Game or the quit save fires no hook
   (`park-company.md:355`), this should become a failure.
6. **Not recorded:** deletions, renames, subfolders of `save` other than `autosave`, and Save As into any other
   folder (that save surfaces as unpaired). No slack before `emitted_at`: a file stamped before its hook cannot be
   that hook's save (`openrct2-facts.md:43`).
7. **Settled at Gate 1 (flags are warnings); recorded question for real play. Warning or failure for the `-main` and park flags.** Default: warnings (R15, R16), because they describe play
   outside this run or a play mistake, not lost capture. Making them exit 1 gains a harder stop before data is
   trusted and costs a red run for something the capture itself did right.
8. **`save` refusal is a new refusal.** It extends the list at `ARCHITECTURE.md:292-302` and the fixture at
   `tests/test_capture.py:178`. Default: accept (D5).
