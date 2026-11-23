# Spec: the save watcher's remembered save folder

status: draft 2026-10-20, a delta on `docs/ai-dlc/specs/save-file-watcher.md` (the spec that built the watcher; its
requirement numbers are written "watcher spec R<n>" below). Contract map: `docs/ai-dlc/contracts/save-watch-folder.md`.

## Bottom line

During a capture, the save watcher (the background thread of `make capture-data` that records every `.park` file
written) misses saves made into a folder other than its three. In the practice session it matched only 9 of 56 saves,
because the 47 named saves went to a folder outside the OpenRCT2 user folder that the game's Save dialog remembered.
This change reads that remembered folder from the game's `config.ini`, watches it too, and records its files under a
new folder kind, `remembered`. A remembered folder outside the user folder prints one console warning; no folder
remembered, or a `config.ini` that cannot be read or holds a non-absolute value, prints one note and the watcher
behaves as today. The save-file record contract gains the new kind as a minor version bump (1.0.0 to 1.1.0), kept
even though the breaking-change tool prints a warning for it (the tool exits 0; the PR states the warning). No new
package, no plugin change, no path in any record.

## Goal

Every save of a capture pairs with the file it wrote, so later rules that follow a park's main save have a complete
file history. The project goal is "a portfolio analytics stack for a theme park run as a business" (`CLAUDE.md:3`);
the watcher exists because the plugin cannot see file names (watcher spec Goal, `openrct2-facts.md:43`). The stated
rulings (2026-10-20) are binding:

1. "the tracker reads the game's last-used save folder from config.ini, watches it too, and warns when it lies outside
   the OpenRCT2 user folder; unit test."
2. "When config.ini names no remembered save folder, it watches the default folders as today and prints one note."
3. "Files found there get a new folder_kind 'remembered', added to the save-file record contract as a minor version
   bump."

Further rulings (2026-10-20, now requirements R1, R2b, R2c, R13 and Verify-by 3): the key is `last_game_directory`
under `[general]` and only outer double quotes are stripped; a malformed or unreadable `config.ini`, or a
non-absolute value, gives a note and the default folders; the version stays 1.1.0 even if the breaking-change tool
warns, and the PR states the warning; the same folder is never watched twice; the ADR is number 0040.

Checked fact (cited, not re-derived): OpenRCT2's `config.ini` keeps the remembered folder as `last_game_directory`
under `[general]`, its value double-quoted (`last_game_directory = "/path/to/save"`); an empty value is `""`. This was
read from a real `config.ini` on the project owner's machine on 2026-10-20. `config.ini` sits in the OpenRCT2 user
folder. Nothing in `src/` reads `config.ini` today, and stdlib `configparser` keeps the quotes (contract map (4)).

## Decisions settled by this spec

Each decision states its gain and cost. Only the real-play checks remain under "Needs owner decision".

- **D1. A separate function adds the folder; `watch_folders` is unchanged.** A new `remembered_folder(user_dir)`
  returns the folder to add (or none) and the one line to print; `run()` merges it into the dict that
  `watch_folders(user_dir)` returns. Gain: the pinned three-folder test (`test_save_watch.py:90-95`) and the `KINDS`
  list (`test_save_watch.py:23`) stay as they are, and the reader is unit-testable without a watcher. Cost: the folder
  set now comes from two calls, so a reader of `run()` sees both.
- **D2. The reader lives in `save_watch.py`.** Gain: one owning module for "which folders are watched"; the file grows
  from 235 to about 330 lines. Cost: `save_watch.py` gains a `configparser` import beside its threading code. A new
  module was weighed and rejected: it adds a file for about 50 lines.
- **D3. The remembered folder is probed before the watcher starts, not in the scan.** The probe lists the folder and
  stats each `.park` entry exactly as `SaveWatcher._list` does (`save_watch.py:160-186`), by reusing that listing or
  sharing one helper with it, so the probe fails on every error the first scan would raise (an `os.scandir` error, or
  a `PermissionError` from `stat` on a folder with read but no search permission). Gain: an unreadable remembered
  folder cannot fail the first scan, so the first-scan failure path (watcher spec R5, the `WatcherStartFailed`
  exit 1 tested at `test_capture_saves.py:219`) stays exactly as it is for the default folders and the record
  folder, and `SaveWatcher._list` needs no per-kind `except`. Cost: a folder that turns unreadable in the moment
  between the probe and the first scan still takes the existing exit-1 path (rare, and the run says why); the probe
  duplicates one directory listing at start.
