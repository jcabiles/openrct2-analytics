# Rehearsal extract: three chained headless sessions on the benchmark park, plugin 0.6.0

This folder holds 9,429 events from three headless game sessions on one copy of the benchmark park, plus the
converter's `seq` audit. It is **rehearsal data, never company data**: no one played, and a script drove the game.
`make check` runs the contract check, the pytest guards in `tests/test_sample.py` and dbt on it. Two results come
from it, both **observational**, from one park copy, three headless sessions, one machine and no player:

- **Each session reports the save its predecessor wrote.** Sessions 2 and 3 each start with `loaded_save_id` and
  `loaded_save_session_id` equal to the previous session's `save_written` event, and a `loaded_save_seq_floor`
  below that event's `seq` (3,039 below 3,040, and 2,914 below 2,915).
- **The monthly statements balance exactly.** For both pairs of consecutive months, cash minus loan minus the amount booked to the
  new month (0 in all three statements) changed by exactly the later statement's 14-line total, to the tenth of a dollar. A planted +1 tenth made the check fail.

The plugin's per-tick cost is judged by `make bench` on separate runs, not on these sessions; its result is in
`docs/FINDINGS.md`, "Full capture, part 2: benchmark".

## What is in it

| File | Rows | What |
|---|---|---|
| `v1/session_start.parquet` | 3 | One `session_start` event per session, its first event (`seq` 1): park name, scenario name, plugin API level, whether the game has a window, game speed, climate, and the four `loaded_save_*` fields naming the save the session loaded (null for session 1). |
| `v1/park_snapshot.parquet` | 108 | One `park_snapshot` event per session per game day, 36 per session, with weather and temperature. |
| `v1/plugin_stats.parquet` | 108 | One `plugin_stats` event per session per game day, 36 per session: the plugin's own timing, loss counters and work-queue counters. The thirteen fields added at contract 1.3.0 are set in every row. |
| `v1/finance_month.parquet` | 3 | One `finance_month` event (monthly statement) per closed game month: March, April and May of year 9, one per session. |
| `v1/ride_snapshot.parquet` | 3,132 | One `ride_snapshot` event per ride, stall and facility per game day: 29 of them (7 rides, 8 stalls, 14 facilities) on each of 36 days per session. |
| `v1/save_written.parquet` | 3 | One `save_written` event per session, from the one save each session made. |
| `v1/guest_arrived.parquet` | 178 | One `guest_arrived` event per guest the game's guest-generation hook reported: 55, 61 and 62 per session. |
| `v1/guest_left.parquet` | 81 | One `guest_left` event per known guest that left the park, at game-day resolution: 22, 27 and 32 per session. |
| `v1/guest_refused.parquet` | 1,951 | One `guest_refused` event per ride-refusal thought newly present at a daily guest check: `bad_value` 1,025, `more_thrilling` 358, `not_while_raining` 300, `cant_afford_ride` 149, `sickening` 73, `intense` 46. |
| `v1/guest_snapshot.parquet` | 1,478 | One `guest_snapshot` event per member of the random guest sample per game day: 384, 477 and 617 per session. |
| `v1/guest_boarded.parquet` | 2,370 | One `guest_boarded` event per new boarder a seat poll found: 758, 745 and 867 per session. |
| `v1/weather_change.parquet` | 14 | One `weather_change` event per change of weather the plugin saw: 5, 6 and 3 per session. |
| `v1/game_action.parquet` | 0 | One `game_action` event per call of a game action hook. This sample holds none: plugin 0.6.0 did not record actions, and the empty file is here so the contract check finds a file for every contract. |
| `registry/v1/park_registry_2026-10-21_01.csv` | 1 | The registry delivery for this rebuild's park: company start year 2000, game-year origin 9 and `delivered_on` 2026-10-21. |
| `audit/seq_audit.parquet` | 3 | The converter's `seq` audit, one row per session; all three are clean (3,112, 2,996 and 3,321 events). |

