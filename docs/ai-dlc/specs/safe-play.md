# Plan: a play launcher and an automatic backup of the last recorded save

**Bottom line.** Two small additions make it hard to play the company park without recording, and easy to recover
when it happens anyway.

1. **An "OpenRCT2 Enterprise" Mac app.** One double-click opens a Terminal window that starts the recording command;
   the command then opens the game itself and confirms it started. The app is built on the machine by
   `make launcher` and is never committed.
2. **An automatic backup copy.** After every healthy, normally finished company recording, the capture command copies
   each park's last recorded save into the game's own save folder as `<park name>-last-plugin-save-YYYY-MM-DD.park`,
   and keeps a never-overwritten archive copy in the repo's git-ignored `local/` folder. If a park is ever played
   unrecorded, loading the game-folder copy is the whole recovery.

Neither change touches the plugin, the data contract, dbt, or how events are recorded. Effort: about one and a half
days, including tests, docs and one hand test on the Mac.

Revised on 2026-11-09 after a blind review by three reviewers; the changes are listed at the end.

## Why this is needed

- **What went wrong on 2026-11-09.** The company park was played for about 40 minutes with the plain game icon. No
  events were recorded, and the manual save `Crazy Castle.park` was overwritten with the unrecorded play.
- **The cause is by design.** `make capture-data` installs the plugin, records until the game quits, then removes the
  plugin (`ARCHITECTURE.md`, "Capture command"; ADR 0009). So the plain game icon always starts without recording.
- **Why it matters.** Unrecorded game days are a real gap. Once their game month closes, the company build fails on
  purpose (ADR 0031) and names the save to replay. Recovery that day needed the last recorded autosave, found by hand
  before the game's autosave rotation (10 files kept) deleted it.

## Part 1: the launcher

### What the player sees

1. Double-click "OpenRCT2 Enterprise" (in `~/Applications`, and on the Dock if the player drags it there).
2. A Terminal window opens and runs `make play DATA_SET=company` in the repo.
3. The command does every existing capture check, installs the plugin, starts listening, then opens OpenRCT2 and
   waits up to 60 seconds to see it running.
4. The player plays and quits the game as usual. The Terminal window shows the normal capture report, including the
   new backup line (Part 2), then "Press Return to close this window."

### Design choices

1. **The capture command opens the game, not the launcher.** `capture.py` gains `--open-game`. When set, `run_session`
   runs the open command right after it prints "Open OpenRCT2 now", which is the moment the plugin is installed, the
   listener is up and the save watcher has made its first scan.
   - **Why.** Only the capture command knows when it is ready. A launcher that opened the game on a timer, or by
     reading the command's output, could open the game before the plugin is installed, which is the exact failure
     being fixed. The capture command also refuses to start while the game runs, so the game must open after it.
   - **The open command** defaults to `open -a OpenRCT2` on macOS; `--open-game-command` replaces it (the same test
     seam pattern as `--game-check-command`).
   - **A bounded wait.** With `--open-game`, `_watch` must see the game running within 60 seconds. If the open command
     fails or the game never appears, the session cleans up (removes the plugin, closes the listener) and exits 1 with
     "OpenRCT2 did not start; nothing was recorded. Open the launcher again." Without `--open-game`, the wait stays
     unbounded as today, because the player opens the game by hand.
   - **A new Make target** `play` runs `capture` with `--open-game`. It is added to `DATA_SET_GOALS`, so it takes
     `DATA_SET` on the command line only. `capture-data` is unchanged.
2. **A locally built AppleScript app that opens a committed `.command` file in Terminal.**
   - `launcher/play-company.command` (committed, executable) starts with `#!/bin/zsh -l` so it gets the login
     `PATH` (where `uv`, `npm` and `make` live), changes to the repo folder relative to its own location
     (`cd "${0:A:h}/.."`), runs `direnv exec . make play DATA_SET=company` (so any `OPENRCT2_*` setting in the
     repo's `.envrc` applies, exactly as in an interactive shell), and ends with a "Press Return to close" prompt. If
     `direnv` is not on `PATH`, it stops with a message naming `brew install direnv` and `direnv allow`. The file
     holds no machine path.
   - `make launcher` compiles a one-line AppleScript with `osacompile`, passing the absolute path of that `.command`
     file as a literal at compile time: `do shell script "open -a Terminal " & quoted form of "<path>"`. It builds to
     a temporary folder, then moves the app to `$HOME/Applications/OpenRCT2 Enterprise.app` (expanded, not a quoted
     `~`), replacing an older build only after the new one compiled. Nothing is written into the app bundle after
     `osacompile`, so the app's local code signature stays intact.
   - **Why an app, not just a `.command` file.** The project owner asked for an app-like icon. A `.command` file shows
     its extension and can only sit on the Dock's right-hand side with documents; an app sits with the game icon it
     replaces.
   - **Why not an app that scripts Terminal with `tell application "Terminal" to do script`.** That sends Apple
     Events to Terminal, which needs a one-time Automation permission and fails silently if it is denied.
     `open -a Terminal <file.command>` goes through Launch Services and needs no such permission.
   - **Why the app is built locally and not committed.** The repo's absolute path is a private machine path (Never
     break rule 5), and a compiled app is a binary.
   - **Why a visible Terminal window, not a background service.** The capture command is an interactive,
     long-running session: it prints the report at the end, Control-C must interrupt it cleanly, and it discards
     typed-ahead input through the terminal. A background launchd agent would hide the report and any refusal.
