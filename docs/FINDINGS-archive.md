# Findings archive

Rows and sections moved out of `docs/FINDINGS.md` on 2026-10-08 to keep it near the 500-line guide. Text is unchanged.
Nothing here is a current measurement.

### Projections for gentler schedules

**Superseded (2026-09-29): a redesigned schedule has since been measured; see the rows dated 2026-09-29
and the section "Capture schedule re-test". Kept as the record of what was projected.**

These are **projections, not measurements**: they divide a measured cost per call by a longer interval.
They are optimistic, because the measured cost of one guest pass rises as the gap between passes grows
(see the row on why the same scan costs different amounts), and because a pass that is not itself split
across ticks lands entirely in the one tick it runs, no matter how rarely it is called — the mean-per-tick
projections for `guest_scan` below say nothing about the worst tick unless the scan is also spread. Trial runs made outside this
test (kept in the project folder's notes, not part of this record) measured two such schedules at 2 to 4 times
these projections, so read every projection here as a lower bound. Nothing
here chooses the full capture's design; that is the project owner's decision when the lane returns to problem framing.

| Change | Basis | Projection |
| ------ | ----- | ---------- |
| `guest_scan` every 120 ticks instead of every 20 (still one tick per pass) | 24.87 ms per pass over 120 ticks | mean 0.207 ms per tick, from 1.244; worst tick still at least 24.87 ms, unmeasured whether split |
| `guest_scan` once per game day (about 518 ticks, still one tick per pass) | 24.87 ms per pass over a game day | mean 0.048 ms per tick, from 1.244; worst tick still at least 24.87 ms, unmeasured whether split |
| `boarding_poll` every 40 ticks instead of every 20 | 0.98 ms per poll over 40 ticks | mean 0.024 ms per tick, from 0.049 |
| The daily snapshot's build and typical send flush spread over 20 ticks, mean vs mean | mean build 22.57 ms (full-2) + typical send flush 27.1 ms (full-2: 948 ms ÷ 35 days), split 20 ways | mean 2.48 ms per tick (during the 20-tick window), from 0.044 + 0.052 |
| The daily snapshot's build and worst send flush spread over 20 ticks, worst vs worst | worst build 44.8 ms (full-1) + worst send flush 63.6 ms (full-1), split 20 ways | worst tick about 5.42 ms (during the 20-tick window), from 95.6 |

Taken together, a schedule with the guest scan every 120 ticks, boarding polled every 40, and the daily
snapshot spread over 20 ticks projects a mean of about **0.33 ms per tick** (0.207 + 0.024 + 0.096, the
last from splitting the snapshot's mean build and typical send flush, 22.57 + 27.1 ms, across the roughly
518 ticks of a game day) — inside the average limit, but this arithmetic is optimistic per the caveat
above. The worst tick is **not** inside its limit: as scheduled, the guest scan still runs in one tick and
costs at least 24.87 ms there (full-2's measured pass mean), so this schedule fails the 10 ms worst-tick
limit outright. The scan itself would have to be split across ticks too to fit, and the only measured
split (20 ticks, passes back to back) cost 52.56 ms per pass — about 2.6 ms per tick of the pass
(52.56 ÷ 20) — worse than the unspread mean, not better (see the row above on spreading the scan). No
schedule that fits both limits has been measured (as of 2026-09-28).
