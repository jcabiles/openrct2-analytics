# ADR 0049: a finished park runs one game year headless, and every session carries a play-mode label

- Date: 2026-11-13.
- Status: Proposed with the autopilot-year spec (`docs/ai-dlc/specs/autopilot-year.md`); it takes effect when the
  branch that builds it merges. Section "Departure from the staging rule" amends the staging rule in
  `docs/CONVENTIONS.md`.

## Bottom line

`make autopilot-year DATA_SET=company PARK=<id>` takes a finished company park's last recorded save from the backup
archive, plays it in the game with no window and the plugin until 1 March of the next game year, checks the capture in
its own work folder, and only then lands it in the company data, labeled `autopilot`. Every row of
`staging.stg_session_start` gains `play_mode`, `managed` or `autopilot`; a session with no label row is `managed`. The
plugin and the fourteen event contracts do not change. One case lets a wrong run through (decision 8) and is guarded
only by this text.

## Context

Park 1 is finished and Park 2 is played by hand. The company should still show two parks in one month. Without a label,
an autopilot session would look like play by the player, and lever analysis would count it as such.

## Decision

1. **The source save is the newest archive copy, proven to be the last recorded save.** The command lists the park's
   archive folder and takes the `.park` file with the latest time at the end of its name (not a full-name sort, because
   the name starts with the park's name, which the player can change). The park's latest `save_written` event, over
   all company runs, must pair with exactly one save-file record; the copy's size must equal that record's
   `size_bytes` and its modified time must not be earlier than the record's `modified_at`. No copy, no unique pair or a
   failed proof is a refusal. Gain: an archive copy is never changed, and a stale copy cannot silently cut off play
   recorded after it. Cost: size and time are a cheap match, not a byte proof, and a run whose backup was skipped
   blocks autopilot until one healthy `make play` run makes a new backup.
2. **Stage, check, then append.** The game runs with its user-data folder inside a new work folder. Only a capture that
   passes the `seq` audit, the contracts and the save-file record check there is appended to `data/company/`,
   under the company landing lock, which also re-checks the registry and the staged label. A landing lock held after
   the run exits 1 (the `parquet.lock` refusal at start-up stays exit 2). Gain: a failed run never reaches the append-only
   raw data (invariant 2). Cost: a new landing function, because the rehearsal landing refuses a non-empty data set.
3. **The label is a delivery file beside the park registry.** Files
   `data/<set>/registry/v1/session_play_mode_<YYYY-MM-DD>_<NN>.csv` are read by dbt through the existing registry
   folder variable, and the publish and delete paths already visit that folder. The reference contract is
   `contracts/reference/session_play_mode.odcs.yaml` (version 1.0.0, outside the event version line), checked by
   `python -m openrct2_analytics.ingest.play_mode_feed`, which `make check` (on the sample), `make contracts`,
   `make transform` and the publish contract step run. Gain: no plugin change, no event-contract bump and no `make
   bench`. Cost: a new contract, checker, staging model and wiring.
4. **The ready mark lives in the same delivery row as the label.** A park's first autopilot run needs
   `READY="<park id> is profitable and its scenario challenge is complete"`; the phrase is written into
   `ready_confirmation`. "First run" means the park has no `autopilot` label row whose session is in the converted
   `session_start.parquet`, so an orphan label row never makes the next run look like a later one. On a later run a
   given `READY` is ignored and the report says so. Gain: one feed and one contract, and the mark is recorded with the
   run. Cost: the mark exists only once a run lands; a first run that fails must be confirmed again.
5. **One session per label row.** The checker refuses a `session_id` that appears twice across all deliveries. Gain:
   staging needs no repeat-delivery filter. Cost: a wrong label is fixed only by the pre-go-live rewrite of
   `make delete-company-data` (ADR 0033).
6. **Landing order: label, then save-file records, then one raw file.** The work folder's raw files are joined into one
   raw file per session, so a raw session never lands in part. A crash leaves at most a label row, or a label row and
   record files, that name no landed session; it never leaves an unlabeled or partial autopilot session. Gain: the
   dangerous direction (an autopilot session counted as managed) cannot happen. Cost: an orphan label row stays in the
   feed until `make delete-company-data SESSION=<id>` removes it.
7. **The stop year is rendered into the helper plugin text.** With a target year, the helper arms on the day callback
   of 1 March of that year and saves 200 ticks later; the command passes the source save's game year plus one. In
   every mode the helper pauses the game right after its save, so no later day is played. Without a target year the
   rehearsal chain's rule is unchanged. Gain: a source saved on 31 October stops after one night, and nothing reads the
   year at run time. Cost: one more placeholder in the helper text.
8. **Abandoned play before `make transform` is counted, both ways.** The year rule reads converted Parquet, so it
   cannot tell kept days from abandoned ones (ADR 0024). Abandoned managed days can refuse a run: a try-out branch
   that played into a later year raises that park's latest managed year. They can also allow a wrong run: Park 2 tries
   a branch into year Y + 2, abandons it and reloads its Y + 1 save; Park 1 may then run year Y + 2 although Park 2's
   kept timeline is still in Y + 1. The command cannot see this case. Whoever plays Park 2 checks, before running
   Park 1, that Park 2's kept timeline reached the year; otherwise the run's session is removed
   with `make delete-company-data SESSION=<id>`. That delete keeps the archive copy and the dated copy: do not load that
   dated copy; the park's next autopilot run is refused until a `make play` from its save before the wrong run makes a
   new backup; a first run with later runs needs `PARK=<id>`. Gain: no kept-timeline read, so the rule works before `make transform`. Cost:
   the allowed-wrong-run case is guarded only by this text.
11. **The label column is added in staging.** `stg_session_start` left-joins the new `stg_session_play_mode` on
    `session_id` and fills `managed` when no row matches, as the roadmap names. Gain: the roadmap's pass/fail line holds
    as written. Cost: the departure below.

Decisions 9, 10, 12 and 13 of the spec (the game-folder copy never replaces a file, the dated name keeps the
wall-clock date, the real-game test is switched by an environment variable, and the work folder is kept after a
failure) are in the spec only.

## Departure from the staging rule

`docs/CONVENTIONS.md` section 4 says staging has no joins; joins belong to intermediate. `stg_session_start` joins
`stg_session_play_mode`, a staging model, for `play_mode`. It is the only staging model that does. A data set with no
label file still builds, because `stg_session_play_mode` names its source only when DuckDB's `glob()` finds a file and
otherwise selects zero typed rows.

## As built: exit codes and the backup

- Exit codes are 0 landed, 1 a run, check, landing or backup problem, 2 refused (nothing written) and 130
  interrupted; through `make`, any failure is make's own non-zero code.
- Success needs the archive to hold a copy of the end-of-year save. Without it the command exits 1 with the steps to
  make the backup (copy the save from the run folder into the game's save folder, load it with `make play`, save while
  paused, quit); the next autopilot run of that park is refused until then. A failure of the dated game-folder copy
  alone, with the archive copy made, exits 1 without those steps, because the next run is not refused.
- The work folder is removed after a fully successful run and kept after any failure.

## R18: why the 2026-11-12 company run wrote no dated backup

No code defect is visible. Every path that skips the backup prints its own line and matches the safe-play spec
(`docs/ai-dlc/specs/safe-play.md`, Part 2). Likely causes, from the code alone: one ambiguous save anywhere in the run
fails the whole run's pairing and skips every park's backup ("No backup made: this run had a capture problem"); or a
write after the last paired save (for example the save offered on quit, if its `save_written` event did not land)
skips that park ("newer unrecorded play may exist"). The 2026-11-12 report's "Save files" and "Backup" lines settle
which one happened; the question is an open row for the project owner. Until one healthy `make play` run of Park 1
ends with a "Backup:" line, `make autopilot-year` refuses Park 1.

## Consequences

- Park 1 keeps producing company months while Park 2 is played by hand.
- After a run, the park's older saves are one game year behind: loading one under `make play` starts a newer session on
  the older branch, and the autopilot year leaves the kept timeline (ADR 0024). The success report names the dated
  copy to load instead.
- Kept work folders pile up until removed by hand.
- The hand-run test on a copy of the benchmark park (`tests/test_autopilot_real_game.py`, run only with
  `OPENRCT2_AUTOPILOT_REAL_GAME=1`) has not been run yet; no result is recorded here.

## Rejected alternatives

- **A label event from the plugin.** It needs a plugin change, a fourteen-contract version bump and a `make bench`.
- **Landing straight into `data/company/` while the game runs.** A failed run would put an unchecked capture in
  append-only data.
- **A label column in an intermediate model.** The roadmap's pass/fail line names `staging.stg_session_start`.
