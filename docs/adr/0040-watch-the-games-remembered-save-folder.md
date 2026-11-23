# ADR 0040: watch the game's remembered save folder

- Date: 2026-10-20.
- Status: Accepted 2026-10-20 (save-watch folder slice).

## Bottom line

`make capture-data` now also watches the folder the game remembers in `config.ini` (`last_game_directory` under
`[general]`), as a fourth folder of kind `remembered`, so a menu save made outside `save/` still pairs with its
`.park` file. A separate function, `remembered_folder`, finds the folder before the watcher starts; the scan, the
record layout and the pairing rule are unchanged (the folder listing moved into a shared `list_park_files`). ADR 0037 stays as written; this record adds one folder to its watcher.

## Context

The Save As dialog opens in the folder the park was loaded from, so a save can land outside the three watched folders
(`docs/architecture/openrct2-facts.md`, "Save As dialog" and "Remembered save folder"). The game keeps a remembered folder in
`config.ini`: `last_game_directory` under `[general]`, in double quotes, and `""` when none is set (observed
2026-10-20 in OpenRCT2 0.5.6). That the game writes the folder of the last save or load into it is unverified; only
the key, section and quoting were observed. The spec is `docs/ai-dlc/specs/save-watch-folder.md`.

## Decision

1. **A separate function adds the folder; `watch_folders` is unchanged (D1).** `remembered_folder(user_dir)` in
   `src/openrct2_analytics/ingest/save_watch.py` returns the folder to add (or none) and the one line to print; `run()`
   in `capture.py` merges it into the dict that `watch_folders` returns and prints the line before the watcher
   starts. The three-folder test and the list of kinds stay as they are, and the reader is testable without a watcher.
   Cost: the folder set comes from two calls.
2. **The folder is probed before the watcher starts, not in the scan (D3).** The probe lists the folder and stats each
   `.park` entry as the scan does, so it fails on every error the first scan would raise. A missing folder is kept
   and waited for; any other error drops the folder with `Note: the game's remembered save folder <folder> cannot be
   read (<ErrorName>: <message>); it is not watched.` (plus a macOS privacy pointer for a `PermissionError`). Gain: an
   unreadable remembered folder cannot fail the first scan, so that failure path stays as it is for the default
   folders. Cost: a folder that turns unreadable between the probe and the first scan still takes the existing exit 1.
3. **A new kind, `remembered` (`REMEMBERED_KIND`).** Records carry `folder_kind: "remembered"` and the base name, never
   the path; the contract's kind list gains the value (contract 1.1.0). Pair lines read `<name> (remembered)`, and
   the gone and back lines read "remembered save folder is gone; watching for it to return." and "remembered save
   folder is back."
4. **Lines printed, at most one per run.** No usable value (no file, no key, empty) prints `Note: config.ini names no
   remembered save folder; watching the save, autosave and user folders only.` An unreadable or malformed
   `config.ini`, or a relative path, prints its own `Note:` line and adds nothing. A value naming a default folder
   adds nothing and prints nothing. A value outside the user folder is watched and prints `Warning: the game's
   remembered save folder <folder> is outside the OpenRCT2 user folder; watching it too.` The path reaches the console
   only, never a record.

## Rejected options

- **Put the reader in `watch_folders`.** Gain: one call. Cost: it would change a pinned test and make the folder set
  depend on a file read.
- **A new module for the reader.** Gain: a smaller `save_watch.py`. Cost: a file for about 50 lines.
- **Refuse the capture when `config.ini` is broken.** Gain: a hard stop. Cost: a lost play session for an optional
  feature.

## Consequences

- **The "-main" history check can print a false line across runs.** The report's check compares records across runs by
  folder kind and file name, but `remembered` can name a different folder in each run, so a file of the same name in
  two different remembered folders is read as one file's history. Recording the folder would put a path in a record,
  so the change accepts this; a test pins the current report lines.
- **An I/O error in the optional remembered folder after start fails the whole capture with exit 1 (D5).** After start
  the folder behaves like any watched folder: a vanished folder prints the gone and back lines, but any other `OSError`
  in a later scan stops the watcher. A remembered folder that turns unreadable mid-run fails the run instead of being
  dropped.
- A save with the same base name in the remembered folder and another watched folder within 5 seconds is a
  two-candidate window and fails the run, as it does for the other folders.
- `ARCHITECTURE.md` ("Capture command") and `docs/architecture/openrct2-facts.md` describe the folder.
- ADR 0037 is the previous record on the watcher.
