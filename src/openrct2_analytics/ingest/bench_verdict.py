"""Combine individual benchmark run judgements into a fixed-rule verdict.

Besides passing or failing, the verdict decides two things the measured runs in
docs/architecture/benchmark.md act on: whether the boarding coverage threshold is due its
one calibration (guest completeness rule 7), and whether a failed per-tick limit is traced
by time to the five boarding guest-field reads (docs/architecture/benchmark.md, "Trace rule").
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass

from openrct2_analytics.ingest.bench_actions import VOID_PREFIX
from openrct2_analytics.ingest.bench_boardings import COVERAGE_FAILED
from openrct2_analytics.ingest.bench_guests import GuestReport, PeriodTimes
from openrct2_analytics.ingest.bench_judge import RunJudgement
from openrct2_analytics.ingest.capture_report import (
    MEAN_TICK_LIMIT_MS,
    WORST_TICK_LIMIT_MS,
    PluginCost,
)

REQUIRED_RUNS = 3
CALIBRATION_MIN_RIDE_RATIO = 0.70  # every car ride in every run, for the one calibration
GUEST_FIELDS = "guest_fields"  # the step kind of the five reads the fallback removes
TRACE_MIN_PERIODS = 2  # one failing period alone is treated as a stall
GUEST_RECORD_NAMES = (
    "refusals_by_type",
    "boardings_by_period",
    "boarding_capture_ratio",
    "guests_known_outside_park",
)


@dataclass(frozen=True)
class Verdict:
    """The fixed-rule result of combining all benchmark runs.

    Attributes:
        passed: Whether every required benchmark rule passed.
        runs: Judgements considered for this verdict, in input order.
        discarded: Invalid retry attempts, paired with their one-based run slot.
        worst_tick_ms: Largest per-run worst tick, or None when no run has a cost.
        mean_tick_ms: Largest per-run mean tick cost, or None when no run has a cost.
        reasons: Plain-words failures, in rule order.
        boarding_calibration_due: Whether the coverage threshold is due its one calibration.
        failure_traced_to_guest_fields: Whether the failure is traced to the guest-field
            reads; None when the verdict passed.
    """

    passed: bool
    runs: tuple[RunJudgement, ...]
    worst_tick_ms: float | None
    mean_tick_ms: float | None
    reasons: tuple[str, ...]
    boarding_calibration_due: bool
    failure_traced_to_guest_fields: bool | None
    discarded: tuple[tuple[int, RunJudgement], ...] = ()


def combine(
    runs: Sequence[RunJudgement], *, discarded: Sequence[tuple[int, RunJudgement]] = ()
) -> Verdict:
    """Combine the fixed number of benchmark runs into one verdict.

    Args:
        runs: Run judgements in benchmark-run order.
        discarded: Invalid retry attempts, paired with their one-based run slot.

    Returns:
        A verdict that uses the worst individual run for each cost measure.
    """
    run_tuple = tuple(runs)
    costs = [run.cost for run in run_tuple if run.cost is not None]
    worst_tick_ms = max((cost.worst_tick_ms for cost in costs), default=None)
    mean_tick_ms = max((cost.mean_tick_ms for cost in costs), default=None)
    reasons = _verdict_reasons(run_tuple, costs, worst_tick_ms, mean_tick_ms)
    reasons.extend(
        f"discarded attempt of run {slot} is void"
        for slot, attempt in discarded
        if is_void(attempt)
    )
    return Verdict(
        not reasons,
        run_tuple,
        worst_tick_ms,
        mean_tick_ms,
        tuple(reasons),
        bool(reasons) and _calibration_due(run_tuple),
        _traced_to_guest_fields(run_tuple, costs) if reasons else None,
        tuple(discarded),
    )


def is_void(run: RunJudgement) -> bool:
    """Return whether a run lost output, so its cost is not a speed result.

    A run is void when the emitter dropped a line, a write was partial, a work item was
    skipped, or the action workload check reported a buffer drop (a ``void:`` reason).
    A counter that is None (an unjudged attempt) does not make a run void.
    """
    counters = (run.lines_dropped_total, run.write_partial_total, run.work_items_skipped_total)
    lost = any(value is not None and value > 0 for value in counters)
    return lost or any(reason.startswith(VOID_PREFIX) for reason in run.completion_reasons)


def _calibration_due(runs: tuple[RunJudgement, ...]) -> bool:
    """Return whether a failed verdict is due the coverage threshold's one calibration.

    Guest completeness rule 7 in docs/architecture/benchmark.md: every failure in the verdict
    and its runs is a rule 7 (b) ratio failure, every car ride's ratio in every run is at least
    70%, and in every run the captured boardings before L equal the plugin's own counter exactly.
    """
    return len(runs) == REQUIRED_RUNS and all(_calibratable(run) for run in runs)


def _calibratable(run: RunJudgement) -> bool:
    """Return whether one run fails, if at all, only on rule 7 (b) with no capture loss."""
    cost, guests = run.cost, run.guests
    if not run.valid or cost is None or guests is None:
        return False
    if not (cost.worst_within_limit and cost.mean_within_limit):
        return False
    if any(not reason.startswith(COVERAGE_FAILED) for reason in run.completion_reasons):
        return False
    ratios = [ride.ratio for ride in guests.coverage.rides]
    high_enough = all(ratio is not None and ratio >= CALIBRATION_MIN_RIDE_RATIO for ratio in ratios)
    return high_enough and guests.boardings_before_last == guests.boarders_queued_total


def _traced_to_guest_fields(runs: tuple[RunJudgement, ...], costs: list[PluginCost]) -> bool:
    """Return whether a failed verdict's failure is traced by time to the guest-field reads.

    docs/architecture/benchmark.md, "Trace rule": only a verdict whose failures are all
    per-tick limits can be traced, and every failed limit must be. A worst-tick failure is
    traced when ``guest_fields`` holds more than half of the failing periods' summed
    worst-tick time and more than half in each of at least two of them; one such period alone
    is a stall. A mean failure is traced when each failing run's mean minus its guest-field
    time per tick is within the limit.
    """
    if len(runs) != REQUIRED_RUNS or not all(run.valid and run.complete for run in runs):
        return False
    if len(costs) != len(runs):
        return False
    traced = True
    if any(not cost.worst_within_limit for cost in costs):
        traced = _worst_traced(runs)
    if any(not cost.mean_within_limit for cost in costs):
        traced = traced and _mean_traced(runs)
    return traced


def _kind_ms(split: str | None) -> dict[str, float]:
    """Parse ``worst_tick_kind_ms`` (``name:ms`` pairs joined by ``|``); empty for None."""
    if not split:
        return {}
    pairs = (part.split(":") for part in split.split("|"))
    return {name: float(ms) for name, ms in pairs}


def _worst_traced(runs: tuple[RunJudgement, ...]) -> bool:
    """The worst-tick half of the trace rule, over every run's failing periods."""
    failing = [
        (period.worst_tick_ms, _kind_ms(period.worst_tick_kind_ms).get(GUEST_FIELDS, 0.0))
        for run in runs
        for period in run.periods
        if period.worst_tick_ms > WORST_TICK_LIMIT_MS
    ]
    mostly_fields = sum(1 for worst, fields in failing if fields > worst / 2)
    fields_total = sum(fields for _, fields in failing)
    return mostly_fields >= TRACE_MIN_PERIODS and fields_total > sum(w for w, _ in failing) / 2


