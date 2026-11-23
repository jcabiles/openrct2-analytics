# ADR 0042: the plugin sends only business actions

- Date: 2026-11-02.
- Status: Accepted 2026-11-02 (the project owner ruled that no data about what the player builds, creates or types is collected; the `ridefreezerating` question closed 2026-11-03; amended 2026-11-16 to record a second one-time contract-version exception, see "Bottom line" and "Context"). It supersedes ADR 0006's preview row and the player-actions spec's R26. Number 0025 was promised by the player-actions spec (`docs/ai-dlc/specs/player-actions.md`, R28) and never written; it is not reused.

## Bottom line

The plugin now sends a `game_action` row only for 13 business actions (prices, ride and stall operation, park, finance and staff decisions), and for two of them (`ridesetsetting`, `ridesetvehicle`) only for listed operating and capacity sub-types. It drops every other action, every build preview, every unlisted sub-type and every action name it does not know, before the row enters its 2,048-row buffer, so a dropped call takes no `seq` number. Five new `plugin_stats` counters count the dropped calls. All 14 contracts move to 1.8.0 on the existing `v1` landing path. This is a one-time exception to the promise of one row per hook call, allowed only because no mart reports figures from game actions (`fct_cleaning_rule_count` only counts their rows) and company data is scratch until go-live. From plugin 0.9.0 the cheat counter also counts `ridefreezerating` (ruled 2026-11-03); the contract stays 1.8.0 as a second one-time exception, ruled 2026-11-16, so two one-time contract-version exceptions now exist, and neither changes rule 6 for any later change.

## Context

The first company session (2026-11-02) wrote a 183.6 MB raw file, 99% `game_action` rows, almost all of them build previews. One tick of track building overflowed the 2,048-row buffer and dropped 10 confirmed rows. Separately, the project owner ruled that the project collects business decisions only: no data about what the player builds, creates or types, and nothing personal about the player in the repository. ADR 0006 had the plugin drop previews and predictions with a daily count per action type, once two checks passed. The player-actions spec (R26, R28) replaced that with sending them tagged and forbade any discard path, but its ADR 0025 was never written, so ADR 0006's row was never formally superseded. Both rest on keeping every call, which this ruling reverses.

## Decision

1. **Keep 13 names.** The kept actions are `parksetentrancefee`, `ridesetprice`, `ridesetstatus`, `ridesetsetting`, `ridesetvehicle`, `parksetparameter`, `parkmarketing`, `parksetloan`, `parksetresearchfunding`, `staffhire`, `stafffire`, `staffsetorders` and `staffsetpatrolarea`, as listed in `plugin/src/action_names.ts`. `ridesetsetting` is kept for operating settings only (codes 0 to 5, 8 and 9; ride type and music are dropped). `ridesetvehicle` is kept for number of trains and cars per train only (the vehicle model, sub-type 2, is dropped).
2. **Drop everything else before the buffer.** Previews, all other action names, unlisted sub-types and unknown names (including any name a later game version adds) are dropped before arguments are copied and before a `seq` number is taken. The lists live in `plugin/src/action_names.ts`, with a Python copy in `src/openrct2_analytics/ingest/action_names.py` that `tests/test_action_names.py` compares with it. The plugin stays at the 81 names of the `@openrct2/types` 0.5.5 action list; any other name counts as unknown, so a mismatch drops instead of sends.
3. **Count the drops.** Five `plugin_stats` counters hold running totals of dropped calls: `game_actions_skipped_preview_total`, `game_actions_skipped_prediction_total`, `game_actions_skipped_confirmed_total`, `game_actions_skipped_unknown_total` and `game_actions_skipped_cheat_total`. The cheat counter records that cheat calls happened, with no arguments.
4. **Contracts stay v1 at 1.8.0.** The five counters are optional fields, so the landing path does not change. The committed sample gains the five columns by a column migration of its `plugin_stats` file, with no game run and no raw file.
5. **Predictions of kept actions stay as rows.** `int_game_actions__labeled` still never counts a prediction as a player action.

## Supersedes

- **ADR 0006, the row "Previews and client-side predictions".** The row is replaced: dropping is now unconditional and applies to previews and to every non-kept action, with session totals per label instead of a daily count per action type and no gating checks; predictions of kept actions are kept. The plugin 0.7.0 tagged sending that the player-actions spec introduced ends. dbt still labels predictions, and its preview tests keep guarding rows from plugin 0.7.0 and earlier.
- **The player-actions spec's R26, "No discard path".** The plugin discards by design, as the lists above state.

## Exception to repository rule 6

Repository rule 6 treats a change to what a contract promises as breaking, and `game_action` promised one row per hook call. Dropping rows changes that promise, yet the version moves only by a minor bump. The exception holds once, before go-live, because no mart reports figures from game actions (`fct_cleaning_rule_count` only counts their rows) and company data is scratch until go-live (ADR 0033). It does not change rule 6 for any later change.

A second one-time exception, ruled by the project owner on 2026-11-16, keeps the contract at 1.8.0 although the `plugin_stats` cheat counter now counts two actions, `cheatset` and `ridefreezerating`, instead of one. The counter's promise changes, yet the version stays 1.8.0 and no field is added. It holds once, before go-live, for the same reasons as the first: no model reads the column and company data is scratch until go-live (ADR 0033). It does not change rule 6 for any later change.

## Consequences

- **Gain:** raw files are far smaller, the buffer no longer overflows on track building, and build, creation and typed-text detail is never collected.
- **Cost:** build detail is gone for good for sessions played with plugin 0.8.0 and later, and cannot be recovered downstream.
- **Real-play check.** It reads ride builds from `ride_snapshot` rows, and its save checkpoints are the three price clicks on the new stall, in order.
- **Benchmark.** The benchmark's action helper sends only plain `ridesetprice` calls, so every action row in a judged run is confirmed. The next judged `make bench` measures a different mix from the earlier windows (ADR 0005, ADR 0041); that run is left to the project owner.
- **Older rows.** Rows from plugin 0.7.0 may still hold previews and build actions, and the dbt preview tests keep guarding them.
- **Closed 2026-11-03: `ridefreezerating` counts as a cheat.** It is a cheat and is dropped, and it now feeds the cheat counter with `cheatset`, for a fuller cheat trace. The cost is one table change and a counter name that no longer matches a single action. The contract description names both actions and no field is added. The plugin version moves to 0.9.0 so rows from earlier plugins can be told apart. The contract version stays 1.8.0 under the second exception to rule 6, recorded above.
