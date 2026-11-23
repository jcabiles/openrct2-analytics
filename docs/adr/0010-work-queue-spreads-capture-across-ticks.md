# ADR 0010: work queue spreads capture across ticks

- Date: 2026-10-02
- Status: Accepted

## Bottom line

The plugin uses one oldest-first work queue for queued socket lines and capture
items, with a 4 ms allowance over all plugin time in a tick. Daily events stay
direct; the day callback queues only new capture work. A step is never cut
short, and a new day skips and counts unfinished items from the old day rather
than carrying them forward. The measured full-capture part 1 benchmark passed:
the worst tick was 5.162 ms and the highest mean was 0.0286 ms per tick,
against 10 ms and 1.25 ms limits (`docs/FINDINGS.md`, "Full capture, part 1:
benchmark").

## Context

The plugin must capture daily ride snapshots without concentrating their cost
in the day callback. This change adds creation order to the line queue and
lets `timing.ts` expose `tickMsSoFar`, the plugin time spent in the open tick.
A separate allowance for only new queue work would miss earlier plugin work in
the same tick.

## Decision

| Decision | Choice |
|---|---|
| Allowance | `plugin/src/work.ts` starts no further step once all plugin time in the tick reaches 4 ms. |
| Order | Lines and task items share one creation-order counter; the oldest pending step runs first. |
| Day callback | Existing daily events remain direct. It queues new ride work, which `interval.tick` performs. |
| Overshoot | A pending queue runs at least one step, but no step is interrupted; overshoot is at most one step. |
| New day | Unfinished prior-day items are skipped and added to `work_items_skipped_total`, so work cannot accumulate across days. |

## Rejected alternatives

- **Give the runner its own 4 ms budget.** Earlier callbacks could already
  have spent material plugin time in that tick.
- **Send all daily events through the queue.** The established daily events do
  not need the new scheduling path; only new capture work does.
- **Carry unfinished ride work into later days.** Backlog would make a daily
  snapshot increasingly stale and unbounded.

## Consequences

- The observed hook order is `interval.tick` before `interval.day` when both
  run. This is an inference: the day callback stayed below the 4 ms allowance,
  so a tick hook after it would have started that day's ride snapshots on the
  same tick; none carried that tick. Fifteen of 105 judged periods had a
  worst tick below 4 ms, bounding the day callback's tick there, and no
  period's worst tick was the day callback's own. The day callback's time
  therefore does not come out of that tick's allowance.
- `timing.ts` starts a fresh bucket if a same-tick callback begins more than
  100 ms after its bucket opened. Thus a day callback over 100 ms opens a fresh
  timing bucket for a same-tick tick hook. Under the observed hook order, no
  tick hook follows that day callback on the same tick, so this matters only if
  that order is wrong. The period records the larger bucket, not their sum, so
  the worst tick would be under-reported. This is accepted only for a callback
  already ten times the 10 ms tick limit.
- The bounded `flush()` in the day callback, the save callback and the 5-second
  reconnect interval hands lines off directly, outside the allowance and ahead
  of pending work items. This is by design: lines must keep moving while the
  game is paused, and a save made just before a quit must still hand off its
  `save_written` event. Their time adds to the tick's. Each benchmark run
  included one autosave inside its judged window (`docs/FINDINGS.md`, "Full
  capture, part 1: benchmark"). Because `seq` is stamped at hand-off (ADR
  0007), the save's cut stays exact.
- The line-queue cap rose from 1,000 to 5,000 (`QUEUE_MAX_LINES` in
  `plugin/src/emit.ts`, the probe's measured bound), replacing the figure ADR
  0007 states.
- The benchmark's zero skipped items and zero queue length show that its daily
  ride work completed before the next day, but do not prove that for other
  parks or hardware.

## How we would know this is wrong

- A benchmark or real-play measurement exceeds the tick limits because steps
  run too long or the allowance omits callback time.
- Work is skipped routinely on a target park, making daily snapshots
  materially incomplete.
- Engine behavior shows a different hook order, invalidating the timing
  interpretation above.
