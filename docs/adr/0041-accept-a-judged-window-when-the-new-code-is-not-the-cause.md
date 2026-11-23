# ADR 0041: accept the two failed judged benchmark windows of 2026-10-22

- Date: 2026-10-22.
- Status: Accepted 2026-10-22 (the project owner accepted these two windows). It does not amend ADR 0005's limits; a standing rule for later windows is a proposal that awaits the project owner's decision.

## Bottom line

The project owner accepted the two judged benchmark windows of 2026-10-22, whose verdicts printed FAILED on the worst-tick limit of ADR 0005. Both worst ticks were caused by the plugin's existing line-sending step (88.976 ms and 17.619 ms), the new action code added 0.280 ms and 0.243 ms to them, and every run's mean was under 1.25 ms. The verdicts were not changed, the judge code (`src/openrct2_analytics/ingest/bench_verdict.py`) still prints FAILED for them, and ADR 0005's 10 ms and 1.25 ms limits stand unchanged. Whether a similar excess in a later window should be accepted by a standing rule is proposed below, not decided.

## Context

The player-actions item added two hooks (`action.query`, `action.execute`) and a send step to the plugin. Two judged windows ran on 2026-10-22 on the same build, and both verdicts were FAILED on the worst-tick limit:

- Window 1: worst tick 89.306 ms (limit 10 ms), made of 88.976 ms in the plugin's existing line-sending step and 0.280 ms of action code (send step 0.187, execute hook 0.093, query hook none).
- Window 2, the re-run on the same build: worst tick 17.932 ms, made of 17.619 ms in the line-sending step and 0.243 ms of action code.
- Every run's mean was under 1.25 ms (0.368 to 0.780 ms). All six runs were valid and complete, with no dropped line and nothing discarded.

The fallback ladder's test (`Q + A < E`, query-hook time plus action time against the excess over 10 ms) held in both windows, so removing the query hook would not have changed either result. The measurements are in the 2026-10-22 rows of `docs/FINDINGS.md`. The project owner answered in chat on 2026-10-22, about these two windows: "Just pass anyway. I'm okay with this."

## Decision

1. **The two windows of 2026-10-22 are accepted by the project owner.** The verdicts stay FAILED. The project owner's words were: "Just pass anyway. I'm okay with this." The ruling covers these two windows only.
2. **The test the director applied was R25's `Q + A < E` on each tick over 10 ms** (the player-actions spec's fallback ladder): query-hook time plus action time was smaller than the excess over 10 ms in both windows, so the new code did not explain the excess. Window 1: worst tick 89.306 ms, line step 88.976 ms, action code 0.280 ms. Window 2: worst tick 17.932 ms, line step 17.619 ms, action code 0.243 ms. Every mean was under 1.25 ms.
3. **ADR 0005 is not amended.** Its limits still describe the measured budget and still apply to later windows.
4. **The judge does not implement any acceptance rule.** `bench_verdict.py` marks a window FAILED on any worst tick over 10 ms, and each FAILED verdict needs the project owner's acceptance.

## Proposal, awaiting the project owner's decision

A standing rule for later windows: accept a window when every run's mean is under 1.25 ms and the new code's share of each tick over 10 ms is under 10 ms, recording each such tick in `docs/FINDINGS.md`. Gain: a stall in an existing step that the new code does not cause would not block a merge. Cost: a real stall in the line-sending step would be recorded instead of blocking, and the judge would need a follow-up change to implement it. Until the project owner decides, nothing beyond the two windows above is accepted.

## Rejected alternative

Treat any tick over 10 ms as blocking the merge, with no acceptance. It was set aside for these two windows because both over-limit ticks were in a step the new code does not change (the line-sending step), so blocking would have halted the build for a stall the new code did not cause. Slow ticks also occurred before the new code: ADR 0005 records a 57.122 ms windowed tick, and `docs/FINDINGS.md` records 11.25 ms and 9.640 ms runs of the same earlier code.


## Consequences

- **Gain:** a stall in an existing step that the new code does not cause did not block the merge, and the player-actions item can proceed to the real-play check.
- **Cost:** a real stall in the line-sending step is recorded instead of blocking; the plugin's worst tick on this build reached 89.306 ms in one run. Every such window still needs an explicit acceptance.
- **Where the branch stands against the per-tick budget (repo invariant 8):** the means are within budget (highest 0.780 ms against 1.25 ms); the worst-tick limit of 10 ms was exceeded in one run of each window by the existing line step, and those two windows are accepted by the project owner.
- **Follow-up:** investigate the line-sending stall; decide the proposal above. Observational: one benchmark park copy, one machine, headless, no player.