- **D4. "Same folder" uses `os.path.samefile`; "inside" uses resolved paths.** For the equal test (R3), two folders
  are the same when both exist and `os.path.samefile` says so (as `publish_rotation.py:45` does), and otherwise when
  their `Path.resolve()` results are equal (a missing folder still resolves). `Path.resolve()` alone does not fold
  letter case, so on macOS's default case-insensitive disk a value differing from `save/` only in case would be
  watched twice and fail the run (every save a two-candidate window, `save_pairing.py:146-153`). The inside test (R4)
  uses `Path.resolve()` and `is_relative_to`; a case-variant of a folder inside the user folder is the one residual
  case, and the worst result is a spurious R5 warning, not a double watch. Gain: a symlinked, `..`-laden or
  case-variant path to a default folder is not watched twice. Cost: a few `stat` calls; two comparison routes.
- **D5. After start, the remembered folder behaves like any other watched folder.** It vanishing (an unplugged drive
  raises `FileNotFoundError`) prints the existing gone/back lines with kind `remembered`; any other `OSError` in a
  later scan stops the watcher and fails the run with exit 1, as today (watcher spec R6). Gain: no new error path in
  the thread. Cost: a remembered folder that turns unreadable mid-run fails the run instead of being dropped.

## Requirements

### Reading the remembered folder

- **R1. Where and how `config.ini` is read.** `remembered_folder(user_dir)` reads `user_dir / "config.ini"` with the
  encoding `utf-8-sig` (UTF-8, tolerating a byte-order mark, which plain `utf-8` hands to the parser as a stray
  character that raises `MissingSectionHeaderError`) through `configparser.ConfigParser(interpolation=None)` (stdlib;
  `interpolation=None` because a `%` in a path breaks the default interpolation). It reads `last_game_directory` under
  `[general]` and strips exactly one leading and one trailing `"` when both are present, and nothing else: no escape
  is interpreted (source: checked fact; configparser keeps the quotes). It is read once, when the watcher is built in
  `run()` (`capture.py:204-206`), never re-read during the run. (Source: ruling 1; contract map (4).)
- **R2. No remembered folder.** When `config.ini` is missing, has no `[general]` section, has no
  `last_game_directory` key, or the value is empty after stripping (`""`), no folder is added and one line is printed
  (source: ruling 2):

  `Note: config.ini names no remembered save folder; watching the save, autosave and user folders only.`

  Reason: all three mean the game has no remembered folder to offer, so the defaults are the whole answer. A missing
  `config.ini` (`FileNotFoundError`) is this case, not R2b's.
- **R2b. A `config.ini` that cannot be read or parsed.** `remembered_folder` catches `OSError` (a permission error, or
  `IsADirectoryError` when `config.ini` is a folder), `configparser.Error` (a malformed file) and
  `UnicodeDecodeError` (a non-UTF-8 file; it is a `ValueError`, not an `OSError`), and only those. No folder is added
  and one line is printed (source: owner ruling 2026-10-20):

  `Note: config.ini could not be read (<ErrorName>: <message>); watching the save, autosave and user folders only.`

  Reason: an optional feature never blocks a capture, and the error is shown, not swallowed. Cost: a broken
  `config.ini` costs the remembered folder for that run. The alternative, refusing the capture with exit 2, gains a
  hard stop and costs a lost play session.