3. **The data set is fixed to `company` in the launcher.** The choice of data set is made by which icon is opened.
   Rehearsal play stays on the command line.
4. **The plain game icon is left alone.** The docs tell the player to remove the plain OpenRCT2 icon from the Dock and
   drag the new app there. Changing another program's install is out of this repo's scope.

### Claims about standard practice, after review

- C1. Partly true. An AppleScript applet compiled with `osacompile` is a common no-dependency way to give a shell
  workflow an app icon; "the standard" overstated it. Alternatives exist (a hand-made bundle with a shell script in
  `Contents/MacOS`, Platypus, Shortcuts), each with a cost noted above or a new dependency.
- C2. Disputed. Two reviewers say a locally built app carries no quarantine flag, so Gatekeeper does not block it; one
  cites Apple saying first-launch checks apply regardless of origin. The hand test settles it.
- C3. True: `open -a Terminal <file>.command` avoids the Automation permission that scripting Terminal needs.
- C4. Partly true: `open -a` finds a registered app by name; with several installed copies the pick is Launch
  Services' choice. The 60-second check catches a failed open.
- C5, C6. True.
- C7. True for a file appearing whole; it does not stop a target being replaced, so the archive never replaces.
- C8. Partly true: size and time are a cheap check, not proof of identical bytes. It must compare at the records'
  millisecond precision and re-check after copying.
- C9. Partly true: dated copies help, but same-day replacement weakens them, so the archive keeps every copy.

## Part 2: the backup copy

### What the player sees

After a normal quit of a company recording, the report gains one line per park that had a recorded save in the run:

`Backup: Crazy Castle's last recorded save (autosave_2026-11-09_19-12-03) copied to save/Crazy
Castle-last-plugin-save-2026-11-09.park.`

The file appears in the game's own "Load game" list.

### Design choices

