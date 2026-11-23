# ADR 0028: guest staging keeps 255 as a real reading and turns only the 65535 thought placeholder into null

- Date: 2026-10-11
- Status: Accepted, by the project owner's rulings for staging part 2 (3a-2) and for the 65535 follow-up (2026-10-11).
- Builds on: ADR 0022 (`docs/adr/0022-staging-every-event-type.md`), which stages the five guest event types.

## Bottom line

In the guest staging models, 255 in `happiness`, `hunger`, `thirst` and `nausea` stays as sent, and `thought_item` of
`stg_guest_snapshot` is the only guest column where a placeholder becomes null: 65535 ("the thought has no argument")
becomes null. What is given up: a reader of any other guest column still has to know what its raw value means, and a
reader of `thought_item` can no longer tell "no argument" from a failed read, because both are now null.

## Context

The staging rule for ride readings turns the placeholders -1, 1,275 and 255 into null, and the project owner's
wording for the staging rework said "255 become NULL". Those three values are placeholders in `ride_snapshot`, where the
contract names them as "no reading". In the guest contracts, 255 is different: it is each need field's declared
maximum (0 to 255, unhappy to happy), so a fully happy guest legitimately sends it. In the committed sample, 282 of
2,370 `guest_boarded` rows carry `happiness` 255, and `guest_snapshot` carries 8 `happiness` and 4 `thirst`
readings of 255. The guest contract describes 65535 in `thought_item` as the game's "no argument" value, and the
first guest models left it raw because the sentinel list did not name it.

## Decision

1. **255 in the guest need columns passes through.** The list of nulled placeholders is read as the values the game
   sends to mean "no reading", and that list is found in `ride_snapshot` only. Gain: a fully happy guest is not erased.
   Cost: none beyond saying so in each column description.
2. **65535 in `stg_guest_snapshot.thought_item` becomes null** (`nullif(thought_item, 65535)`), in that model only. The raw
   value and the contract are unchanged, and no other guest model gains a `nullif`. Gain: a consumer filters nothing
   to use the column. Cost: a null item now means no argument, no thought, or a failed item read; the column
   description names all three, and `thought_type` is the column that says whether a thought exists.

## Rejected alternatives

- **Nulling 255 in the guest need columns**, the literal wording of the original ruling. It would erase real readings
  (the sample counts above) and make "very happy" indistinguishable from "unknown".
- **Keeping 65535 raw**, the first reading. Every consumer of `thought_item` would filter it out by hand.

## Consequences

- `ARCHITECTURE.md` (the dbt stage) lists which placeholders become null and which stay raw.
- A new guest placeholder is a new decision: it needs its own record or an amendment, not a silent `nullif`.
- **How we would know this is wrong:** a guest column other than `thought_item` gains a game placeholder that the
  contract names as "no reading", or a consumer needs to tell a failed item read from "no argument".
