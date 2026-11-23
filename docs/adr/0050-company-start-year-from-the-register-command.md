# ADR 0050: the register command takes the company start year of the second and later parks

- Date: 2026-11-13.
- Status: Proposed with the start-year spec (`docs/ai-dlc/specs/start-year.md`); it takes effect when the branch that
  builds it merges. Amends ADR 0038 (`docs/adr/0038-company-registry-deliveries-from-the-register-command.md`), only
  where that record says the command always writes company start year 2000.

## Bottom line

`make register-parks` and `make after-play` gain one option, `START_YEAR=<year>`, so the second company park is
registered with its real company start year and not the fixed 2000. The option is required when a non-practice company
park is already registered and a non-practice park is being registered, and the only year accepted is the company year
after the latest year the registered parks hold. The first company park keeps 2000, and practice parks take no year. A
wrongly typed year that lands can be fixed only by hand, before go-live. No data contract, dbt model, plugin file or
event contract changes.

## Context

ADR 0038 gave the command one fixed start year, 2000, and noted that a real park with another start year needs a later
change. The company now plans a second park that starts the company year after the first park's last managed year, so
that the site can show two parks in one month. A registry row with the wrong year puts every month of that park on the
wrong company calendar, and the registry is append-only from the point of view of the warehouse.

## Decision

1. **The option is required as follows.** A "registered company park" is a park whose latest registry row has
   `data_set` `company` and no practice note (`register_parks.py:_registered_company_parks`). With none registered, the
   first company park gets 2000 and `START_YEAR` may be left out. With one or more registered, `START_YEAR` is
   required for the non-practice park being registered. Practice parks never count as registered company parks, take no
   `START_YEAR`, and get 2000 as before. Gain: no silent 2000 for a second park, while the first-park path stays one
   bare command. Cost: one more registry read, which `registered_parks` already makes today.
2. **The floor F is the latest company year the registered company parks hold.** A park's year is the larger of its
   registry start year and its latest managed company year; F is the largest such year. Once a park has managed days,
   F is that park's last managed year Y. The start year enters only for a registered park with no managed day yet, so a
   new park cannot be given a year that a registered park already holds. The managed company year is read by the
   shared logic of the autopilot item (ADR 0049; `managed_years.latest_managed_year`), from the converted
   `park_snapshot`, `save_written` and `session_start` files. This record does not redefine it: days after a session's
   last save do not count, a 1 March day counts toward the year before only when its session already played that year or its `session_start` is in that year, and `autopilot` sessions do not count. Gain: one
   owner for the rule. Cost: one comparison on top of the shared reader.
3. **Exactly F + 1 is accepted.** A year at or before F is refused (Y is refused and Y + 1 accepted when Park 1's last
   managed year is Y), and so is a year after F + 1. The business rules (R13 of `docs/ai-dlc/specs/start-year.md`) start the next park the March after the managed
   park goes to autopilot, and a gap year would have no managed park. Gain: a typo such as 2005 for 2001 is caught
   before it lands, and such a row could otherwise be fixed only by a delete. Cost: the typed year confirms a value
   the command already knows, and a deliberate gap needs a code change.
4. **The first company park accepts only 2000.** `START_YEAR=2000` there is accepted and any other value is refused.
   Any typed year, for the first company park too, is checked against the park's game-year origin: the park's first
   `session_start` must be in game year 1, or the command refuses. A bare command for a first company park skips that
   check, as it did before. Gain: a typed 2000 is not punished, and the first park cannot be moved off 1 March 2000.
   Cost: one more refusal text.
5. **A given `START_YEAR` with nothing to register is not used and not refused.** Both commands print a line saying so
   and exit as before. Gain: the after-play rerun line still works after the register step succeeded and a later step
   failed. Cost: a mistyped year on such a rerun goes unnoticed, which is harmless because nothing is written.
6. **One run registers at most one non-practice park, and the year is checked in three places.** `START_YEAR` applies to
   exactly one park, so two non-practice parks in one run are refused whether or not a year is given. The year check
   runs before the lock, again under the landing lock (a delivery or convert may have landed while the lock was taken;
   the lock does not wait), and `make after-play` runs the same check before its first step. Gain: a bad year ends as
   a refusal (exit 2, nothing changed) and not as a failed register step in the middle of the chain. Cost: the
   managed-year read runs up to three times.
   `make after-play` cannot register one of two waiting company parks: it refuses a `PARKS` list that omits a waiting
   park (`parks-missing`), and a list naming both as company is refused as several company parks. Register one with
   `make register-parks PARKS=...` first.
7. **Exit codes and the refusal rule are unchanged:** 0 written or nothing to do, 1 failed, 2 refused, 130
   interrupted; every refusal leaves the folder tree unchanged. The stale-Parquet guard is the autopilot item's:
   when a company park is already registered (not for the first company park) and a non-practice park is being registered, a raw file holding a session that was never converted is a refusal, because a
   stale Parquet understates the last managed year.
8. **A mistyped year is fixed by hand.** If a wrong year lands, `make delete-company-data` before go-live (ADR 0033)
   removes the row, and the park is registered again. No correction command is built.
9. **Abandoned play raises the floor, and there is no override.** The floor reads converted Parquet, and autosaves
   are saves, so managed days that a player abandoned (for example a try-out branch of Park 1 that ran past its
   closing 1 March) still count. Park 2 then has to start the year after that. The overlap and gap refusals name the park and
   the year F that set the floor, and the missing-year refusal names only the floor year; all three point here; they cannot name the session and game date, because the shared
   reader returns only the year. To find which session set F, read the `make results` sessions list, or the converted
   `park_snapshot` game dates of that park. There is no flag to set the floor lower; the fix by hand is decision 8.
   Gain: one rule for both commands. Cost: if Park 1 recorded a save in a try-out
   branch that reached Y + 1, Park 2 must start in Y + 2.

## Rejected options

- **Fixing the start year at 2000 for every park.** Gain: no new option. Cost: two parks share company years, and the
  second park's months land on the wrong calendar.
- **Accepting any year after F.** Gain: a deliberate gap works without a code change. Cost: a typo lands and can be
  fixed only by a delete (decision 3).
- **A per-park year in `PARKS`, such as `<id>:company:<year>`.** Gain: several company parks in one run. Cost: two
  company parks can then share a year, and the parser grows; one park per run is the rule instead.
- **A command to correct a landed year.** Gain: no delete. Cost: a second writer of corrections to an append-only
  feed; out of scope (decision 8).

## Consequences

- A hand-written registry delivery that relabels a park from practice to company bypasses the year check. That is
  out of scope and is not guarded.
- The contract version does not change: `company_start_year` is a required integer with no bounds in
  `contracts/reference/park_registry.odcs.yaml`, so the overlap rule lives in `register_parks.py`.
- ADR 0038 gains a status pointer here, and no other edit.