1. **The copy runs after every other check of the run, and only when the run is healthy.**
   - **Which file.** For each park, the run's last `save_written` event (by `emitted_at`) that paired with exactly
     one file. `_report_saves` returns the whole judgment, not only its failure flag, and `convert_and_report`
     receives the run's watched-folder map (`capture.py`, the `watched` dict built at start, which includes the
     remembered folder), so the file path is resolved from the record's folder kind and name, never re-derived.
   - **When it skips.** No copy is made when the save pairing, the watcher or the `seq` audit failed in this run; the
     report says "No backup made: this run had a capture problem (above); the previous backup was kept." It also
     skips a park whose last paired save is older than a later unpaired write of that park's files in this run,
     because a newer unrecorded state may exist; the report says so.
   - **Why the last recorded save is the right restore point.** The kept timeline drops events after each save's cut
     (ADR 0024), so the last recorded save is exactly where the recorded history can resume without a gap.
   - **Why at the end, not during play.** Pairing needs the converted events, which exist only after the game quits.
     Copying every save during play (a reviewer's suggestion, to rule out a file replaced before the end) would copy
     dozens of files per session; the identity check below covers the same risk.
   - **An interrupted run (exit 130) makes no copy,** so the previous copy stays and can be older than the recorded
     data. This limit is stated in the docs.
2. **Company only.** The game-folder copy and the archive are made only for `DATA_SET=company`, so rehearsal play
   never drops files into the player's save folder.
3. **Two copies, two jobs.**
   - **The game-folder copy**, `<user dir>/save/<park name>-last-plugin-save-YYYY-MM-DD.park`, is the one obvious
     file to load. The park name comes from the session's `session_start` event; characters unsafe in a file name
     (`/`, `:`, control characters, a leading dot) become `_`; with no park name the `park_id` is used. The date is
     the local date the run ended, and a second run that day replaces that day's copy. It is skipped when the source
     and target are the same file.
   - **The archive copy**, `local/park-backups/<park_id>/<park name>-<YYYY-MM-DD-HHMMSS>.park` in the repo, is never
     overwritten and never seen by the game, so loading and re-saving a game-folder copy cannot destroy every restore
     point. `local/` is git-ignored, so no game file is ever committed (Never break rule 5). It is not under
     `data/company/`, because `make delete-company-data` removes that folder's files.
4. **The copy is checked and written safely.**
   - The source must still have the size and modified time of its paired watcher record, compared at the record's
     millisecond precision. The check runs before and again after copying; a mismatch removes the copy and reports it.
   - Each copy is written under a temporary name without the `.park` suffix (so the game never lists a half-written
     file), then renamed into place. A game-folder target that is a link or not a regular file is refused. An archive
     target that already exists is refused.
5. **Exit codes.** A run with no recorded save prints a note and keeps exit 0 (playing without saving is allowed). A
   copy that fails for any other reason (an I/O error, a changed source, a refused target) makes the run exit 1, and
   the message says "The recorded data is fine; only the backup copy failed." Exits 2 (refused) and 130 (interrupted)
   keep their meanings.
6. **No automatic deletion.** A copy is about 170 KB; one per day in the game folder for a year is about 60 MB, plus
   the archive. Deleting old copies would mean code that removes files from the player's game folder. The docs tell
   the player how to delete old copies by hand.
7. **The save watcher needs no exception for these copies.** Copies are made after the watcher stops, so the run that
   makes them never sees them, and the archive is outside every watched folder. In a later recorded run, a save the
   player makes over a game-folder copy is a real save and must be recorded and paired like any other.

## Files that change

- `src/openrct2_analytics/ingest/capture.py`: the `--open-game` and `--open-game-command` options; pass the watched
  map and data set onward.
- `src/openrct2_analytics/ingest/capture_session.py`: the open-game call and bounded wait in `run_session` and
  `_watch`; `_report_saves` returns the judgment; the backup call at the end of `convert_and_report`.
- New `src/openrct2_analytics/ingest/save_backup.py`: choosing the file per park, naming, checking and copying.
- `src/openrct2_analytics/config.py`: the archive folder setting, `OPENRCT2_BACKUP_DIR`.
- `src/openrct2_analytics/ingest/game_check.py`: the default open command per platform, beside the default game
  process name (moved from `config.py`, a golden example capped at 200 lines).
- `Makefile`: the `play` and `launcher` targets, and `play` in `DATA_SET_GOALS`.
- New `launcher/play-company.command`.
- Docs: a new ADR (0048; 0047 was taken by the time of the build) "Open the game from the capture command and keep a backup of the
  last recorded save"; `ARCHITECTURE.md` ("Capture command"); `CLAUDE.md` (the `play` and `launcher` commands);
  `docs/CONVENTIONS.md` module map; `README.md` if it lists the play steps; the steps to set up the Dock icon.
- `contracts/reference/save_file_observation.odcs.yaml`: drop the "a start row's file_name ends in -main" rule
  (version 1.2.0), because Part 3 writes start records for every `.park` file.
- Tests: `tests/test_save_backup.py`, `tests/test_capture_play.py`, the capture and save-file tests,
  `tests/test_makefile.py`.

## Tests

- **Backup**, with real files in temporary folders:
  - picks the last paired save per park when a run has several saves and two parks;
  - resolves an autosave, a save-folder file and a remembered-folder file through the watched map;
  - matches a real file's modified time at millisecond precision (a real `stat`, not a typed number);
  - names the game-folder copy from the park name, cleans unsafe characters, falls back to the `park_id`;
  - replaces the same day's game-folder copy, never replaces an archive copy, and skips a source equal to its target;
  - refuses a source whose size or time changed before or after copying, and a target that is a link;
  - makes no copy on an interrupted run, a failed pairing, a watcher error, a `seq` failure, a rehearsal run, or
    when a later unpaired write exists, and says why;
  - never leaves a temporary file behind.
  - Each test is first run against a deliberately broken version to see it fail.
- **Open game**, with a stand-in open command and the stand-in game process the capture tests already use:
  - the open runs after the install and the "Open OpenRCT2 now" line;
  - a failing open, or a game that never appears within the limit, cleans up and exits 1;
  - without `--open-game` nothing is opened and the wait is unbounded.
- **Launcher**: a test checks `play-company.command` holds no absolute path and is executable. `make launcher` needs
  `osacompile` and runs only by hand on macOS, so `make check` does not run it.
- **By hand on macOS, once**: build the launcher, double-click it, confirm no Gatekeeper or permission prompt, play a
  few game days, save, quit; confirm the report's backup line, the game's Load list, and the archive file. Then open
  the launcher with the game already running, and confirm the refusal is readable in the Terminal window.

## Out of scope

- An in-game "NOT RECORDING" sign (needs the plugin installed permanently; deferred).
- Hiding the plain OpenRCT2 app.
- Running the after-play steps (`make after-play`) automatically after the game quits.
- Deleting old backup copies.
- Windows and Linux launchers.

## Part 3: a warning before play when a save changed while nothing was recording

Approved by the project owner on 2026-11-09.

- **What the player sees.** Before the game opens, a line such as "Crazy Castle.park changed after the last recorded
  save; load Crazy Castle-last-plugin-save-2026-11-08.park instead." The warning never stops the run.
- **How.** Today the first scan writes a `start` record only for `-main` files, and the existing check compares each
  start record with that file's last paired write in earlier runs (`save_pairing.py`, the "R15" check). The first scan
  now writes a start record for every `.park` file in the watched folders, and the same check runs over all of them
  and names the newest game-folder backup of the file's park, when one exists.
- **Why reuse the existing check.** It already knows each file's last recorded write across runs; extending its input
  is smaller and safer than a second, parallel check.
- **Cost.** About half a day, and more save-file records per run (one start record per `.park` file). ADR 0037's rule
  that only `-main` files get start records changes, so the new ADR supersedes that line.
- **Tests.** A file modified after its last paired write warns, with the backup name; an unchanged file does not; a
  file never paired in any run prints no warning; the existing `-main` warnings keep their text.

## Changes after the blind review (2026-11-09)

- Added the 60-second wait for the game, with cleanup and exit 1 on failure.
- Compared modified times at millisecond precision, with a re-check after copying.
- Copied only after a healthy run, and only for the company data set; skipped when a newer unpaired write exists.
- Added the never-overwritten archive copy under `local/park-backups/`.
- Passed the pairing judgment and the watched-folder map through instead of re-deriving them.
- Moved the machine path out of any file written into the app; the `.command` file is committed and path-free.
- Ran the launcher through a login shell and `direnv exec`; fixed the quoted-`~` path; added the "Press Return"
  prompt; added `play` to `DATA_SET_GOALS`.
- Dropped the game date from the report line (it would need new fields for no recovery value).

## Changes during the build (2026-11-09)

- **The warning before play is its own call.** The R15 lines print only in the report after the game quits, so the
  run now judges the earlier runs' records and events right after the first scan and prints the warnings before the
  "Open OpenRCT2 now" line (`save_backup.warn_before_play`). The same check still runs in the report.
- **Less noise in the report.** For a file without the `-main` suffix, the report prints only the "changed since its
  last paired write" warning; the "no earlier paired write" note and the lost-event warning stay `-main` only, so ten
  autosaves do not add ten notes per run.
- **A wider skip rule.** A park is also skipped when another park later saved over its chosen file in the same run;
  the identity check would otherwise fail that copy and exit 1 for a run with nothing wrong.
- **An archive setting.** The archive root is `OPENRCT2_BACKUP_DIR` (default `local/park-backups`), like
  `OPENRCT2_CAPTURE_DIR`, so tests never write into the repo's own `local/` folder.
- **The open command's error output goes to a temporary file, not a pipe.** A program the open command leaves
  running (the game) would hold a pipe open and stall the capture command.
- **The contract rule on start rows is dropped** (see "Files that change").
- **Only the command's own dated copy is replaced or recommended** (after review). A dated copy counts as the command's
  own while its bytes equal one of that park's archive copies. Otherwise (the player saved into it, or a same-named
  park owns it) the copy goes beside it with `-HHMMSS` added, and the warning names an own copy or the archive copy.
  A dated copy that is no longer the command's own warns before play; one the command replaced never does.
- **The 60-second limit runs only while the check clearly says "not running" and no event landed**, and a timeout
  checks once more for a late game and prints a loud "NOT recording" line (after review).
- **A chosen autosave the game already deleted is skipped with a note**, and the archive and game-folder copies are
  attempted independently (after review).
- **The launcher stops with a message when `direnv` does not trust the folder** (after review).
- **`--open-game-seconds`** is a test seam for the 60-second limit.
