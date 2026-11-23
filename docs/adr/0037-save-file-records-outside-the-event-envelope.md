# ADR 0037: save-file records sit outside the event envelope

- Date: 2026-10-19.
- Status: Accepted 2026-10-19 (save-file watcher slice); what counts as a shared candidate file is amended by ADR 0053 (`docs/adr/0053-one-file-saved-again-is-not-a-shared-candidate.md`), so one file saved again outside an earlier save's window pairs each save.

## Bottom line

While `make capture-data` runs, a watcher thread writes one small record for every `.park` file that is created or
changed, and the capture report pairs each `save_written` event of the run with one such record. The records have their
own contract under `contracts/reference/` and their own folder, `data/<set>/save_files/v1/`. No pipeline step reads
them. The plugin cannot see file names (its save hook takes no arguments), so this is the only place a save's file name
is recorded.

## Context

The project owner duplicates saves to try ride designs and saves the final build over `<park-name>-main`. Later rules
that follow a park's main save need to know which file each save went to, and a name cannot be recovered after play.
The spec is `docs/ai-dlc/specs/save-file-watcher.md`.

## Decision

1. **The record carries no `park_id`; pairing ties it to a park.** The watcher sees only the file system, and reading a
   `.park` file's format is out of scope. A record is tied to a park through the `save_written` event it pairs with,
   whose envelope carries `park_id` and `session_id`. An unpaired record has no park.
2. **"Paired" is a strict one-to-one match on the plugin's clock.** Rows are first cut to the run by `received_at`, then
   reduced to the first-received row per `event_id`, breaking ties on `received_at` by `_raw_file`, then `_raw_line`,
   as `models/staging/stg_save_written.sql` already does. Only `created` and `modified` records count; `start` records never
   pair. A candidate for an event is a distinct file (folder kind plus name) with at least one such record whose
   modified time lies in `[emitted_at, emitted_at + 5 s]`, and its latest record in that window stands for it. The
   window uses the plugin's `emitted_at`, not `received_at`, because the plugin's queue can hold a line back. An event
   pairs only when it has exactly one candidate file and that file is a candidate of no other event; all of that file's
   in-window records then count as paired. Otherwise (several candidate files, or a candidate file another event shares)
   the event fails; failing events that are linked through shared files form one two-candidate window failure that names
   all their events and files. An event with no candidate fails on its own. Any other write record is unpaired. Pairing
   runs within one capture run only. Three things are new, and they live in
   `src/openrct2_analytics/ingest/save_pairing.py`: the window and pairing rule, the cut of rows to one capture run by
   `received_at` (from that run's start up to, not including, the next run's start), and the first-received dedupe done
   within that cut run only (staging dedupes over all rows at once, so an `event_id` delivered in two runs keeps the
   later run's row here and the earlier run's row in staging). Only the tie order (`received_at`, then `_raw_file`,
   then `_raw_line`) follows the staging model. The later roadmap item "Main-save anchor in the warehouse"
   (`docs/ai-dlc/roadmap/park-company.md`) must match all three in dbt, so it is not implemented twice.
3. **Landing is `data/<set>/save_files/v1/`, append-only, read by no pipeline step.** Convert, the event contract check
   and dbt never read it; `make contracts` and `make check` check the records against their own contract. `make
   delete-company-data` with no scope removes them with the rest of the company data, because it removes every file
   under `data/company/` except the parquet lock (derived Parquet goes as rebuildable output); a named park or session
   delete leaves them, because they carry no `park_id` and that delete reads only raw event files and registry rows.
4. **The contract lives in `contracts/reference/`, not beside the event contracts.** It is
   `contracts/reference/save_file_observation.odcs.yaml`, version 1.0.0, outside the event version line, the
   envelope and the `seq` audit. `contracts/reference/` was made for the registry feed, which also is not an event
   type. The converter and the dbt source generator ignore that folder; the breaking-change check covers it, treating a
   new file as an addition and requiring a major bump of that file's own version for a later breaking change.

Gain: no parsing of game files, no change to the plugin or the event contracts, and the records survive like raw
captures. Cost: an unpaired record has no park; a named-scope delete leaves the records (they hold file names and times
only); two saves within 5 seconds of each other fail the run until real play shows how close saves behave; and the
repo now holds a second reference contract.

## Details the code fixes

- **Alias refusal.** `save_files_dir` and `registry_dir` share one alias-refusal helper in `registry_feed.py`. `save_files_dir`
  also refuses a save-file folder (or its `v1`) that resolves outside its own data set's folder, so a link cannot send the
  records elsewhere; a relocated data folder stays allowed. The alias check works one way: `registry_dir` and `make delete-company-data` do not compare against `save_files`, so their
  behavior is unchanged.
- **An interrupted run gets no pairing verdict of its own.** On an interrupt, a stuck connection thread, zero events, a
  converter failure or a watcher join that timed out, the run prints "Save pairing skipped" and keeps the records
  (`capture_session.py`, `capture.py`). A later run's convert reads the earlier run's events too, so the later report
  pairs the earlier records with them and uses the result for its `-main` and park lines, but it never prints that
  run's pairing failure lines or pairing notes, and they never fail the later run. An unreadable record line from an
  earlier run does print, as a note, and does not change the exit code.
- **A re-delivery landing in the next run.** A repeated `save_written` delivery that lands in a later run is a fresh row
  there, because the row cut by `received_at` runs before the first-received dedupe. That run reports "no file record
  within 5 s" for it, because the record belongs to the earlier run.
- **File names.** The contract's `file_name` rule is "no `/` and not empty". The watcher strips one `.park` suffix, so a
  name holding `\` or a second `.park` is legal.

## Rejected options

- **Read the park from the `.park` file.** Gain: records would carry a park. Cost: a parser for the game's file format
  and a dependency or a copy of its layout.
- **Put the records in the event stream.** Gain: one path. Cost: they would need an envelope, a `seq` and a plugin
  change, though the plugin cannot see file names.
- **A state file for the `-main` check.** Gain: simple lookup. Cost: a mutable file beside append-only data; the report
  derives the history from pairing instead.

## Consequences

- `ARCHITECTURE.md` ("Capture command", "Deleting company data and going live"), `docs/CONVENTIONS.md` (module map and
  gate order) and `CLAUDE.md` describe the watcher, the new folder and the added check.
- A change to the pairing rule must be mirrored in the main-save anchor model when it is built.
- ADR 0036 is the previous record.
