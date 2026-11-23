# ADR 0048: the capture command opens the game, backs up the last recorded save, and warns before play

- Date: 2026-11-09.
- Status: Accepted 2026-11-09 (the project owner approved the safe-play spec, `docs/ai-dlc/specs/safe-play.md`). It
  amends ADR 0037's rule that only `-main` files get `start` records.

## Bottom line

A Mac app, "OpenRCT2 Enterprise", starts `make play DATA_SET=company`, which installs the plugin and then opens the
game itself, so the company park is never opened without recording by habit. After a healthy company run, each park's
last recorded save is copied into the game's save folder and into a never-overwritten archive, so recovery from an
unrecorded session is "load the backup". Before the game opens, any save file that changed while nothing was recording
is named, with the backup to load instead.

## Context

On 2026-11-09 the company park was played for about 40 minutes from the plain game icon. Nothing was recorded, because
`make capture-data` removes the plugin after every run (ADR 0009), and the manual save was overwritten. The last
recorded autosave had to be found by hand before the game's autosave rotation (ten files kept) deleted it.

## Decision

1. **The capture command opens the game.** `--open-game` (used by the new `make play` target) runs the open command
   (`open -a OpenRCT2` on macOS; `--open-game-command` replaces it in tests) right after the "Open OpenRCT2 now" line,
   when the plugin is installed, the listener is up and the save watcher has made its first scan. The game must then
   be seen running within 60 seconds; otherwise the session removes the plugin, stops the listener and exits 1 with
   "OpenRCT2 did not start; nothing was recorded. Open the launcher again." The limit runs out only while the game check
   clearly answers "not running" and no event has landed, because a check that cannot tell, or arriving events, mean
   the game may be up. After a timeout the command checks once more and, if the game is now running, prints a loud
   "running, but NOT recording" line. Without `--open-game` the wait is unbounded, as before. The open command's error
   output goes to a temporary file, not a pipe, because a program it leaves running would hold a pipe open.
2. **The launcher is a locally built AppleScript app.** `make launcher` compiles a one-line AppleScript that runs
   `open -a Terminal` on the committed `launcher/play-company.command`, whose absolute path is written into the app at
   build time. It takes the icon of the installed `OpenRCT2.app` (the default script icon when the game is not in
   `/Applications` or `~/Applications`) and is signed again after the swap. The app is built into a temporary folder
   under `~/Applications`, then replaces any older build. The
   `.command` file runs a login `zsh`, changes to the repo folder relative to its own location, stops with a message
   when `direnv` is missing or does not trust the folder, and runs `direnv exec . make play DATA_SET=company`. It holds
   no machine path.
3. **The backup runs after every check of a healthy company run.** For each park, the run's last `save_written` event
   (by `emitted_at`) that paired with exactly one file is the restore point, because the kept timeline drops events
   after each save's cut (ADR 0024). No copy is made when the run's pairing, watcher or `seq` audit failed, nor for a
   park whose chosen file, or another file paired with that park in the run, was written again later in the run, nor
   for a chosen autosave the game already deleted. The source must still match its record's size and modified time to
   the millisecond, before and after copying.
4. **Two copies, and only the command's own copies are replaced or recommended.** The archive copy,
   `<park name>-YYYY-MM-DD-HHMMSS.park` under `OPENRCT2_BACKUP_DIR/<park_id>/` (default `local/park-backups`,
   git-ignored and outside `data/company/`, which `make delete-company-data` empties), is never replaced. The
   game-folder copy, `<park name>-last-plugin-save-YYYY-MM-DD.park` in the game's `save` folder, counts as the command's
   own only while its bytes equal one of that park's archive copies. A later run the same day replaces it only then;
   otherwise (the player saved into it, or another park of the same name owns it) the copy is written beside it as
   `<park name>-last-plugin-save-YYYY-MM-DD-HHMMSS.park`, so no player file is overwritten. The two copies are
   attempted independently. Both are written under a temporary name without the `.park` suffix and then renamed (the
   archive by a hard link, which fails when the target exists). An archive folder inside a watched save folder is
   refused.
5. **Exit codes.** A run with no recorded save prints a note and exits 0. A copy that fails makes the run exit 1 with
   "The recorded data is fine; only the backup copy failed."
6. **The warning before play.** The watcher's first scan now writes a `start` record for every `.park` file, not only
   `-main` files. Right after that scan, the run judges the records and converted `save_written` events of earlier
   runs (the existing R15 check of `docs/ai-dlc/specs/save-file-watcher.md`) and prints one warning per file whose
   start record differs from its last paired write (a later write whose save event was lost included), and per dated
   copy that is no longer its park's own copy. Each names the park's newest own game-folder copy to load, or else its
   newest archive copy to copy into the save folder. A dated copy that still equals an archive copy never warns,
   because the command, not the player, replaced it. The warning never stops the run. In the report after the game
   quits, a file without the `-main` suffix gets only the "changed since its last paired write" warning; the "no
   earlier paired write" note and the lost-event warning stay `-main` only, so autosaves add no noise.

## Amendments

- ADR 0037: `start` records are written for every `.park` file in the watched folders. The save-file observation
  contract drops its "a start row's file_name ends in -main" rule (version 1.2.0).

## Consequences

- One `start` record per `.park` file per run (a few dozen lines per run with ten autosaves). The pre-play check reads
  every earlier run's records, so it slows as they grow: about 2 seconds at 365 runs of 200 files.
- Unrecorded play that writes only new files (fresh autosaves, a new save name) is not warned about; the check knows
  only files that some run recorded.
- About 170 KB per copy; one game-folder copy per park per day, plus one archive copy per park per run. Nothing deletes
  them automatically.
- The archive copy is placed by a hard link, so `OPENRCT2_BACKUP_DIR` must be on a file system that supports hard
  links (APFS does; exFAT and some network shares do not).
- `make delete-company-data PARK=<id>` does not yet remove that park's archive folder or dated copies.
- An interrupted run (exit 130) makes no copy, so the previous copy can be older than the recorded data.
- The app points at the checkout it was built from; rebuilding from another checkout replaces it.

## Rejected alternatives

- **A launcher that opens the game on a timer or by reading the command's output.** It could open the game before the
  plugin is installed, the failure being fixed; only the capture command knows when it is ready.
- **An app that scripts Terminal with Apple Events.** It needs a one-time Automation permission and fails silently
  when that is denied; `open -a Terminal` does not.
- **Copying every save during play.** Dozens of copies per session; the identity check covers the same risk.
- **Read-only backup files.** The game's own Save over a loaded backup would then fail.
- **A second, parallel check for the pre-play warning.** The R15 check already knows each file's last recorded write
  across runs; widening its input is smaller.