def _mean_traced(runs: tuple[RunJudgement, ...]) -> bool:
    """The mean half of the trace rule: each failing run is within the limit without them."""
    for run in runs:
        if run.cost is None or run.cost.mean_within_limit:
            continue
        per_tick = _guest_fields_ms_per_tick(run.periods)
        if per_tick is None or run.cost.mean_tick_ms - per_tick > MEAN_TICK_LIMIT_MS:
            return False
    return True


def _guest_fields_ms_per_tick(periods: tuple[PeriodTimes, ...]) -> float | None:
    """The judged periods' summed guest-field time over their summed ticks."""
    fields = [period.guest_fields_ms_total for period in periods]
    ticks = sum(period.period_ticks for period in periods)
    if not periods or ticks == 0 or any(value is None for value in fields):
        return None
    return sum(value or 0.0 for value in fields) / ticks


def _verdict_reasons(
    runs: tuple[RunJudgement, ...],
    costs: list[PluginCost],
    worst_tick_ms: float | None,
    mean_tick_ms: float | None,
) -> list[str]:
    """Return combined-verdict failures in fixed rule order."""
    reasons: list[str] = []
    if len(runs) != REQUIRED_RUNS:
        reasons.append(f"needs {REQUIRED_RUNS} runs, got {len(runs)}")
    for position, run in enumerate(runs, start=1):
        if not run.valid:
            reasons.append(f"run {position} is not valid: {'; '.join(run.validity_reasons)}")
        if not run.complete:
            reasons.append(f"run {position} is not complete: {'; '.join(run.completion_reasons)}")
        if run.cost is None:
            reasons.append(f"run {position} has no cost")
        if is_void(run):
            reasons.append(f"run {position} is void")
    if any(is_void(run) for run in runs):
        return reasons  # a void run's cost is not a speed verdict
    if costs and any(not cost.worst_within_limit for cost in costs):
        reasons.append(f"worst tick {worst_tick_ms} ms is over the {WORST_TICK_LIMIT_MS} ms limit")
    if costs and any(not cost.mean_within_limit for cost in costs):
        reasons.append(f"mean tick {mean_tick_ms} ms is over the {MEAN_TICK_LIMIT_MS} ms limit")
    return reasons


