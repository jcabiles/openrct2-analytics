# ADR 0018: guests are captured by one seed, an arrival hook, a daily check and a 20-tick seat poll

- Date: 2026-10-08
- Status: Accepted

## Bottom line

The plugin follows guests without ever reading every guest again after startup. It seeds its known-guest table once,
records each arrival from the game's `guest.generation` hook, checks each known guest once a game day for exits and
refusal thoughts, polls car seats every 20 ticks to find boardings, and follows a random cohort of up to 100
arrivals with one snapshot a day. The work queue of ADR 0010 gains reusable task objects, reusable payloads and
continuous tasks to carry this. The measured full-capture part 2 benchmark passed: the worst tick was 4.164 ms and
the highest mean 0.0349 ms per tick, against 10 ms and 1.25 ms, and the day-start cost fell from 2.7464 ms (part 1's
plugin) to 2.3243 ms, more than the 0.2925 ms run-to-run spread the rule required (`docs/FINDINGS.md`, "Full capture,
part 2: benchmark"). This ADR extends ADR 0010 and does not replace it.

## Context

Part 2 had to record guest arrivals, exits, ride refusals, boardings with boarder details and a random guest sample,
and reduce the recurring day-start allocation that part 1 left, all inside the 4 ms allowance and the per-tick limits
of ADR 0005. The game offers no boarding hook, no hook for a guest leaving or a new thought, and no amount paid;
entity IDs are reused slots; and one pass over every guest cost 9.9 to 52.6 ms in the probes. So each fact had to be
inferred from what the API does expose, at a stated resolution.

## Decision

| Decision | Choice |
|---|---|
| Finding guests | One all-guest read at session start seeds the known-guest table; seeded guests emit nothing. After that no tick reads every guest. |
| Guest key | The plugin mints a `guest_key`, counted from 1 per session in first-seen order, because an entity ID can be reused by another guest. Every guest event carries the key and the ID. |
| Arrivals | The `guest.generation` hook only records the ID and tick; an `arrival` step emits `guest_arrived` later. Resolution is the tick. A reused ID first emits `guest_left` with `exit_reason` `id_reused`. |
| Exits | A daily `guest` step per known guest reads `map.getEntity(id)`; null, a non-guest, or a guest out of the park after being in emits `guest_left`. Resolution is the game day. |
| Refusals | The nine ride-refusal thought types, each with the refused ride's ID from `thought.item`, not confirmed in this repo for three of them (ledger row PX-9). A `guest_refused` is emitted for a thought not present at the guest's previous check, so a refusal that appears and expires within a day is missed and a repeat is not re-sent. |
| Boardings | A seat poll every 20 ticks reads every car's seats; a seat whose guest ID changed since the last completed poll is a new boarder. Everything a boarding carries is read at that poll, not at the later boarder step. |
| Capture limit | A boarding is missed when it starts and ends between two polls, and whenever a seat lists the same guest at both polls. Rides with no cars record none. The `guest_boarded` contract states the limit. |
| Price | `ride_price_listed_tenths` is the ride's listed price at the poll, standing in for the price paid, which the API does not expose. |
| Cohort | Each arrival joins with probability 0.5 (`Math.random`, not the game's generator) while fewer than 100 members are followed; a member leaves at its exit. One `guest_snapshot` per member per game day; `items_carried` is one `\|`-joined string. |
| Queue | Tasks are objects created once in `main()`. Day-scoped tasks (rides, guests) are skipped and counted at a new day; continuous tasks (arrivals, boarders) are fed between days and never skipped. Guest-kind steps are held from the day callback's tick until the day's ride items are done. |
| Payloads | Every payload builder fills one reusable object per event type and writes every field on each fill. The emitter copies the fields, so a reused payload is never queued itself. |
| Attribution | `plugin_stats` reports each period's worst tick split by step kind, and `worst_day_start_tick_ms`, the highest whole time of the day-start ticks. A step or poll that throws is counted in `work_items_failed_total` and the error still reaches the game. |

## Rejected alternatives

- **A daily all-guest diff.** It costs an all-guest read each day, the single-tick cost that failed the first
  capture design.
- **A daily seat check for boardings.** It sees only the guests aboard at one instant a day, so it misses every ride
  that begins and ends between two checks, a far larger share than a 20-tick poll misses.
- **First-come cohort admission.** The cohort would over-represent the first guests of a session; a constant
  probability gives every arrival the same chance while a place is free, at half the fill rate.
- **Reading boarder details at the boarder step.** A guest slot or a price can change between the poll and the
  step, so the event would carry another guest's values.
- **One boolean per item type.** It adds 50 contract fields, and a new item type in a later game version would be a
  contract change; one delimited string keeps the event flat.
- **A station cache.** It can return stale values after a same-month ride replacement.
- **Stopping the station walk at the first empty slot.** The engine allows an empty slot before a used one (a reviewer's reading of the 0.5.5 engine source, not confirmed by this repo), so it
  could undercount stations; `ride.stations` is read once per snapshot and all 255 slots are walked.

## Consequences

- **The listed price is a stand-in awaiting the project owner's decision.** It differs from the amount charged when
  a guest used a free-ride voucher or the price changed between the charge and the poll (at most 20 ticks), and
  voucher boardings cannot be identified. The pricing model (NEXT 8, the roadmap's observational pricing
  model) must treat the field as the listed price. The build did not wait for the decision.
- **Boarding counts are lower bounds.** The benchmark's boarding coverage was 0.892 over the four car rides, with
  two rides at 0.857 and 0.826; the shortfall was not attributed. Coverage is judged by benchmark rule 7 at a
  threshold of 77%, set once after seeing this data (it began at a provisional 90%), so the pass at 77% shows the
  rest of the run is sound, not that 77% is independently right. All three runs captured the same 758 boardings, so
  this is one park's evidence.
- **Each seat keeps a guest's ID after the guest leaves** until another guest takes the seat (found when the first
  part 2 benchmark reported 93% repeated boarding rows). Comparing seat by seat, not guest by guest, is what keeps a
  leftover listing from counting as a boarding.
- **The reduction claim is a headless, one-park measure.** Run B's day-start ticks run no guest step, so the claim
  covers the day-start work only; its worst tick of any kind is a guest step, mostly the `guest` source (92.5% of
  the worst-tick time), whose inner cost was not analyzed.
- **The live-object test uses heap snapshots, not `v8.queryObjects`.** In Node 26.9.0 `queryObjects` returns 0 for
  objects made inside a `vm` context, which is where the stand-in game runs the plugin. The snapshot method counts
  objects alive after garbage collection by ID and is the stricter of the two (`plugin/test/allocation.test.mjs`).
- **Seeding is one tick of up to about 50 ms at each park load.** It lands in the warm-up period the benchmark
  never judges. Spreading it over 20 slices cost more in total and left the worst tick unchanged.
- **Garbage-collection pauses land in whichever step was running.** A worst-tick source names where time was
  spent, not what made the garbage.
- **The cohort is per session.** A reload starts an empty cohort. Seeded guests never join, because their arrival
  was not observed.
- **Five new event types and thirteen new `plugin_stats` fields** joined the contracts at version 1.3.0 (a minor
  bump). No staging model reads them yet (`docs/CONVENTIONS.md`, section 3).

## How we would know this is wrong

- A real-play check (part 3) or another park shows the 20-tick poll missing a material share of boardings, or
  boarding coverage below the 77% threshold.
- `lines_queued_max` approaches the 5,000-line cap on a busier park, or the continuous backlog fails benchmark
  rule 5 (more than 64 items pending).
- Day-start ticks or the guest steps push the worst tick past 10 ms on other hardware.
- The project owner rejects the listed price as the stand-in for price paid.
