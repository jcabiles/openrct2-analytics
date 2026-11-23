# ADR 0039: statements send the money already booked to the new month

- Date: 2026-10-20
- Status: Accepted

## Bottom line

The monthly statement now also carries `new_month_booked_tenths`, the money the game had already booked to
the new month when the plugin read it: the sum of index 0 of the 14 expenditure histories. The exact cash
check subtracts it, so the identity becomes: the change in (cash − loan − booked) from one statement to the
next equals the later statement's 14 lines, to the tenth. This replaces the claim in ADR 0008 that nothing
is yet booked to the new month at the day-1 reading. The price is one optional field, which moves all 13 contracts
(the envelope and the 12 event contracts) from 1.5.0 to 1.6.0 and the plugin from 0.5.0 to 0.6.0, and a re-convert of every older
landing set. Statements from earlier plugins count the field as 0, so old captures keep failing the check
exactly as they do today.

## Context

ADR 0008 read the statement in the day-1 callback and recorded why that moment looked safe: in all 14
month rollovers of the schema 0 capture the new month's index 0 was 0 in every type. It also named its own
failure sign: a consecutive pair failing the balance check in a longer run.

That sign appeared. The two-park capture of 2026-10-09 (nine chained sessions) fails the exact cash check on
11 of about 67 consecutive pairs (`docs/FINDINGS.md`, "Ledger reconciliation" and the 2026-10-09 two-park
cash row). The failures come as equal and opposite pairs, for example -$1.00 then +$1.00 for Park 1 in year
9, months 5 and 6. That is what a small amount `p(k)` booked to the new month before the reading produces:
the cash at the reading includes `p`, and the next statement's ledger also counts it, so the check's
difference for month k is `p(k-1) - p(k)`.

The suspected cause is the engine's order at a month start: the month-start tick shifts every expenditure
history (the new month becomes index 0), then lets guests buy things, and only then runs the `interval.day`
hook. This order comes from a second-hand read of `GameState.cpp` and `Scenario.cpp` at v0.5.6 and is
unverified against the source text. The arithmetic is exact and comes straight from the raw lines. The repo
already assumes the tick hook runs before the day callback (`plugin/src/work.ts`).

## Decision

| Decision | Choice |
|---|---|
| Field | `new_month_booked_tenths` on `finance_month`: the sum of index 0 of the 14 expenditure histories at the reading, an optional integer in tenths of a dollar, signed (a spending line can be positive after a refund). Staging converts it to `new_month_booked_usd`. |
| Corrected identity | The change in (cash − loan − booked) from the park's previous kept statement equals the later statement's 14 lines. `ARCHITECTURE.md` and the metric catalog state it. |
| Old statements | A statement without the field counts it as 0 (in `fct_park_month`, the one place the rule lives). Raw captures are append-only, so old captures are not fixed: they fail the exact test as before. The committed sample still passed when the field was added. |
| What the check stays | Exact, at severity `error` on every target. Nothing is loosened. |
| Mixed pairs | A pair whose earlier statement is old and whose later one carries the field fails exactly when the old reading already held new-month money; the other order fails exactly when the later old reading did. Both are no weaker than before. |
| Versions | All 13 contracts (the envelope and the 12 event contracts) move 1.5.0 to 1.6.0 together (a minor bump, ADR 0007); the plugin moves to 0.6.0 so rows from the fixed plugin can be told apart. |
| Older landing sets | Each is re-converted from its append-only raw files with `make convert DATA_SET=<set>` before `make contracts`, `make transform` or `make publish`, because staging reads `v1/finance_month.parquet` directly and `make publish` does not convert. `make pipeline` already converts first. |
| Superseded | The "Why that moment" row of ADR 0008. The rest of ADR 0008 stands. |

## Rejected alternatives

- **Cache the last tick's cash and read that.** It needs a per-tick read, which the plugin's cost budget
  (ADR 0005) is built to avoid, and it still misses money posted before the month shift on that tick.
- **Allow a tolerance in the cash test.** It would weaken an exact test to hide a known, explainable
  difference, and a real leak elsewhere could hide inside the tolerance.
- **Treat a missing field as "not checkable".** It would change the count of months checked and the
  committed site export, and it would let old captures stop failing without anyone having fixed them.

## Consequences

- **Why the schema 0 capture saw nothing.** If the suspected engine order is right (unverified at source), the
  leak appears only in a month where a guest buys something in the month-start tick, and the 14 rollovers of
  the schema 0 capture happened to have none, so index 0 was 0 each time. Chance, a game-version difference or
  a play-pattern difference is not ruled out. That is one park and one player (observational), not proof that
  the order never leaks. About 1 pair in 6 leaks in the two-park capture.
- **Old captures keep failing.** Any capture made before plugin 0.6.0 fails the exact test on the months that
  leaked, and stays that way.
- **A thin check on the committed sample.** With 3 statements the sample has 2 pairs, so it would pass the
  check about 70% of the time even without the field; its passing shows the field is wired through, not that
  the fix works.
- **One more field on the shared version line.** Adding it moves 13 contracts together, as ADR 0007 set out.
- **The mart cannot tell "sent as 0" from "not sent".** `plugin_version` in `stg_finance_month` still can.

## How we would know this is wrong

- A new capture from plugin 0.6.0 or later still fails the exact test: the amount booked before the reading
  is not all in index 0, or cash moves between the reading and the hook, and the field needs another look.
- The engine source shows the day hook runs before guests buy at a month start: the cause above would be
  wrong and the failures would need a new explanation.
- A longer run with the loan changing fails the check in a way the field does not explain: ADR 0008's
  open question about loan principal returns.