def may_repeat(attempts: Sequence[RunJudgement]) -> bool:
    """Return whether the one benchmark slot may receive its retry.

    Args:
        attempts: Attempts for one run slot, in attempt order.

    Returns:
        True only for the first invalid attempt, unless it is void: a void run is reported
        and stops the build, not repeated.
    """
    return len(attempts) == 1 and not attempts[0].valid and not is_void(attempts[0])


def verdict_record(verdict: Verdict, conditions: Mapping[str, str]) -> dict[str, object]:
    """Build a JSON-ready record of a benchmark verdict.

    Args:
        verdict: Combined benchmark verdict to record.
        conditions: Caller-supplied facts that identify the benchmark conditions.

    Returns:
        A record containing only JSON-compatible values.
    """
    attempts = (*verdict.runs, *(attempt for _, attempt in verdict.discarded))
    return {
        "passed": verdict.passed,
        "void": any(is_void(attempt) for attempt in attempts),
        "reasons": list(verdict.reasons),
        "boarding_calibration_due": verdict.boarding_calibration_due,
        "failure_traced_to_guest_fields": verdict.failure_traced_to_guest_fields,
        "worst_tick_ms": verdict.worst_tick_ms,
        "mean_tick_ms": verdict.mean_tick_ms,
        "limits": {"worst_tick_ms": WORST_TICK_LIMIT_MS, "mean_tick_ms": MEAN_TICK_LIMIT_MS},
        "runs": [_run_record(run) for run in verdict.runs],
        "discarded": [
            {"slot": slot, **_run_record(attempt)} for slot, attempt in verdict.discarded
        ],
        "conditions": dict(conditions),
    }


def _run_record(run: RunJudgement) -> dict[str, object]:
    """Build the JSON-ready record for one run judgement."""
    cost = run.cost
    return {
        "valid": run.valid,
        "complete": run.complete,
        "reasons": list(run.reasons),
        "validity_reasons": list(run.validity_reasons),
        "completion_reasons": list(run.completion_reasons),
        "judged_ticks": None if cost is None else cost.judged_ticks,
        "worst_tick_ms": None if cost is None else cost.worst_tick_ms,
        "mean_tick_ms": None if cost is None else cost.mean_tick_ms,
        "worst_tick_session_id": None if cost is None else cost.worst_tick_session_id,
        "worst_tick_at_ticks": None if cost is None else cost.worst_tick_at_ticks,
        "worst_tick_offset_ticks": run.worst_tick_offset_ticks,
        "worst_tick_period_ticks": run.worst_tick_period_ticks,
        "work_units_total": run.work_units_total,
        "work_items_skipped_total": run.work_items_skipped_total,
        "lines_dropped_total": run.lines_dropped_total,
        "write_partial_total": run.write_partial_total,
        **_period_record(run.periods),
        **_guest_record(run.guests),
    }


def _all_or_none(values: list[float | None]) -> list[float] | None:
    """The values when every one is present, else None."""
    present = [value for value in values if value is not None]
    return present if values and len(present) == len(values) else None


def _period_record(periods: tuple[PeriodTimes, ...]) -> dict[str, object]:
    """The verdict's per-run fields from the judged periods' time fields."""
    sources: dict[str, float] = {}
    for period in periods:
        for name, ms in _kind_ms(period.worst_tick_kind_ms).items():
            sources[name] = sources.get(name, 0.0) + ms
    worst = [period.worst_tick_ms for period in periods]
    day_start = _all_or_none([period.worst_day_start_tick_ms for period in periods])
    lines = _all_or_none([period.lines_queued_max for period in periods])
    kinds = Counter(period.worst_step_kind for period in periods if period.worst_step_kind)
    return {
        "worst_step_kinds": dict(kinds),
        "worst_tick_ms_by_source": sources,
        "mean_period_worst_tick_ms": sum(worst) / len(worst) if worst else None,
        "mean_period_worst_day_start_tick_ms": None
        if day_start is None
        else sum(day_start) / len(day_start),
        "guest_fields_ms_per_tick": _guest_fields_ms_per_tick(periods),
        "lines_queued_max": None if lines is None else int(max(lines)),
    }


def _guest_record(guests: GuestReport | None) -> dict[str, object]:
    """The verdict's per-run fields from the guest report."""
    if guests is None:
        return dict.fromkeys(GUEST_RECORD_NAMES)
    coverage = guests.coverage
    return {
        "refusals_by_type": dict(guests.refusals_by_type),
        "boardings_by_period": [asdict(period) for period in guests.boardings_by_period],
        "boarding_capture_ratio": {
            "ratio": coverage.ratio,
            "rides": [asdict(ride) for ride in coverage.rides],
        },
        "guests_known_outside_park": guests.guests_known_outside_park,
    }
