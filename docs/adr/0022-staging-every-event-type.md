# ADR 0022: staging covers every contracted event type except `plugin_stats`, and the staging slice is built in two parts

- Date: 2026-10-09
- Status: Accepted. It records the staging rulings the project owner gave for slice 3a on 2026-10-05, 2026-10-06
  and 2026-10-09.
- Supersedes in part: ADR 0016 (`docs/adr/0016-dbt-design.md`). Two statements are replaced: the "Guest events"
  row of the provisional-choices table and the clause that names the company-calendar build as the author of
  `stg_envelope`. The rest of ADR 0016 stands unchanged.

## Bottom line

Every contracted event type except `plugin_stats` gets its own staging model, and the staging slice (roadmap 3a)
owns `stg_envelope`. ADR 0016 had planned to stage only three of the five guest event types and left the building of
`stg_envelope` to the company-calendar work. Both statements no longer match what is built, and an accepted ADR is
superseded, not edited, so this record replaces them. The slice is built in two parts: part 1 (3a-1) builds the shared
machinery, the five non-guest event types and `stg_envelope`; part 2 (3a-2) adds the five guest models on that
machinery.

## Context

ADR 0016 chose its staging scope before the guest capture existed. Its "Guest events" row staged
`guest_boarded`, `guest_refused` and `guest_arrived` and held `guest_left` and `guest_snapshot` until a consumer
appeared after v1. Its `stg_envelope` paragraph said the company-calendar build defines that model. The project
owner's rulings for slice 3a replaced both: staging for every contracted event type, none for `plugin_stats`, and
`stg_envelope` owned by the staging slice, which keeps every landed delivery and which the park-registry and
company-date work then consumes. Without a record, the accepted ADR would contradict the build.

The same rulings said to split the slice if its spec needed more than about 8 tickets, and the spec did. The
sources do not say what goes in each part; the split below follows the type split the project owner wrote for the fallback
case (part 2 unmerged), which both spec reviewers accepted as the reading for this split.

## Decision

### 1. Every contracted event type except `plugin_stats` is staged

`stg_<event_type>` exists for `finance_month`, `park_snapshot`, `session_start`, `ride_snapshot` and
`save_written` (part 1), and for `guest_arrived`, `guest_boarded`, `guest_left`, `guest_refused` and
`guest_snapshot` (part 2). No `stg_plugin_stats` model is built. This replaces ADR 0016's "Guest events" row; the
guest identity it names (`session_id` plus `guest_key`) is not changed here.

Gain: one rule, with no list of exceptions to remember; every staged type is checked by the same gate. Cost: two
guest types (`guest_left`, `guest_snapshot`) get a model before any v1 consumer asks for one.

### 2. The staging slice owns `stg_envelope`

`stg_envelope` is built in part 1 by the staging slice, not by the company-calendar build. Its behavior in ADR 0016
stands: it keeps every landed delivery, including repeated `event_id` deliveries, and reads only the envelope
columns. This replaces the clause at ADR 0016 that gave the model to the company-calendar build.

Gain: the model exists before the work that consumes it. Cost: that work waits for part 1.

### 3. Two parts: 3a-1 and 3a-2

Part 1 (3a-1) builds every check, the money macro and the contract bump once, plus the five non-guest event types
and `stg_envelope`. Part 2 (3a-2) adds the five guest models on that machinery, as small, routine changes; the
three guest models that carry money (`guest_arrived`, `guest_boarded` and `guest_snapshot`) get their enforced
contracts there. A contract change in part 2 takes the next minor version, 1.5.0.

Gain: the shared pieces land once and the guest models are small. Cost: until part 2 merges, the forward staging
rule of `docs/CONVENTIONS.md` is unmet for the five guest types, and the planned `ride_boarding` metric stays
planned.

## Rejected alternatives

- **Editing ADR 0016 in place.** An accepted record would then say something its readers never agreed to. ADR 0016
  gains a status line instead.
- **Building all ten event-type models in one slice.** More than about 8 tickets, against the ruling to split.

## Consequences

- ADR 0016's status line gains "Superseded in part by ADR 0022".
- Part 2 gets its own short spec section once part 1 merges.
- **How we would know this is wrong:** a consumer needs `plugin_stats` rows in a model, or the company-date work
  cannot read `stg_envelope` as built. Either reopens this record.