- **R2c. A value that is not an absolute path.** When the stripped value is not absolute (`Path.is_absolute()`), no
  folder is added and one line is printed (source: owner ruling 2026-10-20):

  `Note: config.ini's remembered save folder <value> is not an absolute path; watching the save, autosave and user folders only.`

  Reason: a relative value would be read against the shell's current folder. Cost: if the game ever writes a
  relative value, that folder is not watched. The value is printed as `config.ini` gives it, on the console only
  (R5's path rule).
- **R3. Same as a default folder.** When the folder is the same folder (D4: `os.path.samefile` when both exist, equal
  resolved paths otherwise) as `user_dir / "save"`, `user_dir / "save" / "autosave"` or `user_dir`, no folder is added, no new kind is used, and nothing is printed.
  Reason: it is already watched under its own kind; watching it twice would record every save twice and make each
  save a two-candidate window (contract map RISKS; `save_pairing.py:146-153`). The same folder is never watched
  twice, whatever the path spelling. (Source: stated edge rulings.)
- **R4. Inside the user folder elsewhere.** When the resolved folder lies inside the resolved user folder
  (`Path.is_relative_to`) but is none of R3's three, it is watched as kind `remembered` and nothing is printed.
  Reason: it is a normal game folder, so there is nothing to warn about. (Source: stated edge rulings.)
- **R5. Outside the user folder.** Otherwise it is watched as kind `remembered` and one warning is printed, naming the
  folder as `config.ini` gives it (after quote stripping), on the console only (source: ruling 1):

  `Warning: the game's remembered save folder <folder> is outside the OpenRCT2 user folder; watching it too.`

  The path appears only on the console, which already prints paths (`capture.py:96`); it never reaches a save-file
  record, committed console output or committed text (invariant 5; contract map (5)). Temporary test files, such
  as a test's own `config.ini`, may hold temporary paths.
- **R6. Missing or unreadable at start.** `remembered_folder` probes the resolved folder the way the first scan would:
  it lists the folder and stats each `.park` entry as `SaveWatcher._list` does (D3), so a folder that passes the probe
  passes the first scan:
  - `FileNotFoundError`: the folder is kept and the first scan waits for it, as for a missing `autosave` folder
    (watcher spec R7, `save_watch.py:164-169`); R5's warning still prints when it applies. Reason: a remembered folder
    on a drive not yet mounted is still the folder the game will save to.
  - Any other `OSError` (a folder without read permission, a folder with read but no search permission whose `stat`
    raises `PermissionError`, or a value naming a file, `NotADirectoryError`): the folder is not added and one line is
    printed instead of R4's silence or R5's warning:

    `Note: the game's remembered save folder <folder> cannot be read (<ErrorName>: <message>); it is not watched.`

    When the error is a `PermissionError`, the line ends with the extra sentence ` On macOS, allow the terminal under
    System Settings, Privacy & Security, Files and Folders (or Full Disk Access), then run the capture again.`
    Reason: macOS privacy controls can deny the terminal access to a folder under Documents, Desktop, Downloads,
    iCloud or an external volume, and without the pointer the fix would silently watch nothing new.

  Each `except` names its reason in a comment (`docs/CONVENTIONS.md` no-swallowing rule). The default folders and the
  record folder keep today's first-scan failure path unchanged (D3).
- **R7. One line at most.** `remembered_folder` returns at most one line, and `run()` prints it through `say` before
  the watcher starts, so it appears before the "Open OpenRCT2 now and play" line (`capture_session.py:267`).

### Watching and records

- **R8. The new kind.** The added folder's kind is the string `remembered`, a named constant in `save_watch.py`. The
  watcher, records, pairing and report need no other change: identity is (`folder_kind`, `file_name`)
  (`save_pairing.py:27`, `:45`), so a pair line reads "`<name> (remembered): save_id …`" and the gone/back lines read
  "remembered save folder is gone; watching for it to return." and "remembered save folder is back."
  (`save_watch.py:168`, `:173`). The pinned report lines and gone/back wording do not change (contract map (2)).
  Known limitation: the report's "-main" history check compares records across runs by (`folder_kind`, `file_name`)
  (`save_pairing.py:212-217`, `:222-247`), but `remembered` can name a different folder in each run, so a file of
  the same name in two different remembered folders is read as one file's history and can print a false line. The
  change accepts this (recording the folder would put a path in a record, R9) and pins the current lines with a test
  (A17).
- **R9. Records hold only the kind name.** A record from the remembered folder carries `folder_kind: "remembered"`
  and the base name; never the folder's path (watcher spec R1, R8; `save_watch.py:6`).
- **R10. Same base name in two folders.** Unchanged: a save whose base name is written in both the remembered folder
  and another watched folder within one 5-second window is a two-candidate window and fails the run, as today
  (`save_pairing.py:146-153`). Stated so a reviewer does not count it as a regression.

### Contract

- **R11. Minor bump.** In `contracts/reference/save_file_observation.odcs.yaml` (a hotspot):
  - `version: 1.0.0` becomes `version: 1.1.0` (`:5`; ruling 3; invariant 6, a widened allowed list is not breaking);
  - the `folder_kind` property description (`:48`) becomes "The watched folder the file sits in, save, autosave,
    parent or remembered (the game's last-used save folder, read from config.ini); text.";
  - the quality rule (`:70-71`) gets the description "folder_kind is save, autosave, parent or remembered" and the
    query `... WHERE folder_kind NOT IN ('save', 'autosave', 'parent', 'remembered')`;
  - the "all seven fields" text (`:26`) is unchanged: no field is added.
- **R12. Kind lists elsewhere.** The comment at `save_pairing.py:37` (the only edit to the pairing module; its code
  treats `folder_kind` generically, `:27`, `:45`, `:278`) and the module docstring at `save_watch.py:1-9` name the
  fourth kind. `test_save_files.py:44` (`RULE_LINE`) changes to R11's new description; the `"backup"` break
  at `:36` stays and still fails.

### Records to update

- **R13. Documents, in the same change** (`engineering-standards.md`: a change that invalidates a doc updates it):
  - `ARCHITECTURE.md:306-316` ("three folders"): the remembered folder, its source in `config.ini`, the note and
    warning lines, the `remembered` kind. `ARCHITECTURE.md` is already 667 lines; the edit replaces text in place and
    adds at most a few lines.
  - `docs/architecture/openrct2-facts.md`: one row for `last_game_directory` under `[general]`, quoted, empty as `""`,
    observed 2026-10-20 in OpenRCT2 0.5.6, with no machine path. The "Save As dialog" row (`:45`) stays.
  - A new ADR, `docs/adr/0040-watch-the-games-remembered-save-folder.md` (the number before it is taken by the
    month-start cash branch), recording D1, D3 and the new kind. Its consequences state two things: the "-main" history limitation of
    R8, and that an I/O error in the optional remembered folder after start fails the whole capture with exit 1 (D5).
    ADR 0037 is not edited (records are superseded, not edited). Gain: the reason for a fourth kind survives the
    spec's deletion. Cost: one short file.

## Files and owning modules

| File | Change | Owner |
|---|---|---|
| `contracts/reference/save_file_observation.odcs.yaml` | R11; **hotspot** | `contracts/` |
| `tests/test_save_files.py` | R12: `RULE_LINE`; a `remembered` record passes the check | `tests/` |
| `src/openrct2_analytics/ingest/save_pairing.py` | Comment at `:37` only (R12) | `ingest/` |
| `src/openrct2_analytics/ingest/save_watch.py` | `remembered_folder`, the kind constant, docstring (R1 to R9) | `ingest/` |
| `src/openrct2_analytics/ingest/capture.py` | Merge the remembered folder into the watched dict and print its line (R7) | `ingest/` |
| `tests/test_save_watch_remembered.py` | New: R1 to R10 unit and end-to-end cases | `tests/` |
| `ARCHITECTURE.md`, `docs/architecture/openrct2-facts.md`, `docs/adr/0040-…` | R13 | docs |
| `CHANGELOG.md` | "Unreleased" entry names the remembered folder | docs |

Not touched: `tests/test_save_watch.py` (438 lines; its `:90-95` test and `KINDS` stay), `tests/test_capture_saves.py`
(451 lines; its `:219` test must still pass unchanged), `Makefile`, `pyproject.toml`, `uv.lock`, `plugin/`,
`convert.py`, `models/`. New tests go in a new file because both existing test files would pass 500 lines.

## Contracts and regeneration

Only the reference contract above changes, 1.0.0 to 1.1.0. The event contracts, the dbt sources and the plugin do
not change: the converter, dbt and the event contracts never read these records (`save_file_observation.odcs.yaml:7-12`).
Because the file now has a base on `origin/develop`, the breaking-change check (`scripts/check_contract_breaking.py`,
run when `CI` is set) compares it for real this time. Measured result (2026-10-20): `datacontract breaking` run on
temporary copies carrying R11's exact edits printed a WARNING on `quality.[1].query` and INFO on two descriptions, and
exited 0. The script fails a change when the tool exits with its breaking code and no major bump exists, and also when the
tool exits with any other non-OK code (`check_contract_breaking.py:160-164`, `:186-189`, `:190-207`). The tool's
exit 0 here means 1.1.0 passes; the owner's ruling to keep 1.1.0 stands and the PR body quotes the WARNING line.
Contingency: if the build's own `CI=1 uv run python scripts/check_contract_breaking.py` exits with any non-zero
code, the build parks; nobody weakens the check. Verify-by 3 runs it.

## Test seams

- **Temp user folder.** Every test builds the user folder under `tmp_path` and writes its own `config.ini` there
  (for example `[general]` and `last_game_directory = "<tmp_path>/elsewhere"`). An end-to-end test points
  `OPENRCT2_USER_DIR` at it, as `test_capture_saves.py:416` does. A temporary `config.ini` may hold a temporary
  path; no test reads a real player folder, and no committed text holds a real machine path.
- **Pure reader.** `remembered_folder(user_dir)` reads one file and probes one folder; tests call it directly and
  assert the returned folder and line.
- **Watcher with four folders.** A test builds `{**watch_folders(user_dir), "remembered": <folder>}` by hand and calls
  `scan()` directly (watcher spec test seam "one scan without a thread"); `remembered` never joins `KINDS`.
- **Unreadable folder.** `chmod 000` on a temp folder, and `chmod 444` (read, no search) on another holding a
  `.park` file, each restored in a `finally`; the tests are skipped when run as root, where permissions do not bite.
  A file in place of the folder covers `NotADirectoryError`.
- **Unreadable `config.ini`.** Temp files holding latin-1 bytes, a byte-order-marked valid file, a malformed file
  (no section header), a folder named `config.ini`, and a `config.ini` with mode 000 (skipped as root).
- **Case-variant folder.** The value spelled with different letter case from `save/`; skipped when the temp disk is
  case-sensitive (a probe of the temp folder decides).
- **End to end.** Fixtures and helpers are imported from `tests.test_capture` and `tests.test_capture_saves`, as
  `test_capture_saves.py:33` does.

## Golden paths

- The reader follows the deliberate-skip style of `SaveWatcher._list` (`save_watch.py:160-186`): catch only the named
  error, return a plain value, say why in a comment.
- The end-to-end case follows `test_capture_saves.py`'s capture tests (`:122`, `:416-447`); unit cases follow
  `tests/test_save_watch.py`; the contract cases follow `test_save_files.py:25-50`.
- A rule in `docs/CONVENTIONS.md` outranks these examples.

## Out of scope

- Re-reading `config.ini` during a run (a folder changed in the Save dialog mid-session is not followed).
- Watching more than one remembered folder, subfolders of it, or any `config.ini` key other than
  `last_game_directory`.
- Any change to pairing, the 5-second window, the report wording, the record's seven fields, the plugin, or dbt.
- Recovering the 47 unmatched practice-session saves; records are append-only (invariant 2).
- The "-main" history limitation across runs with different remembered folders (R8); it is recorded in the ADR.
- Warehouse rules that use the records (watcher spec "Out of scope").

## Constraints

- No new dependency: stdlib `configparser`, `os`, `pathlib` only (`engineering-standards.md`).
- Every touched or new code file stays under 500 lines (`check_file_sizes` counts code suffixes only);
  `ARCHITECTURE.md` (667 lines) is the named exception: flagged and only edited in place.
- Records and committed text hold only the kind name, never a folder path (invariant 5, R9). Tests use `tmp_path`;
  their temporary `config.ini` files may hold temporary paths, which are not committed.
- `contracts/` is a hotspot: one ticket owns the contract file, and no other ticket edits it.
- No swallowed error: every deliberate `except` (R2b's three error types, R6's probe errors, and `FileNotFoundError`
  for a missing `config.ini` if caught rather than checked) names its reason in a comment.
- The eight invariants of `CLAUDE.md`; invariants 1 and 8 are untouched because no event or plugin code changes.
- Committed text never names the project owner.

## Verify-by

Commands a fresh worker runs end to end from the branch head, offline, with no game installed:

1. `make check` exits 0.
2. `uv run pytest tests/test_save_watch_remembered.py tests/test_save_watch.py tests/test_save_files.py
   tests/test_capture_saves.py tests/test_capture.py -q` passes.
3. `CI=1 uv run python scripts/check_contract_breaking.py` exits 0 (needs the local `origin/develop` ref; no
   network). The PR body quotes the tool's WARNING line. A non-zero exit parks the build; the check is not weakened.
4. `grep -n '^version: 1.1.0$' contracts/reference/save_file_observation.odcs.yaml` prints one line, and
   `grep -c 'seven fields' contracts/reference/save_file_observation.odcs.yaml` prints 1.
5. A test in `tests/test_save_files.py` runs the save-file checker over a temporary data folder: a record with
   `folder_kind: "remembered"` passes and one with `"backup"` is rejected with R11's rule line. (The committed sample
   has no save-file records, so a run over it cannot fail; `save_files.py:293-295`.)
6. `git diff --name-only origin/develop...HEAD` lists only the files in "Files and owning modules" plus process
   records, and `git diff origin/develop...HEAD -- pyproject.toml uv.lock plugin/ Makefile` is empty.
7. `git diff origin/develop...HEAD -- . ':(exclude)docs/ai-dlc' | grep -nE '^\+.*(/Users/|/home/)'` prints nothing (the
   process records are left out because they quote this command), and a reviewer reads every committed addition
   (process records included) for machine paths and personal names; the grep alone is narrower than that rule.
8. `wc -l src/openrct2_analytics/ingest/save_watch.py src/openrct2_analytics/ingest/capture.py
   tests/test_save_watch_remembered.py tests/test_save_files.py` shows every code file under 500 lines
   (`ARCHITECTURE.md`, 667 lines, is the named exception and is edited in place).

Deferred to real play (not run by the build; recorded in the first real-play review):

- A capture where the Save dialog's folder is outside the user folder pairs every named save with a `remembered`
  record.
- The check records where that folder lives (for example under Documents, Desktop, Downloads, iCloud or an external
  volume) and whether the watcher watched it. If R6's `PermissionError` note appears, the macOS Files and Folders
  setting is the first thing to check; a reproducer is `os.scandir` on the folder from the terminal that runs
  `make capture-data`.

## Acceptance

| # | Criterion | Tag | Req |
|---|---|---|---|
| A1 | `make check` exits 0 on the branch head | check: Verify-by 1 | all |
| A2 | `config.ini` missing, without `[general]`, without the key, and with `""` each add no folder and return R2's note exactly | check: `test_save_watch_remembered.py` | R1, R2 |
| A2b | A latin-1 `config.ini`, a malformed one (no section header), a folder named `config.ini`, and an unreadable one (mode 000, skipped as root) each add no folder, return R2b's note with the error name, and raise nothing | check: `test_save_watch_remembered.py` | R2b |
| A2c | A relative value (for example `saves/here`) adds no folder and returns R2c's note exactly | check: `test_save_watch_remembered.py` | R2c |
| A3 | A quoted value has its outer quotes stripped and an unquoted value is unchanged; a value holding `%` is read without error; a valid file with a byte-order mark is read | check: `test_save_watch_remembered.py` | R1 |
| A4 | A value equal to `save`, `save/autosave` or the user folder, written directly, through a symlink, and (skipped on a case-sensitive disk) in a different letter case, adds no folder and prints nothing | check: `test_save_watch_remembered.py` | R3, D4 |
| A5 | A value inside the user folder but none of the three adds `remembered` and prints nothing | check: `test_save_watch_remembered.py` | R4 |
| A6 | A value outside the user folder adds `remembered` and returns R5's warning naming the folder; no save-file record, and no console output or text the test commits, holds the path (temporary test files may hold temporary paths) | check: `test_save_watch_remembered.py` | R5, R9 |
| A7 | A missing remembered folder is kept and a file created there after the first scan yields a `created` record of kind `remembered`; an unreadable folder, a folder with read but no search permission (mode 444, holding a `.park` file; skipped as root) and a file in its place are not added and return R6's note; the `PermissionError` cases end with the macOS privacy sentence | check: `test_save_watch_remembered.py` | R6 |
| A8 | A watcher over the four folders writes `folder_kind: "remembered"` records, prints "remembered save folder is gone; watching for it to return." and "… is back." | check: `test_save_watch_remembered.py` | R8 |
| A9 | End to end: with `OPENRCT2_USER_DIR` at a temp folder whose `config.ini` names an outside temp folder, the warning prints before the "Open OpenRCT2 now" line, a save written there pairs with a "(remembered)" pair line, and the run exits 0 | check: `test_save_watch_remembered.py` | R5, R7, R8 |
| A10 | `test_save_watch.py:90-95` and `test_capture_saves.py:219` pass unchanged | check: Verify-by 2; `git diff origin/develop...HEAD -- tests/test_save_watch.py tests/test_capture_saves.py` is empty | D1, D3 |
| A11 | The contract is 1.1.0, accepts `remembered`, still rejects `backup` with R11's rule line, and keeps "seven fields" | check: `test_save_files.py`, Verify-by 4 | R11, R12 |
| A12 | `CI=1 uv run python scripts/check_contract_breaking.py` exits 0 on the bumped contract and the PR body quotes its WARNING line | check: Verify-by 3 | R11 |
| A13 | No new dependency, no plugin, Makefile or dbt change, no private path or personal name in any committed addition, every code file under 500 lines | check: Verify-by 6, 7, 8 | Constraints |
| A14 | `ARCHITECTURE.md`, `openrct2-facts.md` and the new ADR 0040 describe the remembered folder accurately (the ADR includes the R8 and D5 consequences) and hold no machine path or owner name | judgment: reviewer reads each against R13 and the code | R13 |
| A15 | Every `except` catches only the named errors and states why; nothing in the scan thread changed | judgment: reviewer reads `remembered_folder` and the `save_watch.py` diff | R2b, R6, D3, D5 |
| A16 | The save-file checker run over a temporary data folder accepts a `remembered` record and rejects a `backup` record | check: `test_save_files.py`, Verify-by 5 | R11 |
| A17 | A pairing-report test pins today's report and "-main" history lines for a `remembered` record, and the ADR states the cross-run limitation | check: `test_save_watch_remembered.py`; judgment: reviewer reads the ADR | R8, R13 |
| A18 | A save whose base name is written in both the remembered folder and another watched folder within one 5-second window is a two-candidate window and fails the run, as before the change | check: `test_save_watch_remembered.py` | R10 |

## Definition of Done

The change is done when A1 to A18 hold on the branch head, `make check` is green after each ticket (not only at the
end), Verify-by steps 1 to 8 have run with their results stated in the PR, and the PR is merged into `develop` after
its reviewer passes. The real-play checks stay open until a play session runs them.

## Tickets

No behaviour-preserving refactor is needed first: D1 leaves `watch_folders` and the watcher's scan untouched, so a
refactor ticket would be empty. Three tickets, in dependency order:

1. **Contract 1.1.0** (**hotspot: `contracts/`**). Owns `contracts/reference/save_file_observation.odcs.yaml`,
   `tests/test_save_files.py`, the comment at `save_pairing.py:37`. Delivers R11, R12, A11, A12, A16. Lands first so
   records of the new kind pass the check.
2. **Read and watch the remembered folder.** Owns `save_watch.py`, `capture.py`, the new
   `tests/test_save_watch_remembered.py`. Delivers R1 to R10, A2 to A10, A15, A17, A18. Depends on ticket 1 for A9's record check.
3. **Records.** Owns `ARCHITECTURE.md`, `docs/architecture/openrct2-facts.md`, `docs/adr/0040-…`. Delivers R13, A14.

Gain of three tickets: the hotspot edit is isolated and reviewable alone. Cost: three hand-offs for a small change;
tickets 2 and 3 could merge into one if one worker builds both.

## Needs owner decision

Nothing is open for the build: every earlier open point is a ruling now written as a requirement (malformed or
unreadable `config.ini`, R2b; non-absolute value, R2c; the ADR, R13; outer-quote stripping only, R1; keeping 1.1.0
despite the tool's warning, Verify-by 3). Two items wait for a real play session, as "Deferred to real play" above
states: the end-to-end pairing of every named save, and where the remembered folder lives and whether the watcher
could read it.

## Notes

Contract map notes: its section (4) says the remembered-folder key "is not recorded in the repo"; the checked fact in
"Goal" supersedes that, and R13 records it. The map copy in `docs/ai-dlc/contracts/save-watch-folder.md` replaces the
clone's home-folder path in its first line with a description, so the committed copy holds no machine path.