The Parquet was converted at contract 1.7.0 from the raw files of this rebuild, which plugin 0.6.0 captured, and then migrated to contract 1.8.0 by adding five null columns to `v1/plugin_stats.parquet` (every existing column and row is unchanged). The eight `plugin_stats` columns added at contract 1.7.0 (the six `game_actions_*_total` counters and the two `action_*_ms_total` hook times) and the five added at contract 1.8.0 (`game_actions_skipped_preview_total`, `game_actions_skipped_prediction_total`, `game_actions_skipped_confirmed_total`, `game_actions_skipped_unknown_total` and `game_actions_skipped_cheat_total`) are null in all 108 rows, because plugin 0.6.0 did not send them. Twelve of the 13 ride-statistic columns of `v1/ride_snapshot.parquet` (all but `inversion_count`) are set in every row, and `inversion_count` is set in 324 of the 3,132 rows, and `new_month_booked_tenths` in `v1/finance_month.parquet` is set in all 3 statements. It is 0 in every statement, so its sum is 0 tenths: the booked-amount part of the balance check below is **not exercised** by this sample, and only the stand-in test in the repo's tests proves the fix.

## Lineage columns

Every row in `v1/` carries `_raw_file` and `_raw_line`, which say where the event came from. `_raw_file` is the
base name of the raw JSON Lines file (for example `events-2026-10-21-session-1.jsonl`); `_raw_line` is the
1-based physical line number in that file, with blank lines counted. The converter adds both; the plugin never
sends them. The raw files are not committed.

## How it was made

- **Park.** A copy of the benchmark park, Dusty Greens, fixture SHA-1 `a65dba74…`. The park file itself is never
  committed, and the fixture's SHA-1 was the same before and after every session. Every session start reports park
  name and scenario name "Dusty Greens" and climate `hotAndDry`.
- **When and where.** 2026-10-21, 12:55 to 13:20 UTC. OpenRCT2 0.5.6 (plugin API level 124), headless host,
  normal speed (the game speed was never changed), plugin 0.6.0. Apple M1, 8 cores (4 performance, 4
  efficiency), 16 GB, macOS 26.5.2.
- **Three sessions, each loading the previous session's save.** `make bench-sample` ran each session in its own
  isolated user-data folder with autosave off. A save helper, written only into that folder's plugin folder,
  saved the park once it had seen 36 day callbacks, so that save is each session's only one. The benchmark
  stopped the game once the save file had landed and its `save_written` event had arrived. Session 1 loaded the
  fixture copy; session 2 loaded a copy of session 1's save, and session 3 a copy of session 2's, so the three
  sessions form one straight game timeline from 6 March to 22 June of year 9. Each session got a new
  `session_id`, and all three share one `park_id`, because the park ID is stored in the save.
- **Session boundaries.** Each session's last day of events is created after that session's save: the save helper's
  day hook runs before the plugin's on the save tick, so `save_written` takes the lower `seq` (3,040, 2,915 and
  3,235), and that day's `plugin_stats`, `park_snapshot`, 29 ride snapshots and guest events follow it with higher
  `seq` (72, 81 and 86 events in all). The
  next session resumes from the save inside that day and sends no `park_snapshot` for it: session 1's snapshots
  run from year 9, month 0, day 7 to month 1, day 11, and session 2's from month 1, day 12 (the day after). So a
  timeline model that keeps only events before each save's cut (ADR 0006) drops one daily snapshot per session
  boundary: that last day's `park_snapshot`, `plugin_stats`, ride snapshots and guest events from the two earlier
  sessions.
- **No losses.** In every session `lines_dropped_total`, `write_partial_total` and `work_items_skipped_total`
  stayed 0, and `work_queue_length` was 0 in every row.

## Save lineage

Taken in `game_ticks_elapsed` order, session 1 reports no loaded save, because no plugin session ever saved the
fixture. Sessions 2 and 3 each report the save the session before wrote:

| Session | `loaded_save_session_id` | `loaded_save_seq_floor` | Previous session's `save_written` `seq` | Same save ID |
|---|---|---|---|---|
| 2 | session 1 | 3,039 | 3,040 | yes |
| 3 | session 2 | 2,914 | 2,915 | yes |

`loaded_save_lines_waiting` was 0 in both, so each save cut its session exactly at its `save_written` event.
`tests/test_sample.py` repeats this check, with planted controls: a session reporting an older save, another
session's ID, or a floor equal to the save's `seq` each fail it. This query, run with `duckdb` from the repo root, recomputes it:

```sql
SELECT later.session_id,
       later.loaded_save_id = save.save_id
       AND later.loaded_save_session_id = save.session_id
       AND later.loaded_save_seq_floor < save.seq AS reports_previous_save
FROM read_parquet('data/sample/rehearsal/v1/session_start.parquet') AS later
JOIN read_parquet('data/sample/rehearsal/v1/save_written.parquet') AS save
  ON save.save_id = later.loaded_save_id
ORDER BY later.game_ticks_elapsed
```

## Balance check

