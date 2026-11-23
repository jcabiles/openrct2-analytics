# Benchmark

**Bottom line.** `make bench` runs the built plugin headless on copies of the benchmark park and judges three 35-day
runs against the per-tick limits (10 ms worst tick, 1.25 ms mean); `make bench-sample` rebuilds the rehearsal sample.
Both run alone on the project owner's machine and never in CI. The rules below were fixed before the first run. The
recorded results are in `docs/FINDINGS.md`. `ARCHITECTURE.md` describes the rest of the system.

**Benchmark** (`make bench`, `make bench-sample`). `make bench` runs the built plugin headless on copies of the
benchmark park and judges three 35-day runs against `docs/adr/0005-plugin-per-tick-budget.md`'s limits. ADR 0041 (`docs/adr/0041-accept-a-judged-window-when-the-new-code-is-not-the-cause.md`) records the project owner's acceptance of two FAILED windows without changing ADR 0005's limits; the judge code still prints FAILED for them;
`make bench-sample` uses the same harness to rebuild the committed sample. It needs a local game install, so it never
runs in CI. Its rules were fixed before the first run, so the pass line never moves after a result is seen. The project owner accepted two FAILED windows on 2026-10-22 without moving the line (ADR 0041). The
recorded 2026-10-02 benchmark passed: worst tick 5.162 ms and highest mean 0.0286 ms per tick, against 10 ms and
1.25 ms (`docs/FINDINGS.md`, "Full capture, part 1: benchmark"). The part 2 benchmark of 2026-10-05, on the
plugin with guest capture (run B3), passed too: worst tick 4.164 ms and highest mean 0.0349 ms per tick, with the
day-start cost reduced (`docs/FINDINGS.md`, "Full capture, part 2: benchmark"). The part 3a benchmark of
2026-10-13, on the plugin that reuses one `save_written` payload, passed as well: worst tick 5.260 ms and highest
mean 0.1491 ms per tick (`docs/FINDINGS.md`, "Judged benchmark, part 3a"). Its mean per tick is about 4.3 times part
2's, but the part 3a figures were measured on a newer game build (0.5.6) than part 2's (0.5.5), so the comparison is
across builds; no cause is claimed (same row). Under `src/openrct2_analytics/ingest/`, `bench_setup.py` checks settings and
the fixture, refuses unsafe runs and creates each run's folder; `bench_run.py` runs and stops the game;
`bench_play.py` launches and stops one session; `bench_judge.py` judges a run, with the guest rules in
`bench_guests.py` and the boarding rule in `bench_boardings.py`; `bench_verdict.py` combines three runs; and
`bench_sample.py` chains three sessions into the sample. Exit codes are 0 for a passed verdict, a rebuilt sample or a passing
`--dry-run`, 1 for anything else and 2 refused.
- **Refusals** exit 2 with "Nothing was written.", in this order: `--sample` with `--any-park`; `--sample` with `--dry-run`; `OPENRCT2_BINARY`,
  `OPENRCT2_BENCH_PARK` or `OPENRCT2_GAME_PATH` missing or not naming an executable, a file or a folder; a work folder
  (`OPENRCT2_BENCH_DIR`, default `data/bench/`, a relative one taken from the repo root) that equals or overlaps the
  player's OpenRCT2 folder, or still holds an earlier run's folders or `verdict.json`; a fixture whose SHA-1 does not
  start `a65dba74` (Dusty Greens), unless `--any-park`; a binary that does not answer `--version` within 30 s; port
  8765 or 11799 busy; a newest autosave in the player's folder under 10 minutes old (it stands in for a running game,
  because `pgrep` cannot see processes inside the agent sandbox); a one-minute load average at or above 3.0 for 5
  minutes; or a failed plugin build.
- **One run** gets its own folder under the work folder: a user-data folder with the built plugin, a copy of the
  fixture and a fresh `config.ini` (`game_path`, autosave, `pause_server_if_no_clients = false`, `advertise = false`),
  plus raw and Parquet folders. Autosave is every 5 minutes for `make bench`, so the save hook runs as in play, and
  off for `make bench-sample`. A verdict run stops once the 36th `plugin_stats` line has landed (N + 1, with N = 35
  judged days); the count spans sessions, but a plugin restart makes the run invalid either way. Stop order: terminate
  the game (kill it after 30 s), wait for the listener's connection to end, then stop the listener, so no line is cut.
  A run is invalid when it has not stopped after N × 30 s + 120 s, its game exits first, its connection stays open
  after the game stops, or its conversion fails.
