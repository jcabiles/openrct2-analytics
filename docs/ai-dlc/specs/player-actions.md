# Spec: player-actions capture (full capture part 3b)

status: approved (Gate 2, 2026-10-20).

Written from the project owner's Gate 1 rulings of
2026-10-19 (the twelve preflight answers for this item, cited as "G1-1" to "G1-12") and the 2026-10-13 rulings
quoted in the roadmap. "Review PA-01" and similar cite a row of the review ledger,
`docs/ai-dlc/ledger/player-actions.md`. Contract map: `docs/ai-dlc/contracts/player-actions.md`.

## Bottom line

The plugin starts recording every game action, including see-through build previews and the game's client-side
predictions, as one new event type, `game_action`. Each row carries the raw preview and prediction signals, a label
the plugin derives from them, the action's arguments as JSON text, ten flat key columns, and the game date and tick
at which the hook fired. Previews and predictions are sent tagged and never counted as player actions; dbt tests that
are proven to go red enforce it. A staging model and a small labeling model ship in the same change. All contracts
move to 1.7.0.

The item is done when a judged `make bench` passes on one fixed, reproducible action workload that the judge checks
was really delivered, and when the project owner's short real-play check prints exactly one confirmed ride build and
says whether the save hook fired for plain Save Game and the quit save.

Four rulings of 2026-10-19 shape the item (section "Rulings"): previews are never discarded, so a speed failure
after the last fallback step stops the item for a redesign; per-day action counts moved to the roadmap Backlog; the
real-play step list names no game setting; and the sample re-convert uses a copy only.

## Goal

Capture what the player does before real company play starts, because actions cannot be recovered later.

- **Why now.** "Only work that records data the game cannot give back later must come before play" (roadmap :351;
  Play first, roadmap :10). This item is the first step of that block (roadmap :359).
- **Done line** (roadmap :359, verbatim): "Done when player actions and labeled previews are captured, make bench
  passes on the full workload, the real-play check passes, and one dragged preview plus one placed ride yields exactly
  one confirmed ride-build event. The real-play check also records whether the save hook fires for plain Save Game
  and for the save offered on quit; if it does not fire for either, stop and redesign the save-file watcher before
  the clean start."
- **Trace to the two-park goal** (review PA-16). The v1 goal shows two parks on one company calendar through the whole
  stack (roadmap :4-6). Each `game_action` row carries its park's `park_id` (envelope) and its own game date (R6), so
  the later company-calendar model of roadmap item 3c, which maps a park's game day to a company date (roadmap :126),
  can place each action on the company calendar. This item builds neither that model nor action marts.
- **Showcase link.** Previews and predictions are about 99% of schema 0 action events (216,921 of 219,413,
  `docs/FINDINGS.md:208`), so the labeled preview stream is the project's clearest source-caused cleaning rule:
  recorded raw, removed downstream with a test (ADR 0006).

## Requirements

Each requirement names its source. "Unverified" marks a game fact no record confirms, with the probe that settles it.
"Schema 0" is the spike capture of 2026-09-26 and 2026-09-27 (OpenRCT2 0.5.5, `action.execute` only), kept in the
project folder's notes, not in this repo.

### The event

- **R1. One event type, `game_action`.** One row per call of a subscribed action hook. The game's action name (for
  example `ridecreate`, `trackplace`, `ridesetprice`) is the column `action`, the kind marts split by; G1-2's derived
  label is the column `action_label`. Source: G1-1. Both readings of G1-1's "kind label" are columns, so a different
  reading costs only a rename.
- **R2. Both hooks, one column.** The plugin subscribes to `action.query` (the game asks whether an action would
  succeed) and `action.execute` (the game runs it). The column `hook` holds `query` or `execute`. Source: G1-4.
  Unverified: how many rows one `executeAction` call gives (probe: the dry run of R21 counts rows per call, `h`).
  The dry run is a new `bench_run --dry-run` option: one 35-day run with the helper that prints rows per call, the
  helper's `player` value, marker survival, `lines_queued_max` and dropped lines; the wiring ticket T7 (benchmark
  helper, workload check and wiring) builds it. Amendment 2026-10-22: the dry run measured `h`; see the R21 amendment.
- **R3. Raw signals and one derived label.** `args_flags`, the integer `args.flags` as received (null when absent or
  not a number; schema 0 shows negative values such as -2147483648, so the bit test is a 32-bit `&`);
  `is_client_only`, the hook's boolean `isClientOnly`; `action_label`: `preview` when `args_flags & 64` is non-zero,
  else `prediction` when `is_client_only` is true, else `confirmed`. Bit 64 wins when both are set: the facts page
  names bit 64 as the preview signal (`docs/architecture/openrct2-facts.md:70`), and in schema 0 every bit-64 row
  (215,925) is also client-only, so the other order would leave no previews; the 996 client-only rows without bit 64
  are the predictions, and 215,925 + 996 is the FINDINGS figure of 216,921. Both raw signals stay. Source: G1-2.
  Unverified on 0.5.6: bit 64 in real play (probe: the real-play check, verdict 2). The build records the schema 0
  split in `docs/FINDINGS.md` (R31).
- **R4. Who issued the action, raw.** Column `player`, the hook's `player` value, unchanged. Schema 0 shows -1 on
  all 219,413 rows, all from the human player. The plugin does not judge who issued an action. Source: G1-7.
  Column `type` (integer, null when absent), the hook's `type` value as received; schema 0 holds 2 and 6. It ships
  because raw values cannot be recovered later.
