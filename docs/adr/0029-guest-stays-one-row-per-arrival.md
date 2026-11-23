# ADR 0029: a guest stay is one row per arrival, never joined across sessions

- Date: 2026-10-11; reload ruling 2026-10-12.
- Status: Accepted, by the project owner's Gate 1 rulings for the guest stay model (2026-10-11) and the ruling of
  2026-10-12 on a guest across a save reload.
- Builds on: ADR 0018 (`docs/adr/0018-guest-capture.md`), which gives each guest a per-session `guest_key`, and ADR
  0024 (`docs/adr/0024-save-lineage-rules-for-the-kept-timeline.md`), whose kept timeline the model does not yet use.

## Bottom line

`int_guest_stays` has one row per `guest_arrived` event, keyed by (`session_id`, `guest_key`), with the matching
`guest_left` joined on when one exists. A guest seeded at session start has no arrival and gets no row. A guest still
present at a save reload counts once, as the open row of the session where it arrived; nothing joins a guest across
sessions. What is given up: a visit that spans a reload is shown as an open row, so open rows mix guests still in the
park, guests whose exit row was lost, and guests who had not yet entered.

## Context

A guest has no identity across sessions: a guest still present at a reload is seeded again under a new key and emits no
arrival (ADR 0018). The first Gate 1 text said a guest across a reload "counts as two stays, labeled", which conflicts
with "one row per arrival" and "exits with no arrival are excluded". The project owner resolved it on 2026-10-12.

## Decision

1. **Grain is one row per arrival.** An exit with no arrival (a seeded guest) produces no row. Gain: the row count
   equals the arrivals. Cost: those exits are not counted by any model; a warn-level test checks that each one is a
   seeded guest (`arrived_in_session` false).
2. **A guest across a reload is one visit.** The model never joins a guest across sessions. Gain: no guess about
   identity that the data cannot support. Cost: the visit's later part is invisible, and the stay's exit is never seen.
3. **Never-entered guests are kept**, flagged by `entered_park` from the exit, which is null while the stay is open.
4. **Stay length is whole game days, computed inline.** The day number uses the month lengths in
   `docs/architecture/openrct2-facts.md`, written as one offset table in the model and once in the month-length test.
   No macro, because no later model was named as a second user. Cost: the month table is written twice.
5. **The model is provisional until it carries a `timeline_status` label.** It reads every session, including events
   after each session's last save (ADR 0024). Relabeling is roadmap item 24's remaining work.

## Rejected alternatives

- **Two rows for a guest across a reload**, the first Gate 1 wording. The second part has no arrival to anchor a row.
- **Joining a guest across sessions** by slot or by cohort. A slot is reused, and the plugin keeps no identity.

## Consequences

- `ARCHITECTURE.md` (the intermediate model list) states the grain, the seeded exclusion and the provisional label.
- **How we would know this is wrong:** the project owner wants visit counts across reloads, or lineage-labeled data
  shows many guests whose only row is an open one that ends at a save.
