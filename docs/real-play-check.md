# Real-play check

This check shows whether the plugin sends only the kept business actions (dropping and counting
the rest), reads ride builds from ride snapshot rows between park snapshots, and fires the save hook in a real play session.
The steps below are the permanent step list. One command prints the result.

## Before you start

The check captures into the company data set, which is scratch data until go-live. The last steps
remove the session. Use a scenario that is not a company park, so that the rehearsal data stays
clean. `make capture-data` does not start the game. It prints "Open OpenRCT2 now and play."

Clicking the new stall's price-increase button before each save puts a known confirmed action
before each save. The result command uses these price clicks to attribute each save to a
checkpoint. The plugin sends no build actions, so ride builds are read from the daily ride
snapshots instead.

## Steps

1. Close OpenRCT2.
2. Open a terminal in the repo folder on the `develop` branch.
3. Run `make capture-data DATA_SET=company`.
4. Wait until the command prints "Open OpenRCT2 now and play."
5. Start OpenRCT2.
6. Start a new scenario. Use a scenario that is not a company park.
7. Wait until the in-game date changes once, then a few seconds more. That day's ride list is read
   in those seconds, so the stall you place next is not in it.
8. Open the New Ride window. Select one food or drink stall, for example a burger bar. Stall prices
   can always be set, unlike some rides in parks that charge entry. Do not select a saved design.
9. Move the see-through stall preview across at least three tiles. Do not click.
10. Click one time to place the stall. Close the construction window. Do not build or change
    anything else.
11. Wait until the in-game date changes three more times. The next day's stats row then proves that
    the day the stall was placed in was fully recorded.
12. Open the stall's window and click its price-increase button exactly once. This is check 1.
    Change nothing else.
13. Open the Save Game As window. Save the park with the name `player-actions-check`.
14. Click the stall's price-increase button exactly once. This is check 2.
15. Open the disk menu. Select Save Game (not Save Game As).
16. Click the stall's price-increase button exactly once. This is check 3. Then quit the game. When
    the game asks to save the park, select Save. If the game does not ask, write that down.
17. Wait until the capture command prints its report.
18. Run `make real-play-check DATA_SET=company`.
19. Paste the output of steps 17 and 18, and any note from step 16, into the conversation.
20. When the director says the result is recorded, run the delete command that step 18 printed.
    It shows a plan and a confirmation phrase.
21. Run the same command again with `CONFIRM="<phrase>"`.
22. Optional: remove the save file `player-actions-check` from the game's save folder. Agents do
    not delete game files.

Step 13 comes first among the saves, so step 15 saves to the park's own file instead of opening
Save Game As. Step 13 is also a positive control, because Save Game As fires the save hook.

## What the result command prints

1. Ride builds. The count of rides that are in the end snapshot window and not in the start
   window. It passes when the count is 1 and prints both set sizes and the new ride IDs. The
   source is the daily `ride_snapshot` (one row per ride, stall and facility per game day), read
   from two windows that the `plugin_stats` rows prove complete: `work_items_skipped_total` must
   not rise after the window's snapshot, and `lines_dropped_total` and `work_items_failed_total`
   must not rise across the window. Fewer than four `park_snapshot` rows print "not enough game days" and fail; a window
   that is not proven complete prints "ride snapshot window incomplete" and fails. A ride built
   and demolished between two day starts is not seen. Repeat deliveries of one `event_id` count
   once.
2. No build actions sent. It passes when the session has no dropped-action row (the rule of
   `src/openrct2_analytics/ingest/action_names.py`: a name the plugin drops, a preview, or a
   disallowed sub-type) and the last `plugin_stats` row has both
   `game_actions_skipped_preview_total` and `game_actions_skipped_confirmed_total` above zero (the
   stall preview move and the placement produce them). It prints the dropped-action row count and
   the five skipped totals.
3. Save hook, per checkpoint. A checkpoint is a confirmed, accepted `ridesetprice` click on the
   one new ride from verdict 1 that the plugin did not issue; the first three such clicks, in
   order, are check 1, check 2 and check 3. Each save belongs to the checkpoint click before it.
   One save prints "fired". No save prints "not seen". More than one prints "unknown save type",
   because an autosave may be among them. When verdict 1 was refused or did not find exactly one
   new ride, or the session holds a number of clicks other than 3, every checkpoint prints
   "cannot classify" with the reason (the click count is printed). The save-hook verdict is pass
   when check 1's outcome is "fired", check 2 and check 3 are not both "not seen" (that case
   prints the stop line), and no checkpoint's outcome is "cannot classify"; otherwise it is FAIL.
   The project owner is asked to confirm this rule.
4. Supporting tables: rows per hook and label, the `player` values per label, and the last
   `plugin_stats` sent, dropped (`lines_dropped_total`) and skipped totals.

The command ends with the session ID and, for the company data set only, the delete command for
that session. It exits 0 when every verdict passes, 1 when a verdict fails (a session with no
action file prints every verdict with zero rows and exits 1), and 2 when it is refused. The
Makefile, not the module, refuses a `DATA_SET` exported in the shell; the module takes the data
set only from `--data-set`.