Two statements are consecutive when `statement_year * 8 + statement_month` rises by exactly 1 within the park,
taken in `game_ticks_elapsed` order (the game year has 8 months, so month 7 is followed by month 0 of the next
year). For each consecutive pair, (cash − loan − the amount booked to the new month) at the later statement minus the same quantity at the earlier must
equal the sum of the later statement's 14 ledger lines, exactly, in tenths of a dollar. The check fails if any
month has two statements, or if it finds no consecutive pair, because it relies on this extract being one straight
game timeline.

| From | To | Change in cash − loan (tenths) | Booked to the new month at the later statement (tenths) | Later statement's 14 lines (tenths) | Exact |
|---|---|---|---|---|---|
| March, year 9 (session 1) | April, year 9 (session 2) | 66,499 | 0 | 66,499 | yes |
| April, year 9 (session 2) | May, year 9 (session 3) | 33,937 | 0 | 33,937 | yes |

**Pass**: 2 pairs, 0 mismatches, no repeated month. In each session the statement's `cash_tenths` equalled that
day's `park_snapshot` cash, and `finance_months_unread_total` stayed 0 in every `plugin_stats` row. The bank loan
was 0 in all three statements, and seven lines (`ride_construction`, `land_purchase`, `landscaping`,
`park_entrance_tickets`, `marketing`, `research`, `interest`) were 0 in every statement, so real data does not yet
exercise the loan side of the check, the booked amount (0 tenths in all three statements) or those lines; the planted controls cover the check's arithmetic for all of
them. `tests/test_sample.py` repeats the check on these files, with a planted tenth on each of the 14 lines and on
the loan, and a repeated-month case.

## Plugin timing in these sessions

These sessions are not a cost verdict: autosave was off, and `make bench` judges its own runs. Their
`plugin_stats` rows are kept so the timing fields stay exercised. The plugin's tick hook runs on every tick, so
`callbacks` in each period is `period_ticks` plus a few (the day callback and the reconnect interval); a check of
the form `callbacks >= 1` holds trivially and says nothing, so none is made.

The tick cost measured on the rebuild (headless, autosave off, three chained sessions, not a cost verdict), outside the warm-up rows, against ADR 0005's limits of 10 ms for the worst tick and 1.25 ms for the mean per tick:

| Session | Worst tick (ms) | Mean per tick (ms) |
|---|---|---|
| 1 (`s1792587321039-i0ssmf`) | 4.464 | 0.1254 |
| 2 (`s1792587801446-3lzf29`) | 4.758 | 0.0967 |
| 3 (`s1792588287868-xzldcs`) | 4.269 | 0.1173 |

All three are under both limits. The mean is the sum of `work_ms_total` over the sum of `period_ticks`.

## How to rebuild it

From the repo root, with `OPENRCT2_BENCH_PARK` (the benchmark park file) and `OPENRCT2_GAME_PATH` (the
RollerCoaster Tycoon 2 data folder) set, and `OPENRCT2_BINARY` too where the game is not at the standard macOS
location, run `make bench-sample`. It takes about 25 minutes. It refuses to start, before writing anything, when a
setting is missing, when the park is not the benchmark park, when port 8765 or 11799 is in use, when the newest
autosave in the player's OpenRCT2 folder is under 10 minutes old, when the one-minute load average stays at or
above 3.0 for 5 minutes, or when the work folder (`OPENRCT2_BENCH_DIR`, by default the git-ignored `data/bench/`)
still holds session folders from an earlier rebuild. It converts the three sessions' raw JSON Lines into this
folder, replacing only `v1/` and `audit/`, so this README stays. Then run
`uv run python -m openrct2_analytics.ingest.contracts --data-root data/sample/rehearsal` and `make check`.

The raw JSON Lines stay in the work folder and are never committed; only this converted extract is.

`registry/v1/` holds a committed copy of the park registry feed for this rehearsal sample, with data set `rehearsal`. The committed sample is a rebuildable test fixture, so a rebuild with `make bench-sample` replaces the sample's registry delivery with one dated file, `park_registry_<YYYY-MM-DD>_01.csv`, for the new park only: its park ID, its earliest game year, `company_start_year` 2000, `data_set` `rehearsal`, and `delivered_on` equal to the file name's date. The earlier sample park is not kept registered, because a registered park with no events would hold a company year that can never close. The 2026-10-21 rebuild replaced the 2026-10-10 file with `park_registry_2026-10-21_01.csv`. The append-only rule still binds the real `data/<set>/registry/` feeds; it does not apply to this fixture.
