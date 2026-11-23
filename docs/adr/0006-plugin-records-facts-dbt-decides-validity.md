# ADR 0006: The plugin records facts; dbt decides which records are valid

- Date: 2026-09-29
- Status: Accepted; the row "Previews and client-side predictions" is superseded by ADR 0042 (`docs/adr/0042-plugin-sends-only-business-actions.md`), which makes dropping unconditional for previews and every non-kept action, with session totals per label instead of a daily count per action type and no gating checks, and ends the tagged sending that the player-actions spec (R26, R28) had put in its place.

## Bottom line

The plugin, standing in for the app team, sends what happened plus the facts only it knows: event IDs,
an exact ID for every save, and which save a session loaded. It drops only construction previews and
client-side predictions, with a daily count of what it dropped, and only after two checks pass. Raw
captures keep everything the plugin sends. dbt decides which records are valid, with a test and a count
for every rule: it removes duplicate deliveries, collapses runs of clicks and repeated confirmed actions
into one decision each, and labels rows on abandoned timelines instead of deleting them.

## Context

The game's events behave like real app data. The first capture showed five kinds of records that are
valid JSON but do not count as business facts: history that branches when an earlier save is reloaded
(including the 3 game days an autopilot run kept playing after its year-end save), duplicate
deliveries, one click sent as several events, one placement sent as several confirmed actions, and
construction previews and client-side predictions (about 96% of action events). The house rule is that
raw captures are append-only and every fix happens downstream in dbt, and the plugin is already over its
per-tick time budget (ADR 0005).

Research on 2026-09-28 and 2026-09-29 (`docs/ai-dlc/reports/which-records-are-valid--findings.md`,
reviewed blind by Codex) found that real teams split this work by who knows the fact, whether a wrong
call can be undone, and what keeping the data costs. Producers stamp identifiers and choose which
business events to send, and drop records they have already produced mainly when cost forces it;
consumers decide validity and keep raw data so the decision can change. Employers in the owner's 32
saved analytics-engineer postings ask most for data-quality testing (26) and trusted data (26); a
published take-home rubric rewards catching, handling and writing up data problems. The project owner weighted
real-world practice over showcase when the two disagree.

## Decision

Project owner, 2026-09-29:

| Issue | The plugin | dbt |
|---|---|---|
| Reloaded saves and the post-save run-on | On the `map.save` hook, mints a save ID, stores it with the session ID and `seq` in park storage (saved inside the save file), and emits a "save written" event; at session start, reports the save ID it loaded | Builds the timeline tree, keeps the latest branch from each save, and labels every row kept or abandoned; marts read only kept rows |
| Duplicate deliveries | Keeps stamping `event_id`, reused on any resend | Removes repeats in staging, keyed on `event_id` |
| One click sent as several events | Nothing: it cannot know when the player has finished | Collapses each run into one decision with its final value in intermediate; raw presses stay in staging |
| Repeated confirmed actions | Nothing: the action hook has no identifier shared across copies | Collapses copies matched on action, arguments and tick in intermediate |
| Previews and client-side predictions | Drops them and emits a daily count per action type, once two checks pass | Reconciles its own counts against the plugin's reported drops |
| Showing the work | — | One model counts rows kept and excluded by each rule, marked source-caused or transform-caused; the README's reviewer path summarizes it |

The two checks that gate the preview drop: the capture redesign measures what sending previews costs per
tick, and the pretest's positive control (the project owner drags one preview and places one real ride; exactly one
confirmed build event arrives) shows the flag never marks a real build. The save-ID mechanism is built
only after a headless probe shows that `map.save` fires before the file is written.

## Rejected alternatives

- **Send previews and let dbt detect them from the flag bits.** It shows the most cleaning in dbt, but
  costs the most plugin time, and real teams drop pure noise at the source when cost forces it.
- **Label previews and send them.** Nothing would be lost, but the plugin is over budget. This becomes
  the choice if the measurement shows sending previews is cheap.
- **Keep estimating timelines from game dates only.** No plugin work, but the estimate cannot tell a
  replay from a fork, and the run-on would need its own rule.
- **Drop abandoned timelines in intermediate, or move them to a separate table.** Dropping hides what
  was abandoned; a separate table adds a second table to keep in step. A label is reversible and
  countable.
- **Collapse clicks in the plugin.** The plugin would need to hold state and wait to know a player had
  finished, costing time it does not have, and the intermediate price steps would be lost.

## Consequences

- The capture redesign (roadmap NEXT 1) adds a `map.save` timing probe, the save lineage, the daily
  dropped count, and a per-tick cost measurement for sending previews.
- The contract (NEXT 2b) gains the save lineage and dropped-count events, and states that events are
  low-level commands that may repeat, so consumers deduplicate on `event_id`.
- Staging (NEXT 3a) removes duplicate deliveries; intermediate (NEXT 3b) labels timelines and collapses
  click runs and repeated actions; the trust tests and reviewer path (NEXT 3d, 3f) carry the kept and
  excluded counts.
- Schema 0 data (the 2026-09-26/27 capture and rehearsal parks captured before the redesign) has no save
  IDs, so its timelines keep the high-water-mark estimate, labeled as such.
- The append-only rule holds: dropping previews is a producer choice about what to send, made before
  capture, not a fix to raw data.

## How we would know this is wrong

- `map.save` fires after the file is written, or not at all headless: fall back to the estimate and
  revisit the lineage design.
- The measurement shows sending previews costs little: switch to labeling them.
- The positive control shows a real build flagged as a preview: stop dropping and label instead.
- A collapse rule merges two real decisions in a test fixture: tighten the rule before any mart uses it.