- **R5. Arguments and result.** `args_json`, the hook's `args` as JSON text. Ten flat columns, each null when absent:
  seven from the arguments, `args_ride`, `args_ride_type`, `args_ride_object`, `args_price_tenths` (tenths of a
  dollar, the game's money unit), `args_x`, `args_y`, `args_z` (the action's own coordinate units); three from the
  result, `result_error`, `result_cost_tenths` (tenths of a dollar), `result_ride` (the ride a `ridecreate` returns,
  `RideCreateActionResult.ride`). `result_error` is stored as received: schema 0 shows `error: 0` on all 2,492
  confirmed rows, and the type definitions make it optional, so consumers read "no error" as
  `coalesce(result_error, 0) = 0` (review PA-R9). Source: G1-3. Unverified: that prices and costs are in tenths
  (probe: the dry run reads the helper's `ridesetprice` price against `ride.price`).
- **R6. The hook's own clock** (review PA-02). `action_at_ticks` (game ticks), `action_game_year`,
  `action_game_month` and `action_game_day`, read from `date` inside the hook. The envelope's game date and
  `game_ticks_elapsed` are stamped when the event is built (`plugin/src/emit.ts:52-55`) and can fall on a later day.
  Every consumer of an action's date uses the `action_` columns; the envelope date is the send date. Source: CLAUDE.md
  rule 3; precedent `generated_at_ticks` (`contracts/guest_arrived.odcs.yaml:42-50`).
- **R7. Envelope.** Every `game_action` carries the full envelope stamped by `plugin/src/emit.ts`. Source: rule 1.

### Capture path in the plugin

- **R8. The hook copies values; the queue sends** (review PA-05). Each hook callback writes primitive values into
  preallocated arrays and returns: hook name, `player`, `type`, `action`, `isClientOnly`, `args_flags`, the seven
  argument columns, the three result columns, R6's four clock values, the `args_json` text (written in the hook) and
  one creation order from the shared counter. Nothing keeps a reference to the hook's `args` or `result`. A
  continuous work-queue task sends items oldest first within the queue's allowance (`plugin/src/work.ts:16`); a send
  step only refills the payload object and calls `emit`. Gain: no assumption that the game leaves hook objects
  unchanged. Cost: one string per hook call in the hook. Source: G1-5; pattern `plugin/src/guests.ts:232-239`.
- **R9. Hook order holds through a save** (review PA-01). `onSave` (`plugin/src/main.ts:70-75`) first drains the
  action buffer, sending every buffered item in creation order, then reads the seq floor and waiting count and emits
  `save_written`. So every action hooked before the save takes a lower `seq` than `save_written`, and the floor plus
  waiting count covers it. Gain: save lineage cuts stay right. Cost: a save tick also sends the buffer (normally a
  few items, at most 2,048); its time is recorded as `action` steps. Buffered guest arrivals keep today's behaviour
  (out of scope).
- **R10. Overflow is counted, per label.** The buffer holds 2,048 items, set once per session (15 of the busiest
  recorded 131-action ticks). A hook call that finds it full drops the item and adds one to its label's dropped
  total. A line the emitter drops at its 5,000-line bound (`plugin/src/emit.ts:10,65-69`) counts in the existing
  `lines_dropped_total`, as for every type. Source: G1-5; `.claude/rules/plugin.md`.
- **R11. Running totals on `plugin_stats`.** Six optional integers, session running totals:
  `game_actions_sent_{preview,prediction,confirmed}_total` (items handed to `emit`) and
  `game_actions_dropped_{preview,prediction,confirmed}_total` (buffer drops only; nothing is ever discarded on purpose,
  ruling 1). Source: G1-6; 2026-10-13 ruling ("dropped and sent counts are flat `plugin_stats` fields"). Per-day
  numbers are out of scope (ruling 2).
- **R12. Each hook's cost is measured** (review PA-09). `noteTickPart` (`plugin/src/work.ts:208-210`) takes
  `"weather" | "action_query" | "action_execute"` and adds to that part's index; today it always adds to
  `WEATHER_PART`. `TICK_PARTS` gains `action_query` and `action_execute` (tick parts, never step kinds) and `StepKind`
  gains `action` (the send step). `plugin_stats` gains `action_query_ms_total` and `action_execute_ms_total`, hook time
  in milliseconds over the same period as `work_ms_total`. Gain: one window gives each hook's share of the worst tick
  and of the mean, which R21 needs. Cost: two fields, three tick parts, a few lines in `work.ts` (364 lines).
- **R13. No new allocation per tick** beyond R8's JSON string. Arrays and the payload object are created once per
  session; the payload is refilled on every send (CONVENTIONS.md:125). Source: rule 8.
- **R14. Plugin version.** `PLUGIN_VERSION` (`plugin/src/main.ts:15`) is set to `"0.7.0"`; the cash fix (branch
  `feat/month-start-cash`) moves it to `"0.6.0"` first. The pins in `plugin/test/plugin.test.mjs` and `finance-session.test.mjs` follow.

### Contracts and sample

- **R15. Contract 1.7.0** (review PA-14). Start condition: the branch builds on the cash fix's pushed head (or on
  `origin/develop` once the cash fix has merged); first check all 13 contracts and the staging pins read 1.6.0, then bump to 1.7.0. Every contract, 14 with the new
  `contracts/game_action.odcs.yaml`, moves to 1.7.0; the envelope's type list (`contracts/envelope.odcs.yaml:31`)
  gains `game_action`; `plugin_stats` gains R11's and R12's fields, each "absent in events from plugins before" the
  R14 version. `contracts/reference/park_registry.odcs.yaml` keeps its own version. Source: G1-12; ADR 0007.
- **R16. Zero-row committed sample** (review PA-15). `data/sample/rehearsal/v1/game_action.parquet` exists with 0
  rows; the other files are re-converted under 1.7.0 from the preserved raw copy of the 2026-10-21 sessions, so the
  new `plugin_stats` columns are null and older columns unchanged (`data/sample/rehearsal/README.md:36-38`). The
  contract check builds a view per contract and fails without its file (`contracts.py:193-197`), and its field tests
  are not shown to accept a missing optional column, so re-converting is the only method. `tests/test_sample.py`
  (stem list :201-214) gains `game_action`; the README gains a row and one sentence. Source: G1-12; 2026-10-13
  ruling ("a zero-row committed sample covers the action events").

### dbt

- **R17. Staging, in this item.** `models/staging/stg_game_action.sql` and `.yml`, copying `stg_save_written.sql`:
  rename, cast, first-received dedupe on `event_id`, and `tenths_to_usd` on the two `_tenths` columns; nothing else
  (CONVENTIONS.md judgment item 11). The YAML states the grain, `not_null` and `unique` on `event_id`, and
  `meta.contract_version: 1.7.0`. `stg_envelope.sql`, its fixture and
  `tests/dbt/assert_stg_envelope_keeps_every_delivery.sql` gain the type; every event-contract staging YAML moves to
  1.7.0; `_sources.yml` is regenerated; `fct_cleaning_rule_count.sql` gains a `stg_game_action` block, because the
  dedupe is a cleaning filter `scripts/check_cleaning_rule_counts.py` requires a row for. Source: G1-8; ADR 0022.
