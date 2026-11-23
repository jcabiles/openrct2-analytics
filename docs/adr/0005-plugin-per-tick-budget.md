# ADR 0005: Keep the 10 ms worst-tick and 1.25 ms average per-tick budget

- Date: 2026-09-28
- Status: Accepted; two judged windows that broke the worst-tick limit were accepted by the project owner on 2026-10-22 without changing it (ADR 0041).

## Context

The plugin cost test set two draft limits on 2026-09-27, measured against the game's 25 ms tick slot
at normal speed (40 ticks per second): a worst single tick of at most 10 ms, and an average of at most
1.25 ms per tick (5% of the slot). Two measurements bear on whether to keep them:

- **Headless**, normal speed, 3 valid 35-day runs on the 1,938-guest benchmark park: worst tick 95.6 ms
  and mean 1.43 ms per tick. Fails both limits.
- **Windowed real-game check**, played for 60 game days (about 13.5 minutes) at normal speed: mean
  0.9988 ms per tick, which passes the average limit; worst tick 57.122 ms, which fails the worst-tick
  limit. The player's own verdict was "smooth" — no hitch noticed, no notes — even though a 57 ms tick, more
  than five times the limit, went unnoticed during play. This run is informational, not a valid headless
  measurement run: a mid-session save reload restarted the plugin under the same session ID, duplicating
  2,922 `seq` values, and the daily-snapshot count was 52 of 60. See `docs/FINDINGS.md` for both rows.

## Decision

The project owner (2026-09-28) keeps the 10 ms worst-tick and 1.25 ms average per-tick limits unchanged.

## Rejected alternative

Loosen the worst-tick limit to "never overrun the 25 ms tick window." This would let the trial
schedules measured outside this test pass today. It was rejected because it leaves almost no margin
for bigger parks, slower machines, or the game's own work landing in the same tick window, and because
moving the pass line after seeing the results defeats the point of a pre-registered budget.

## Consequences

- The plugin cost test's combined verdict is FAIL: headless fails both limits, and the windowed check
  fails the worst-tick limit.
- The full-capture candidate slice (roadmap NEXT, problem 1) returns to problem framing. Its schedule
  must be redesigned — spreading work across ticks, capping events sent per tick, and locating the
  unexplained extra over-10-ms tick per game day are candidates — and every redesigned schedule must be
  measured at its real interval before a spec is written, not estimated by projection.