- **The judged window.** The session's `plugin_stats` row 1 is the warm-up and must be marked so; rows 2 to N + 1 are
  judged and later rows are not. Each judged row's `work_queue_length` describes the work queued at the callback
  before it, so the work queued at the last callback belongs to a day outside the window.
- **Action workload.** Each judged run installs an action helper in its isolated plugin folder. It issues seven
  2,400-tick bursts of plain `ridesetprice` calls (the first priced ride is set to its current price) on game days 1,
  6, 11, 16, 21, 26 and 31, starting 100 ticks after each day callback. No call carries a preview flag or a marker
  key, so the plugin keeps every call and labels it `confirmed`. Each burst has 8,576 rows per hook at one row per
  call, with a spike at tick 1,200. With `h` rows per call, each hook that has rows holds 7 × 8,576 / `h` rows in the
  judged periods (60,032 at `h` = 1). `query` holds the same count while the query subscription exists, and 0 once
  the fallback ladder removes it (`JUDGED_EXPECT_QUERY = False`). The check requires, in the judged periods, the
  expected row count in each hook; the action `ridesetprice` and a `player` value in `PLUGIN_ISSUED_PLAYER_VALUES`
  (`(0,)`, `src/openrct2_analytics/ingest/plugin_issued.py`) on every row; the label `confirmed` on every row of a
  hook that has rows; zero values in the three dropped counters and in `lines_dropped_total`; and exact agreement
  between each label's rows before the final `plugin_stats` sequence and its sent total. Missing or mismatched rows
  make the run incomplete. A dropped emitter line (`lines_dropped_total`), a partial write (`write_partial_total`), a skipped work item
  (`work_items_skipped_total`) or a nonzero dropped counter makes it void: the run is reported
  as void, its cost is not a speed verdict, and it is not repeated. A counter missing from `plugin_stats` is
  reported as missing, not as zero. The skipped counters (`game_actions_skipped_*_total`) are not checked here.
  The rows per call and whether query rows are expected in judged runs are the constants
  `JUDGED_ROWS_PER_CALL` and `JUDGED_EXPECT_QUERY` in `bench_run.py`; they were measured with an earlier helper and
  must be set from the dry run's printed values before a judged window (`h` is all action rows, both hooks, divided
  by 60,032). `make bench-sample` installs no action helper. `python -m openrct2_analytics.ingest.bench_run
  --dry-run` makes one 35-day run using the one-row-per-call schedule and prints the observed rows per call, the
  helper's player value(s), and each period's queue maximum and drop totals (even when the run has no cost). It
  exits 0 only when the run is valid and its workload check passes. Because every row is now confirmed, the next
  judged run measures a different mix from the earlier windows (ADR 0042).
- **Valid** means: one session; at least N + 1 `plugin_stats` rows; every judged row with `warmup` false, `clock`
  `performance`, `game_speed` 1 and `period_ticks` above 0; a clean `seq` audit by the converter's rule;
  `session_start` at `seq` 1; the fixture's SHA-1 unchanged; and no malformed line. **Complete** means every judged
  row has `work_queue_length` 0, every judged period has at least one `ride_snapshot` (from `period_start_ticks` up to
  `period_end_ticks`), and the session's last row reports 0 for `lines_dropped_total`, `write_partial_total` and
  `work_items_skipped_total`.