- **R18. Labeled in dbt, in an intermediate model** (reviews PA-03, PA-R6). `int_game_actions__labeled`, one row per
  staged `game_action`, adds three columns. `is_plugin_issued` is true when `player` is in the dbt variable
  `plugin_issued_player_values` (`[0]` from the dry run, see R19; an empty list would compile to false) or `args_json` carries the key
  `analytics_issued_by`. `is_player_action` is true only when `hook` = `execute`, `action_label` = `confirmed` and
  `is_plugin_issued` is false; a query only asks, so query rows never count. `is_refused` is
  `coalesce(result_error, 0) <> 0`: refused attempts count as player actions (the player did act) and consumers that
  want successes filter on it. YAML: `rows_on_sample: 0`; the model joins CONVENTIONS.md row 118's list and the
  expected-row table (`docs/ai-dlc/reports/dbt-design--findings.md`, section 6.2) at 0. Gain over labeling in
  staging: staging stays rename, cast and dedupe. Cost: one model, its YAML and a row-count entry. Source: G1-2, G1-7.
- **R19. Provenance is settled before merge** (reviews PA-03, PA-R6). The benchmark helper (R21) sets
  `analytics_issued_by: "bench-helper"` in the arguments of one confirmed call per burst. The dry run reads both
  signals: whether that key survives into `args_json`, and the helper's `player` value. If `player` differs from -1
  (the human value in schema 0), the build sets `plugin_issued_player_values` to it in `dbt_project.yml`. If the key
  survives, the key rule stands and any future action-issuing plugin of this project sets it. If neither holds, the
  build stops before the PR (conditional stop C2), because G1-7 then cannot hold for plugin-issued actions.
  Amendment 2026-10-22, from the benchmark dry run: the key does not survive; it reached 0 of the 14 confirmed helper
  rows, and the raw capture holds no occurrence, so it is lost before the plugin reads the action's arguments. The
  player signal holds on the benchmark: confirmed helper rows carry `player` 0, so `plugin_issued_player_values` is
  `[0]` and C2 did not fire. Player 0 is most likely the host's network player number, because the benchmark runs the
  game as a headless network host, so the rule is proven only on the benchmark. A human hosting a multiplayer server
  would carry 0 and be dropped, and a plugin issuing non-preview actions in single-player would likely carry -1 and
  count; the real-play check's "Distinct player values per label" line is to confirm the human value. This replaces the sentence
  above that any future action-issuing plugin of this project sets the key, because the key does not work on this
  build. The model's key rule stays but is inert on this build.
- **R20. Downstream tests that can fail** (review PA-R7). `tests/dbt/assert_previews_never_player_actions.sql`
  returns rows of `int_game_actions__labeled` with `is_player_action` true and any raw signal against it:
  `args_flags & 64` non-zero, `is_client_only` true, `hook` <> `execute`, or `is_plugin_issued` true; it never
  reads `action_label`, so it checks the label rule independently. `tests/dbt/assert_game_action_label_matches_flags.sql`
  returns staged rows whose `action_label` disagrees with R3 applied to the raw columns. Both at error severity.
  `tests/test_dbt_player_actions.py`, in the style of `tests/test_dbt_missing_day.py`, copies the sample to a
  temporary dbt project, plants rows and asserts: a bit-64 row labeled `confirmed` makes both tests fail; a
  client-only row labeled `confirmed` makes both fail; correct rows of each label pass. A dbt unit test on the
  intermediate model covers one row per label, a query row, a refused row, a row whose `player` is in an overridden
  `plugin_issued_player_values`, a row with the marker key, and rows of two `park_id`s that keep their own park
  (review PA-R13). Source: G1-2; rule 4; CONVENTIONS.md:118 ("a test on an empty table proves nothing").

### Benchmark

- **R21. One reproducible helper workload** (reviews PA-06, PA-R1, PA-R3, PA-R4). In every judged and dry
  `make bench` run, and never in `make bench-sample`, the harness writes an action helper plugin into the run's own
  plugin folder beside the save helper's slot (`bench_setup.py:42, 362-363`). The helper counts `interval.day`
  callbacks from its first one (day 1) and runs one burst on days 1, 6, 11, 16, 21, 26 and 31 (7 bursts per run). A
  burst starts on the 100th `interval.tick` after that day's callback and lasts 2,400 ticks (one real minute at 40
  ticks a second). On burst tick `t` (0 to 2,399) it calls `context.executeAction("ridesetprice", ...)` on the first
  ride in `map.rides` with a non-empty price list, at its current primary price, `c(t)` times: `c(1200)` = `S`, and
  for every other tick `c(t)` = floor((u+1)·`N`/2,399) − floor(u·`N`/2,399), where `u` = `t` for `t` < 1,200 and
  `t` − 1 after. The first call of each burst omits flag 64 and carries R19's marker (one confirmed call); every
  other call sets `flags: 64`. Rows per call `h` (R2) fix the constants so that rows, not calls, match the busiest
  recorded minute, 8,576 rows with 131 in one tick (`docs/FINDINGS.md:202-208`; schema 0 recorded only
  `action.execute`): for `h` = 1, `S` = 131 and `N` = 8,445 (3 or 4 calls a tick, 8,576 calls a burst); for `h` = 2,
  `S` = 66 and `N` = 4,222 (1 or 2 calls a tick, 4,288 calls a burst; the spike is 66 × 2 = 132 rows, one above the
  recorded 131, because `S` is a whole number of calls). The dry run uses `h` = 1 and measures `h`.
  Amendment 2026-10-22, from the benchmark dry run: rows per call is per path, 1 per preview call (the execute hook
  only) and 2 per non-preview call (execute and query). The judged runs use the `h` = 1 constants (`S` = 131,
  `N` = 8,445), which match the recorded busiest minute on the execute hook; the 7 non-preview calls add 7 query rows.
  A game day is about 529 ticks (`docs/FINDINGS.md:97`), so the spike falls about 240 ticks after the third day
  callback of a burst, never on a day-start tick; each burst crosses about four day-start ticks at 3 or 4 calls, as
  a minute of real dragging would; the last burst ends about 35.7 days in, before the stop row (day 36). Gain: every
  judged period is reproducible and the helper text can copy these numbers. Cost: about 60,000 calls per run; a
  price set may cost less to execute than a real track preview, and headless hooks fire inside the helper's tick
  callback, while real-play previews may fire between ticks (the FINDINGS row says so). Unverified: that `flags: 64`
  reaches `args` (probe: dry run), and whether the action runs on the calling tick (probe: dry run, `action_at_ticks`).
- **R22. The judge checks the workload was delivered** (reviews PA-07, PA-08). A new check in
  `src/openrct2_analytics/ingest/bench_actions.py` (beside the helper text; `bench_judge.py` is 423 lines) adds
  completion reasons to each run, so `bench_verdict` fails the verdict unchanged (`bench_verdict.py:125, 191-192`).
  A run is complete only when, in its judged periods: `game_action` rows per hook equal 7 × calls per burst for
  `execute` (and the same for `query` when `h` = 2, until R25 removes the query subscription, after which the query
  clause no longer applies); helper rows carry the label the dry run recorded (`preview`
  when flag 64 arrives, else `confirmed`) and the 7 marker calls are `confirmed`; every buffer-dropped total is 0;
  and, per label, the rows with `seq` below the last `plugin_stats` row's `seq` equal that row's sent total. That
  last identity is exact because `emit` keeps queue order (`emit.ts:63, 92`) and the judge already requires zero
  emitter drops; no mixed loss is split across labels. Conversion without schema errors is already required
  (`bench_run.py:105-108`).
  Amendment 2026-10-22, from the benchmark dry run: the judge identifies the 7 marker calls as the helper's calls
  without bit 64, because the marker key is lost. It requires exactly 7 per hook, all labeled `confirmed`. While the
  query subscription exists, `query` rows must equal those 7 non-preview calls, not a count derived from `h`. The
  judge requires seven confirmed marker rows in total, not one per burst; it does not check position within a burst
  (a gap that predates this change and is accepted). Every judged row must be a `ridesetprice`, and every row
  without flag 64 must carry a player in `PLUGIN_ISSUED_PLAYER_VALUES` (`(0,)`, `plugin_issued.py`). Without flag 64 the
  run cannot be judged: the "else `confirmed`" branch above is gone, the judge refuses the expected label
  `confirmed`, and a dry run that prints "confirmed" for the helper's non-marker label is a stop (C2). `h` is read
  from the dry run as all action rows, both hooks, divided by 60,032 (7 bursts of 8,576 rows), rounded (60,039 / 60,032 = 1.00012 reads as 1). Everything else in R22 holds.
- **R23. Dropped lines void a run** (review PA-R2). The judge marks a run incomplete when the last `plugin_stats`
  row shows any `lines_dropped_total`, `write_partial_total` or `work_items_skipped_total`
  (`bench_judge.py:266-267, 302-306`), and the verdict fails (`bench_verdict.py:125`). This spec keeps that rule. Such
  a run is void, not a speed failure: R25's ladder never steps on it; a void judged run is reported and stops the
  build (C3). The busiest minute already passes the 5,000-line bound and drained only because the queue kept up
  (`docs/FINDINGS.md:205-207`); both hooks can double the rows. So the dry run prints, per period, `lines_queued_max`
  (`contracts/plugin_stats.odcs.yaml:223`), `lines_dropped_total` and the buffer-dropped totals before any judged
  window is spent; any drop there is conditional stop C3.
- **R24. Pass rule** (the judge's rule; see the 2026-10-22 amendment under R25 for the project owner's acceptance of two FAILED windows). A judged window passes when `verdict.json` has `passed` true: three valid, complete runs
  (R22 and R23 included), worst run within 10 ms worst tick and 1.25 ms mean per tick (ADR 0005), fixture SHA-1
  unchanged, plugin built from a clean code commit. Hook time counts toward a tick, because the timer buckets all
  plugin time by `date.ticksElapsed` (`plugin/src/timing.ts:93-95, 121-122`), including hook calls outside the
  queue's 4 ms throttle (`work.ts:3-5, 271-284`).