- **Guest completeness** (rules fixed before the runs, each shown to fail a planted case in
  `tests/test_bench_guests.py`). (1) No failed step or poll. (2) Every judged period ran its polls. (3) The known
  guests inside the park are within 2% of the park's own guest count. (4) Every recorded arrival and boarding became an
  event or is still pending, against the plugin's own counters. (5) At most 64 continuous items are pending at the end.
  (6) Arrivals match the change in admissions, within 10 or 10%. (7) Boardings follow the game's `total_customers`:
  (a) every period, on running totals; (b) at least 77% on car rides over a window lagged by each ride's time aboard
  (Little's law), where a car ride's span must be at least 10 game days; (c) at most 150% of those customers, and at
  most 150% plus 20 rows per ride. (8) At least one arrival joined the cohort. (9) Every cohort member has exactly one
  snapshot each game day. Refusals are reported by type, not judged, because a run can honestly have none. The 77% began
  as a provisional 90% and was re-set once, after run B2 failed only rule 7 (b): `boarding_calibration_due` is true only
  when that is the sole failure, every car ride is at least 70%, and the plugin's boarding counter equals the captured
  rows; the new value is the lowest ride ratio minus 5 points, rounded down.
- **Day-start reduction.** Run A (part 1's plugin, same harness) and run B (the finished plugin) take three runs each.
  The cost counts as reduced only when the mean of run B's `mean_period_worst_day_start_tick_ms` is below the mean of
  run A's `mean_period_worst_tick_ms` by more than run A's spread (its highest minus its lowest). "Not reduced" leaves
  the work incomplete. Dropping the boarding guest fields was allowed only after a failed verdict met the trace rule below
  (`failure_traced_to_guest_fields`); no verdict needed it.
- **Trace rule.** A failed verdict counts as traced to the five boarding guest-field reads only when all three runs
  are valid and complete, so every failure is a per-tick limit, and every failed limit is traced. Only the
  `guest_fields` step kind counts, never the `boarder_read` lookups. A worst-tick failure is traced when, over the
  failing periods of all runs (worst tick above 10 ms), `guest_fields` holds more than half of their summed
  worst-tick time (by `worst_tick_kind_ms`) and more than half of the worst tick in each of at least two of them;
  one such period alone is a stall. A mean failure is traced when each failing run's mean per tick minus its
  guest-field time per tick (summed over its judged periods) is within 1.25 ms. Source: `_traced_to_guest_fields` and
  its helpers in `src/openrct2_analytics/ingest/bench_verdict.py`; the rule was fixed before the runs.
- **Verdict.** It passes when all three runs are valid and complete and the worst run's worst tick and mean are within
  10 ms and 1.25 ms per tick, by `capture_report.py`'s cost rule (equality passes). `verdict.json` in the work folder
  records each run's reasons, cost, counters and where its worst tick fell (`worst_tick_at_ticks` minus
  `period_start_ticks`, 0 being the day callback's own tick, beside the period's `period_ticks`), the worst-tick time by source, `lines_queued_max` against the emitter's 5,000-line
  cap, refusals by type and each ride's boarding capture ratio, and the conditions:
  park label, fixture SHA-1 prefix, OpenRCT2 version and machine, never a private path. An `--any-park` verdict is
  labeled "not the benchmark park" and is never the recorded result. A verdict speaks only for headless normal speed
  on one park copy and machine.
- **Repeats.** An invalid run is repeated once, in its own folder, and the discarded attempt stays in `verdict.json`
  with its reasons. A valid run is never repeated or discarded, even when incomplete or over a limit. A failed verdict
  is recorded in `docs/FINDINGS.md`, not re-run.
- **Never touched.** In the player's OpenRCT2 folder only the newest autosave's age is read, and `--version` runs with
  a throwaway user-data folder. The fixture is only read and copied, and its SHA-1 is checked after every run.
- **Sample.** Each of the three sessions saves once through a save helper written only into its own plugin folder, and
  stops once that file keeps one size across 3 polls 200 ms apart and its `save_written` has landed. A `seq` violation
  or a malformed line fails the rebuild after the sample is written. The sample stays under 5 MB by the gate's byte sum and holds at least
  one row of each of four guest types (`tests/test_sample.py`). Method and contents:
  `data/sample/rehearsal/README.md`.
- **Emitter capture limit.** The emitter keeps at most 5,000 lines (`plugin/src/emit.ts`), so the supported capture limit is the ratio `lines_queued_max` / 5,000: a park's workload is supported while the ratio stays below 1. During a lost connection, lines build up at the day's emit rate; at the expected ceiling of 1,000 lines a game day, 5,000 lines last about five game days (about a minute of play at normal speed) before the first drop. The benchmark runs on localhost and never disconnects, so this outage case is stated, not measured (source: the part 2 benchmark spec's section "The emitter's capture limit", removed from the tree in commit 4f60210; recover it with `git fetch origin pull/51/head`, then `git show 4f60210^:docs/ai-dlc/specs/full-capture-part-2-benchmark.md`).