- **R25. Fallback ladder with a noise rule** (reviews PA-10, PA-R4, PA-R5). The same plugin code ran 11.250 ms and
  9.640 ms on consecutive days (`docs/FINDINGS.md:103-104`), so: a window that fails a per-tick limit is re-run once
  on the same build. If the re-run fails, take its worst tick's `worst_tick_kind_ms` and the excess `E` over 10 ms
  (for the mean: the per-tick excess over 1.25 ms against `action_*_ms_total` per tick). Let `Q` be the
  `action_query` part and `A` the `action_execute` plus `action` parts. If `Q` + `A` < `E`, the actions do not
  explain the failure: no feature is removed (conditional stop C4). If `Q` ≥ `E`, the query subscription is removed
  (G1-4), `JUDGED_EXPECT_QUERY` in `bench_run.py` is set to `False` so R22's query clause no longer applies, and a
  new window runs. The burst constants already use `h` = 1 (R21's row target), so there is nothing to re-derive. Otherwise, or if the window after the query drop fails the same test, the ladder ends with no
  discard path (R26): the item stops and reports the windows' numbers, `Q`, `A` and `E` (conditional stop C4). At most three judged
  windows (first, re-run, after the query drop), each about 25 minutes plus a dry run per changed build.
  Amendment 2026-10-22, from the judged windows (build `16f7e91`): R25's ladder ran as written and ended at conditional
  stop C4. Window 1: verdict FAILED, "worst tick 89.30599987506866 ms is over the 10.0 ms limit" (run 2, tick 209 of a
  529-tick period); that tick was 88.976 ms in the line-sending step, 0.187 ms in the action send step and 0.093 ms in
  the execute hook, with no query part. Window 2, the re-run on the same build: FAILED, "worst tick 17.932000041007996 ms
  is over the 10.0 ms limit" (run 3, tick 400 of 528): line 17.619 ms, action 0.141 ms, execute 0.102 ms. The runs' means
  were 0.695, 0.753 and 0.780 ms in window 1 and 0.522, 0.368 and 0.481 ms in window 2, all under 1.25 ms; all six runs
  were valid and complete, with no dropped line and nothing discarded. The test gave `Q` = 0 in both, `A` = 0.280 and
  0.243 ms, and `E` = 79.306 and 7.932 ms, so `Q` + `A` < `E`: no query drop and no third window (C4). Both verdicts stay
  FAILED. The project owner answered in chat on 2026-10-22: "Just pass anyway. I'm okay with this." The project owner
  accepted both windows because the excess was the plugin's existing line-sending step and the new action code's share
  was 0.24 ms (0.28 ms in window 1), with every mean under 1.25 ms. ADR 0041 (`docs/adr/0041-accept-a-judged-window-when-the-new-code-is-not-the-cause.md`) records the acceptance of these two windows only and does not amend ADR 0005; any standing rule for later windows is a proposal awaiting the project owner's decision. The judge code (`bench_verdict.py`) is unchanged: a window like these still prints FAILED. Previews were never discarded (R26). Observational: one benchmark park copy, one machine, headless, no
  player; a read-only review agent ran on the machine during window 2. The FINDINGS rows hold R27's fields.
- **R26. No discard path** (superseded by ADR 0042, `docs/adr/0042-plugin-sends-only-business-actions.md`, which has the plugin drop previews and other non-business actions by design) (ruling 1, which replaces G1-9's discard fallback). The plugin never discards previews on
  purpose, and no constant, switch or step in the ladder does. A failure after the last ladder rung stops the item and
  reports the numbers for a redesign. Gain: the done line and ADR 0025 stay true, and no capture loses previews
  without the project owner seeing the numbers. Cost: an unattended build may halt, and real play waits for a ruling
  (about one day); the replay's 6.011 ms worst tick (`docs/FINDINGS.md:202-203`) makes it unlikely.
- **R27. Records.** `docs/FINDINGS.md` gains one row per judged window in part 3a's row shape (`docs/FINDINGS.md:99`)
  plus: `h`, each hook's share of the worst tick and of the mean, the worst tick's offset in its period
  (`bench_judge.py:54-56`; 0 is the day-start tick), rows per hook and label, per-label sent and dropped totals, the
  helper's `player` value and marker result, and "observational, one benchmark park copy, one machine, headless, no
  player; hooks fire inside a plugin's tick callback". Source: rule 7.

### Decision record and the real-play check

- **R28. ADR 0025.** `docs/adr/0025-previews-sent-tagged.md`: "previews are sent tagged, never counted as player
  actions"; it supersedes ADR 0006's preview row and replaces ADR 0006's "daily count per action type" promise
  (`docs/adr/0006-plugin-records-facts-dbt-decides-validity.md:44`) with per-label session totals; it records R19's
  provenance outcome. ADR 0006 gains a "Superseded in part by ADR 0025" line. Gain: raw captures keep every preview.
  Cost: previews and predictions were 74% of the old capture's bytes (roadmap :105). The ADR says previews are sent
  tagged and records that no discard path exists (ruling 1). Source: G1-10.
- **R29. Real-play step list** under "Real-play check", in Standard Technical English (short sentences, one
  instruction per step), committed permanently as `docs/real-play-check.md`; it names no game setting (ruling 3).
  Source: G1-11; roadmap :360.
- **R30. Result command.** `make real-play-check DATA_SET=company`, backed by
  `python -m openrct2_analytics.ingest.real_play_check`, reads the converted Parquet of the latest session (or
  `SESSION=<id>`), prints the verdicts under "What the result command prints", the session ID and the delete command
  for it. Exit codes: 0 pass, 1 a verdict failed, 2 refused (no `DATA_SET` on the command line, an exported one, or no
  session), 130 interrupted. Source: G1-11.
- **R31. Real-play records.** `docs/FINDINGS.md` gains a "Real-play check, part 3b" row with the verdicts, the
  `player` values seen and "observational, one park, one player"; `docs/architecture/openrct2-facts.md:43` states
  what was seen for plain Save Game and the quit save, and `:70` whether bit 64 held on 0.5.6. If the save hook fired
  for neither, the item stops for the watcher redesign (roadmap :359). The build also records the schema 0 split in
  `docs/FINDINGS.md`: 215,925 rows with the preview bit (all client-only), 996 client-only without it, 2,492 neither,
  219,413 in total, with how it is re-derived (count rows by `args.flags & 64` and `isClientOnly` over the preserved
  schema 0 capture), and replaces the contract map's line "`isClientOnly` as prediction is not confirmed in the repo".

## Real-play check

The project owner plays this once, after the item is merged into `develop` and the judged windows were accepted (ADR 0041). It captures
into the company data set, which is scratch until go-live (ADR 0033), and the last steps remove the session. A new
non-company scenario keeps the rehearsal data the v1 site reads clean. `make capture-data` does not start the game:
it prints "Open OpenRCT2 now and play." (`capture_session.py:234-238`). Renaming the ride before each save puts a
known confirmed action before each save, so the command attributes saves by checkpoint, not by position (review
PA-12). The steps name no game setting; "company play" in the roadmap names how the project owner plays, not a
setting (ruling 3).

### Steps (Standard Technical English)

1. Close OpenRCT2.
2. Open a terminal in the repo folder on the `develop` branch.
3. Run `make capture-data DATA_SET=company`.
4. Wait until the command prints "Open OpenRCT2 now and play."
5. Start OpenRCT2.
6. Start a new scenario. Use a scenario that is not a company park.
7. Open the New Ride window. Select one flat ride, for example a merry-go-round. Do not select a saved design.
8. Move the see-through ride preview across at least three tiles. Do not click.
9. Click one time to place the ride.
10. Close the construction window. Do not build or change anything else.
11. Open the ride's window. Rename the ride to `check 1`.
12. Open the Save Game As window. Save the park with the name `player-actions-check`.
13. Rename the ride to `check 2`.
14. Open the disk menu. Select Save Game (not Save Game As).
15. Rename the ride to `check 3`.
16. Quit the game. When the game asks to save the park, select Save. If the game does not ask, write that down.
17. Wait until the capture command prints its report.
18. Run `make real-play-check DATA_SET=company`.
19. Paste the output of steps 17 and 18, and any note from step 16, into the conversation.
20. When the director says the result is recorded, run the delete command that step 18 printed. It shows a plan
    and a confirmation phrase.
21. Run the same command again with `CONFIRM="<phrase>"`.
22. Optional: remove the save file `player-actions-check` from the game's save folder. Agents do not delete game
    files.

Step 12 comes first among the saves, so step 14 saves to the park's own file instead of opening Save Game As
(`docs/architecture/openrct2-facts.md:42`); it is also a positive control, since Save Game As fires the save hook
(`:43`).

### What the result command prints

1. **Ride builds: `<n>` (pass when 1).** Confirmed `execute` `ridecreate` rows with `coalesce(result_error, 0) = 0`
   whose `result_ride` has no later confirmed `ridedemolish` with that `args_ride`. Schema 0 shows the game issues
   `ridecreate` when a ride is chosen and `ridedemolish` when the window closes unused, and every placed flat ride
   there reads `ridecreate` then `trackplace`; this verdict counts kept rides. The confirmed actions in `seq` order
   (`action`, `args_ride`, `result_ride`) print beneath it, with the `trackplace` count, as the probe of the
   flat-ride trace (review PA-12). Collapsing repeated copies is roadmap item 3b-2's work.
2. **Previews tagged: pass or fail.** Pass when the session has at least one `trackplace` row labeled `preview` and
   every row with `args_flags & 64` non-zero is labeled `preview`.
3. **Save hook, per checkpoint.** Checkpoints are confirmed `ridesetname` rows whose `args_json` name is `check 1`,
   `check 2` or `check 3` (schema 0 shows a rename gives one confirmed `ridesetname` row plus client-only copies
   with flags 96, which this rule skips). The saves between checkpoint `k` and the next checkpoint (or the session's
   end) belong to save type `k`: Save Game As, plain Save Game, quit save. One save prints "fired", none prints
   "not seen", more than one prints "unknown save type" (an autosave may be among them), and a missing checkpoint
   prints "cannot classify".
   "Not seen" for both plain Save Game and the quit save prints the roadmap's stop instruction.
   The save-hook verdict is pass when check 1's outcome is "fired", check 2 and check 3 are not both "not seen" (that case prints the stop line), and no checkpoint's outcome is "cannot classify"; otherwise it is FAIL.
4. **Supporting tables:** rows per `hook` and `action_label`; the distinct `player` values per label; the last
   `plugin_stats` sent and dropped totals beside the Parquet counts.

## Files and owning modules

| File | Change | Owns |
|---|---|---|
| `plugin/src/actions.ts` (new) | buffer, hook recording, label rule, drain, send step, payload | R1-R11, R13 |
| `plugin/src/work.ts` | `action` step kind; two tick parts; `noteTickPart` type and dispatch; comment at :30 | R12 |
| `plugin/src/events.ts` | the eight new `plugin_stats` fields | R11, R12 |
| `plugin/src/main.ts` | recorder, its task, two subscriptions, the drain in `onSave`, `PLUGIN_VERSION` | R2, R9, R14 |
| `plugin/test/fake-game.mjs` | the two hooks in `subscribe`'s table (`:296`; file is 436 of 500 lines) | seams |
| `plugin/test/fake-actions.mjs` (new) | firing helpers with a chosen cost, kept out of `fake-game.mjs` as `fake-track.mjs` was | seams |
| `plugin/test/fake-world.test.mjs` | the "no hook" test (`:26-29`) names a hook the stand-in still lacks (review PA-13) | seams |
| `plugin/test/actions.test.mjs` (new), `allocation.test.mjs`, `work-queue.test.mjs`, `plugin.test.mjs`, `finance-session.test.mjs` | tests and version pins | R1-R14 |
| `contracts/game_action.odcs.yaml` (new), the 13 existing contracts | version, type list, `plugin_stats` fields, `worst_tick_kind_ms` text | R15 |
| `data/sample/rehearsal/v1/*`, `audit/*`, `README.md` | re-converted sample with an empty `game_action.parquet` | R16 |
| `models/staging/stg_game_action.*` (new); `stg_envelope.*`; every event-contract staging YAML; `_sources.yml` | staging | R17 |
| `models/intermediate/int_game_actions__labeled.*` (new); `dbt_project.yml` (the variable) | labels | R18, R19 |
| `models/marts/fct_cleaning_rule_count.sql`, `.yml` | the dedupe's counts row | R17 |
| `tests/dbt/assert_previews_never_player_actions.sql`, `assert_game_action_label_matches_flags.sql` (new); `assert_stg_envelope_keeps_every_delivery.sql`; `tests/test_dbt_player_actions.py` (new) | dbt tests and their planted-row proof | R17, R20 |
| Python tests that list every type or count contracts (`tests/test_contract_fields.py:63-65`, `test_sample.py`, `test_contracts.py`, `test_contracts_new_types.py`, `test_convert.py`, `test_convert_event_types.py`, `test_convert_lineage.py`, `test_guest_event_types.py`, `test_repeat_delivery_warning.py`, and any other the gate turns red) | type lists and counts | R15-R17 |
| `src/openrct2_analytics/ingest/bench_actions.py` (new), `tests/test_bench_actions.py` (new) | helper text and schedule; workload check | R21, R22 |
| `src/openrct2_analytics/ingest/bench_setup.py` (`RunInputs` gains `action_helper`, written to its own file), `bench_run.py` (`_verdict_attempt`, `:87-116`, passes it and adds R22's reasons), `tests/test_bench_run.py`, `tests/test_bench_run_sample.py` (sample runs get no action helper) | wiring (review PA-R10b) | R21, R22 |
| `src/openrct2_analytics/ingest/real_play_check.py` (new), `tests/test_real_play_check.py` (new), `Makefile`, `CLAUDE.md` (Commands) | result command | R30 |
| `docs/real-play-check.md` (new) | the permanent real-play step list | R29 |
| `docs/adr/0025-previews-sent-tagged.md` (new), ADR 0006, `docs/FINDINGS.md`, `ARCHITECTURE.md`, `CHANGELOG.md`, `docs/CONVENTIONS.md` (:118, :228), `docs/architecture/openrct2-facts.md`, `docs/architecture/benchmark.md` (helper and workload rule), `docs/ai-dlc/reports/dbt-design--findings.md` 6.2, roadmap :105 and :359 | records | R27, R28, R31 |

`scripts/dbt_rules.py` needs no edit: rule c reads each contract's version from the contract file
(`scripts/dbt_rules.py:264-280`), so only the staging YAMLs change (review PA-R10).

**Owning module per rule.** Envelope fields, `seq`, `event_id` and `emitted_at` belong to `plugin/src/emit.ts` only;
`actions.ts` fills payloads and never stamps them. The plugin's label belongs to `actions.ts`; R20's tests re-derive
it from raw columns. Who issued an action belongs to `int_game_actions__labeled`. Money stays in tenths until
`stg_game_action` (rule 3). `convert.py`, `pyproject.toml`, `package.json` and the lockfiles do not change.

## Contracts and regeneration

In order, by one worker, so the gate is never asked to pass half a bump:

1. Before tickets, the director confirms the preserved raw sample copy of the 2026-10-21 sample sessions (below,
   `$SAMPLE_RAW`) exists and its three files hold 3,112, 2,996 and 3,321 event lines (the audit counts,
   `data/sample/rehearsal/README.md:34`); the director gives its location at run time
   through `$SAMPLE_RAW`. The stable copy is the folder the preserved copy named by `$SAMPLE_RAW` holding
   `events-2026-10-21-session-1.jsonl`, `events-2026-10-21-session-2.jsonl` and `events-2026-10-21-session-3.jsonl`. If it is missing, stop (conditional stop C1). Use is copy-only (ruling 4): copy the files into a temporary folder, check the line counts on the
   copies, convert from the copies, and never write to `$SAMPLE_RAW`.
2. Build on the cash fix's pushed head (branch `feat/month-start-cash`), or on `origin/develop` once the cash fix
   has merged; call that `<base>`. First check all 13 contracts and the staging pins read 1.6.0:
   `git fetch origin && git grep -c '^version: 1.6.0' <base> -- 'contracts/*.odcs.yaml'` lists 13 files, and
   `git grep -l 'contract_version: 1.6.0' <base> -- models/staging` lists every event-contract staging YAML,
   and `git grep -n 'contract_version: 1.5.0' <base> -- models` prints nothing. Otherwise stop and report. Never
   rebase. Expect merge conflicts in `contracts/`, the sample, the `plugin_stats` contract and the version pins.
3. Edit the 13 version lines to 1.7.0, add `game_action.odcs.yaml`, extend the type list and `plugin_stats`.
4. Set every event-contract staging YAML to 1.7.0 (not `stg_park_registry.yml`), add the `stg_envelope` branch,
   fixture and test, run `python scripts/generate_dbt_sources.py` and confirm `--check` passes.
5. Update the Python tests that list every type or hard-code a count (`tests/test_contract_fields.py:64` asserts 13;
   it becomes 14).
6. Re-convert the sample (R16). The branch is red between step 3 and step 6; no gate runs between them.

## Test seams

- **Plugin tests on the stand-in game** (`node --test plugin/test/*.test.mjs`): `fake-actions.mjs` fires a hook with
  chosen `player`, `type`, `action`, `isClientOnly`, `args`, `result` and cost.
- **Required plugin cases:** one row per hook call with every R1-R6 column; bit 64 gives `preview`, also with a
  negative `flags`; `isClientOnly` alone gives `prediction`; both give `preview`; neither gives `confirmed`; missing
  or non-numeric `flags` gives null and no preview; each flat column null when absent; `args_json` parses back to
  the given `args`; changing `args` or `result` after the hook returns does not change the row (R8); a hook on the
  last tick of a day, sent after the day changes, keeps the earlier `action_game_day` while the envelope shows the
  later one (R6); an action hook followed at once by a save hook gives the action a lower `seq` than `save_written`,
  and the stored floor plus waiting count plus 1 equals `save_written`'s `seq` (R9); a full buffer drops the next
  item and counts it under its label; sent totals equal rows emitted per label; items leave in creation order among
  other events; weather, `action_query` and `action_execute` parts keep separate totals and never set
  `worst_step_kind` (R12); 131 hook calls with a set cost in one tick appear as that tick's `action_execute` part and
  the queue's steps that tick stop at the allowance counting that time (review PA-10); payload object and arrays are the same objects across events
  (`allocation.test.mjs`); a session with no actions sends no `game_action`.
- **Benchmark code** (`tests/test_bench_actions.py`): `c(t)` sums to 8,576 rows for `h` = 1 and 2 and takes only the
  stated values; the workload check fails a run with no helper rows, one row short, a wrong label, a buffer drop, or
  a sent total that disagrees; judged runs get the action helper and sample runs do not.
- **Result command** (`tests/test_real_play_check.py`): real Parquet written to a temporary folder from built rows:
  a pass; two kept rides; a created then demolished ride (not counted); an untagged bit-64 row; zero, one and two
  saves per checkpoint window; a missing checkpoint; refusal without `DATA_SET` and with an exported one. No mocks.
- **dbt** (`make check`): the new models build with 0 rows on the sample and the zero-row extract; R20's planted-row
  test proves both singular tests go red; the cleaning-rule counts, built-columns and house-rule checks pass.
- **Not covered offline:** real-play `flags`, `isClientOnly` and `player`; whether `map.save` fires for plain Save
  Game and the quit save; the size of `args_json` for a large action such as placing a saved design (no cap set).

## Golden paths

- Hook into a buffer, sent by a continuous task: `plugin/src/guests.ts:232-256`; hook value through a variable:
  `plugin/src/main.ts:92-96, 110-113`.
- Timed tick part: `noteTickPart` at `plugin/src/work.ts:208-210` (its dispatch changes here).
- Payload builder: `createRideSnapshotBuilder` in `plugin/src/rides.ts`; stand-in split: `plugin/test/fake-track.mjs`.
- Contract: `contracts/save_written.odcs.yaml`; optional field wording: `contracts/plugin_stats.odcs.yaml:249-257`.
- Staging: `models/staging/stg_save_written.sql`; money: `stg_ride_snapshot.sql`; union branch: `stg_envelope.sql`.
- Labeling model: `models/intermediate/int_statements__labeled.sql`; planted-row dbt test:
  `tests/test_dbt_missing_day.py`; two parks: `tests/test_dbt_two_parks.py`.
- Benchmark helper: `SAVE_HELPER` and its writer, `bench_setup.py:44-68, 351-369`.
- Command with house exit codes: `src/openrct2_analytics/ingest/capture.py`.
- Benchmark procedure and FINDINGS row: `docs/ai-dlc/specs/ride-weather-capture.md`, "Benchmark plan".

## Out of scope

- Per-day game-action counts (ruling 2): moved to the roadmap Backlog, unscheduled, for the project owner to reassess.
  This item records the running totals on `plugin_stats` only and builds no per-day model and no `stg_plugin_stats`.
- Collapsing click runs and repeated actions (roadmap 3b-2); preview reconciliation (v2); the save-file watcher;
  any plugin action that changes a real park; action marts; joining actions to the save lineage.
- Buffered guest arrivals at a save (R9 changes only the action buffer).
- A `make bench-sample` rebuild, any change to raw files, a `@openrct2/types` bump, any new dependency.

## Constraints

The repo's invariants (CLAUDE.md, "Never break"), verbatim:

1. Every event carries `park_id`, `session_id`, `seq`, `event_id`, game date, and `emitted_at`; `seq` has no gaps or
   duplicates within a session. (From contract v1; the 2026-09-27 capture is schema 0.)
2. Raw captures are append-only; every fix happens downstream in dbt. The one exception: before go-live, `make
   delete-company-data` archives and then rewrites or removes company raw captures and registry deliveries (ADR 0033).
3. Money stays in the game's tenths of a dollar until one staging conversion; every metric names its unit and its
   clock (game day, company date, or wall-clock hour).
4. Build previews and client-side predictions never count as player actions.
5. Never commit RollerCoaster Tycoon files, game screenshots, the GPL type definitions, or private machine paths.
6. The contract is versioned: adding fields is a minor bump; a breaking change is a major bump and a new landing path.
7. Analyses state their sample (parks, players) and say "observational" unless an experiment design backs a causal
   claim.
8. The plugin compiles to ES5 and stays within its measured per-tick cost budget.

Also: contract text about hook fields is in the project's own words.
- Files at or under 500 lines. No `catch` in hook or step code (`try/finally` only). Hotspots, one writer at a time:
  `plugin/src/main.ts`, `contracts/`, `models/staging/`, `Makefile`. Committed text never names the project owner.

## Verify-by

A fresh worker runs steps 1 to 5 in its own worktree. Step 6 reads the director's benchmark outputs; step 7 reads the
project owner's pasted output.

1. `check:` `make check` exits 0.
2. `check:` `npm run --silent plugin:build && node --test plugin/test/*.test.mjs` exits 0, and
   `node --test plugin/test/actions.test.mjs` reports every "Required plugin cases" item passed.
3. `check:` `git grep -c "^version: 1.7.0" -- 'contracts/*.odcs.yaml'` lists 14 files;
   `git grep -n "version: 1.6.0" -- 'contracts/*.odcs.yaml' models` prints nothing;
   `uv run python -m openrct2_analytics.ingest.contracts --data-root data/sample/rehearsal` exits 0; a DuckDB count of
   `data/sample/rehearsal/v1/game_action.parquet` prints 0.
4. `check:` the precedent spec's sample comparison: old columns unchanged both ways, row counts equal, new
   `plugin_stats` columns null in every row.
5. `check:` `uv run pytest tests/test_real_play_check.py tests/test_bench_actions.py tests/test_dbt_player_actions.py
   tests/test_contract_fields.py tests/test_sample.py` passes; `uv run python -m
   openrct2_analytics.ingest.real_play_check` with no `DATA_SET` exits 2.
6. `check:` the dry run's printout gives `h`, the helper's `player` value and marker result, per-period
   `lines_queued_max`, no dropped line and no buffer drop; then each judged window's `verdict.json` has `passed` true,
   or R25's ladder ran as written. Outcome 2026-10-22: the ladder ran as written (window 1, then the
   re-run, window 2) and ended at C4 with `Q` + `A` < `E`; both verdicts are FAILED on the worst tick and were accepted
   by the project owner's ruling (ADR 0041). `judgment:` a reviewer checks every judged window has a FINDINGS row with R27's
   fields and that any ladder step's `Q`, `A` and `E` are printed in it.
7. `judgment:` the pasted output shows ride builds 1, previews tagged pass, and a line per save type; a reviewer checks
   R31's FINDINGS row and facts-page edits match it, and that `docs/real-play-check.md` names no game setting.
8. `judgment:` a reviewer checks `stg_game_action.sql` only renames, casts, converts money and dedupes, and that ADR
   0025's text matches the bench outcome and ruling 1 (previews sent tagged, no discard path).

## Definition of Done

- Every R1-R31 is met; the build followed the four rulings.
- `make check` is green on the slice branch and on `develop` after merge.
- The judged `make bench` windows with the action helper are in FINDINGS. Their verdicts are FAILED on the worst tick and were
  accepted by the project owner on 2026-10-22 (ADR 0041); the judge code still prints FAILED for them.
- The real-play check passed and is in FINDINGS and the facts page; if the save hook fired for neither save, the item
  is marked stopped for the watcher redesign, not done.
- ADR 0025, ARCHITECTURE, CHANGELOG, CONVENTIONS and roadmap :105 and :359 are updated; :359 is marked done only after
  the real-play check passes. The PR into `develop` was reviewed before merge; only the project owner merges to `main`.

## Conditional stops

Each halts the unattended build at a named point and reports; none needs an answer before approval.

- **C1.** The preserved raw copy is missing or its line counts differ (Contracts step 1).
- **C2.** Neither provenance signal survives the dry run (R19).
- **C3.** The dry run or a judged run drops a line or a buffered action (R23): the run is void, reported, and the
  build stops. The remedies (a faster queue drain, a larger queue
  bound, a lighter burst) each change a ruled workload or a measured bound.
- **C4.** A judged failure that the action parts do not explain, or the third window fails, which ends the ladder
  with no discard path: the item stops and reports the numbers for a redesign (R25, R26).

## Rulings (project owner, 2026-10-19)

The project owner answered the three open questions of review round 1 on 2026-10-19. Each ruling is binding on the
build; none is open.

1. **Stop and redesign; previews are never discarded.** The fallback ladder (R25) never ends by discarding previews, so
   the done line ("labeled previews captured") and ADR 0025 ("previews sent tagged") stay true. A failure after the
   last ladder rung stops the item and reports the numbers for a redesign (R26, C4). This replaces G1-9's discard
   fallback. Gain: no capture loses previews without the project owner seeing the numbers. Cost: an unattended build
   may halt, and real play waits for a ruling, about one day.
2. **Per-day action counts leave this item.** They moved to the roadmap Backlog, unscheduled, for the project owner to
   reassess later (review PA-04). Gain: this item stays at its current size, and no data is lost, because every
   `plugin_stats` row holds a game day's running totals and a later model can take differences. Cost: per-day counts
   are not in the warehouse until then. The roadmap's part 3b description no longer lists them.
3. **No "Theme Park Enterprise version" setting.** The roadmap phrase names company play, not a game setting; the
   roadmap line is reworded and the real-play step list names no game setting. Gain: nothing blocks the build. Cost:
   none known.
4. **Copy-only use of the preserved raw sample copy** (the 2026-10-21 sample sessions; approved with the earlier
   copy-only terms). The build copies the files into a temporary folder, checks the line counts 3,112, 2,996 and
   3,321 on the copies, converts from the copies and never writes the source. Committed text calls it the preserved
   raw sample copy and uses the placeholder `$SAMPLE_RAW`, never a machine path.

## Post-approval amendments (2026-10-22)

These are post-approval edits, not changes to the Gate 1 rulings.

- **(a) Sample raw counts.** The sample's raw source is the 2026-10-21 copy, and its three files hold 3,112, 2,996
  and 3,321 event lines (Contracts step 1, stop C1, "Copy-only use" above). Source: project owner ruling, 2026-10-22.
- **(b) The dry run is a `bench_run --dry-run` option.** Defined at its first use under R2; built by T7. Source:
  project owner ruling, 2026-10-22.
- **(c) The save-hook pass rule.** The rule the code uses is written under "What the result command prints" item 3
  and in `docs/real-play-check.md`. Written up 2026-10-22; the project owner confirms the rule at the game session.
