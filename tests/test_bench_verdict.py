from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from openrct2_analytics.ingest.bench_guests import PeriodTimes
from openrct2_analytics.ingest.bench_judge import RunFacts, RunJudgement, judge_run
from openrct2_analytics.ingest.bench_verdict import combine, may_repeat, verdict_record
from openrct2_analytics.ingest.capture_report import PluginCost
from openrct2_analytics.ingest.convert import convert
from tests.bench_plant import Plant, clean_plant, thin_boardings
from tests.test_convert import SNAPSHOT_PAYLOAD, event, land
from tests.test_convert_event_types import RIDE_PAYLOAD, START_PAYLOAD, typed_event

TICKS_PER_DAY = 100
JUDGED_DAYS = 2
WORK_COUNTERS: dict[str, object] = {
    "work_units_total": 12,
    "work_items_skipped_total": 0,
    "work_queue_length": 0,
    "work_items_failed_total": 0,
    "worst_step_ms": 0.5,
    "worst_step_kind": "ride",
    "worst_tick_kind_ms": "ride:0.200|day_callback:0.050",
    "worst_day_start_tick_ms": 0.25,
    "guest_fields_ms_total": 2.0,
    "continuous_items_pending": 0,
    "lines_queued_max": 30,
    "guests_known": 9,
    "guests_known_in_park": SNAPSHOT_PAYLOAD["guests_in_park"],
    "arrivals_recorded_total": 0,
    "boarders_queued_total": 0,
}


def _judgement(
    *,
    valid: bool = True,
    complete: bool = True,
    worst_tick_ms: float | None = 5.0,
    mean_tick_ms: float = 0.5,
    validity_reasons: tuple[str, ...] = (),
    completion_reasons: tuple[str, ...] = (),
) -> RunJudgement:
    cost = (
        None
        if worst_tick_ms is None
        else PluginCost(100, worst_tick_ms, "session", 125, mean_tick_ms)
    )
    return RunJudgement(
        valid,
        complete,
        validity_reasons,
        completion_reasons,
        cost,
        25,
        100,
        10,
        0,
        0,
        0,
        (),
        None,
    )


def _scripted_run(raw: Path, session: str) -> None:
    """Land one complete run's raw lines: a warm-up day and ``JUDGED_DAYS`` judged days."""
    lines = [typed_event(session, 1, "session_start", START_PAYLOAD)]
    for day in range(JUDGED_DAYS + 1):
        start = day * TICKS_PER_DAY
        stats = {
            "period_start_ticks": start,
            "period_end_ticks": start + TICKS_PER_DAY,
            "period_ticks": TICKS_PER_DAY,
            "worst_tick_at_ticks": start + 25,
            "warmup": day == 0,
            "worst_tick_ms": 0.25,
            "boarding_polls_total": day * 5,
            **WORK_COUNTERS,
        }
        ride = {**RIDE_PAYLOAD, "game_ticks_elapsed": start + TICKS_PER_DAY // 2}
        lines += [
            event(session, len(lines) + 1, "plugin_stats", game_ticks_elapsed=start + 100, **stats),
            event(session, len(lines) + 2, game_ticks_elapsed=start + TICKS_PER_DAY),
            typed_event(session, len(lines) + 3, "ride_snapshot", ride),
        ]
    land(raw, *lines)


def test_three_runs_converted_from_raw_lines_pass_the_verdict(tmp_path: Path) -> None:
    judgements = []
    for slot in (1, 2, 3):
        raw, parquet = tmp_path / f"raw-{slot}", tmp_path / f"parquet-{slot}"
        _scripted_run(raw, f"run-{slot}")
        assert convert(raw, parquet).ok
        facts = RunFacts(parquet, JUDGED_DAYS, "a" * 40, "a" * 40, 0)
        judgements.append(judge_run(facts))

    assert [(j.valid, j.complete) for j in judgements] == [(True, True)] * 3
    assert all(j.reasons == () for j in judgements)
    verdict = combine(judgements)
    assert verdict.passed and verdict.reasons == ()
    assert verdict.failure_traced_to_guest_fields is None
    assert verdict.boarding_calibration_due is False
    run = runs_of(verdict_record(verdict, {}))[0]
    assert run["worst_step_kinds"] == {"ride": 2}
    assert run["worst_tick_ms_by_source"] == {"ride": 0.4, "day_callback": 0.1}
    assert run["mean_period_worst_tick_ms"] == 0.25
    assert run["mean_period_worst_day_start_tick_ms"] == 0.25
    assert run["guest_fields_ms_per_tick"] == 0.02
    assert run["lines_queued_max"] == 30
    assert run["guests_known_outside_park"] == 2
    assert run["refusals_by_type"] == dict.fromkeys(REFUSALS, 0)
    assert run["boardings_by_period"] == [{"customers_rise": 0, "boardings": 0}] * 2
    assert run["boarding_capture_ratio"] == {"ratio": None, "rides": []}


def test_combine_three_qualified_runs_uses_cost_maxima() -> None:
    verdict = combine(
        [
            _judgement(worst_tick_ms=4.0, mean_tick_ms=0.4),
            _judgement(worst_tick_ms=6.0, mean_tick_ms=0.6),
            _judgement(worst_tick_ms=5.0, mean_tick_ms=0.8),
        ]
    )
    assert (
        verdict.passed
        and verdict.worst_tick_ms == 6.0
        and verdict.mean_tick_ms == 0.8
        and verdict.reasons == ()
    )


def test_combine_cost_boundaries_and_overages() -> None:
    assert combine([_judgement(worst_tick_ms=10.0, mean_tick_ms=1.25)] * 3).passed
    assert not combine([_judgement(worst_tick_ms=10.001)] * 3).passed
    assert not combine([_judgement(mean_tick_ms=1.2501)] * 3).passed


def test_combine_requires_exactly_three_runs() -> None:
    assert "needs 3 runs" in combine([_judgement()] * 2).reasons[0]
    assert "needs 3 runs" in combine([_judgement()] * 4).reasons[0]


def test_combine_reports_validity_and_completion_separately() -> None:
    verdict = combine(
        [
            _judgement(
                valid=False,
                complete=False,
                validity_reasons=("fixture changed",),
                completion_reasons=("queue remains",),
            )
        ]
        * 3
    )
    assert verdict.reasons[0] == "run 1 is not valid: fixture changed"
    assert verdict.reasons[1] == "run 1 is not complete: queue remains"


def test_combine_uses_the_worst_run_not_an_average() -> None:
    verdict = combine(
        [
            _judgement(worst_tick_ms=1.0),
            _judgement(worst_tick_ms=1.0),
            _judgement(worst_tick_ms=10.4),
        ]
    )
    assert not verdict.passed and verdict.worst_tick_ms == 10.4


def test_may_repeat_only_allows_one_invalid_attempt() -> None:
    invalid, incomplete = _judgement(valid=False), _judgement(complete=False)
    assert may_repeat([invalid]) and not may_repeat([_judgement()]) and not may_repeat([incomplete])
    assert not may_repeat([invalid, invalid]) and not may_repeat([])


def _with_counters(run: RunJudgement, **counters: int | None) -> RunJudgement:
    return replace(run, **counters)  # type: ignore[arg-type]  # names are loss counters


VOID_COUNTERS = ["lines_dropped_total", "write_partial_total", "work_items_skipped_total"]


@pytest.mark.parametrize("counter", VOID_COUNTERS)
def test_a_void_run_is_reported_void_and_its_cost_is_not_a_speed_failure(counter: str) -> None:
    void_slow = _with_counters(_judgement(worst_tick_ms=12.0, mean_tick_ms=2.0), **{counter: 1})

    verdict = combine([void_slow, _judgement(), _judgement()])

    assert not verdict.passed
    assert "run 1 is void" in verdict.reasons
    assert not any(reason.startswith(("worst tick", "mean tick")) for reason in verdict.reasons)
    assert verdict_record(verdict, {})["void"] is True


def test_the_worst_tick_line_returns_when_no_run_is_void() -> None:
    verdict = combine([_judgement(worst_tick_ms=12.0), _judgement(), _judgement()])

    assert any(reason.startswith("worst tick") for reason in verdict.reasons)
    assert verdict_record(verdict, {})["void"] is False


def test_a_run_made_void_by_the_workload_check_is_void() -> None:
    void = _judgement(complete=False, completion_reasons=("void: emitter dropped lines",))

    assert "run 1 is void" in combine([void, _judgement(), _judgement()]).reasons


@pytest.mark.parametrize("counter", VOID_COUNTERS)
def test_a_void_invalid_attempt_is_not_repeated_and_a_void_discard_fails_the_verdict(
    counter: str,
) -> None:
    void_invalid = _with_counters(_judgement(valid=False), **{counter: 1})

    assert not may_repeat([void_invalid])
    verdict = combine([_judgement()] * 3, discarded=((1, void_invalid),))
    assert verdict.passed is False
    assert "discarded attempt of run 1 is void" in verdict.reasons
    assert verdict_record(verdict, {})["void"] is True


def test_an_unjudged_attempt_with_no_counters_stays_retryable() -> None:
    unjudged = _with_counters(
        _judgement(valid=False, worst_tick_ms=None), **dict.fromkeys(VOID_COUNTERS)
    )

    assert may_repeat([unjudged])


def test_verdict_record_is_json_ready_and_has_no_paths() -> None:
    conditions = {"fixture_sha1_prefix": "abc123", "machine": "test", "game_version": "v1"}
    record = verdict_record(combine([_judgement()] * 3), conditions)
    assert json.loads(json.dumps(record)) == record and record["conditions"] == conditions
    assert not _contains_path(record)


def test_verdict_record_includes_discarded_invalid_attempt() -> None:
    discarded = _judgement(valid=False, validity_reasons=("fixture changed",))
    verdict = combine([_judgement()] * 3, discarded=((2, discarded),))

    record = verdict_record(verdict, {})

    assert verdict.passed
    assert record["discarded"] == [
        {
            "slot": 2,
            "valid": False,
            "complete": True,
            "reasons": ["fixture changed"],
            "validity_reasons": ["fixture changed"],
            "completion_reasons": [],
            "judged_ticks": 100,
            "worst_tick_ms": 5.0,
            "mean_tick_ms": 0.5,
            "worst_tick_session_id": "session",
            "worst_tick_at_ticks": 125,
            "worst_tick_offset_ticks": 25,
            "worst_tick_period_ticks": 100,
            "work_units_total": 10,
            "work_items_skipped_total": 0,
            "lines_dropped_total": 0,
            "write_partial_total": 0,
            "worst_step_kinds": {},
            "worst_tick_ms_by_source": {},
            "mean_period_worst_tick_ms": None,
            "mean_period_worst_day_start_tick_ms": None,
            "guest_fields_ms_per_tick": None,
            "lines_queued_max": None,
            "refusals_by_type": None,
            "boardings_by_period": None,
            "boarding_capture_ratio": None,
            "guests_known_outside_park": None,
        }
    ]


def test_verdict_record_includes_period_and_separate_reason_lists() -> None:
    run = replace(
        _judgement(
            valid=False,
            complete=False,
            validity_reasons=("fixture changed",),
            completion_reasons=("queue remains",),
        ),
        worst_tick_period_ticks=200,
    )
    record = verdict_record(combine([run] * 3), {})

    runs = record["runs"]
    assert isinstance(runs, list)
    entry = runs[0]
    assert isinstance(entry, dict)
    assert entry["worst_tick_period_ticks"] == 200
    assert entry["validity_reasons"] == ["fixture changed"]
    assert entry["completion_reasons"] == ["queue remains"]
    assert json.loads(json.dumps(record)) == record and not _contains_path(record)


def _contains_path(value: object) -> bool:
    if isinstance(value, Path):
        return True
    if isinstance(value, dict):
        return any(_contains_path(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_path(item) for item in value)
    return False


def runs_of(record: dict[str, object]) -> list[dict[str, object]]:
    runs = record["runs"]
    assert isinstance(runs, list)
    return runs


REFUSALS = (
    "cant_afford_ride",
    "bad_value",
    "not_paying",
    "intense",
    "more_thrilling",
    "sickening",
    "not_safe",
    "queuing_ages",
    "not_while_raining",
)


# ---- the calibration rule's planted cases: each run fails only rule 7 (b) ----


def _planted_verdict(tmp_path: Path, plant: Plant) -> tuple[bool, bool]:
    """Judge three copies of ``plant`` at the provisional 0.90 and combine them."""
    runs = [
        judge_run(
            RunFacts(
                plant.write(tmp_path / f"run-{slot}"), plant.judged_days, "a" * 40, "a" * 40, 0
            ),
            coverage_threshold=0.90,
        )
        for slot in (1, 2, 3)
    ]
    assert all(len(run.completion_reasons) == 1 for run in runs), [r.reasons for r in runs]
    verdict = combine(runs)
    return verdict.passed, verdict.boarding_calibration_due


def _ratios_075_to_085() -> Plant:
    """Ride 1 keeps 0.80 of its window's boardings and ride 2 keeps 0.75."""
    plant = clean_plant()
    thin_boardings(plant, ride=1, per_day=6, days=range(3, 14))
    thin_boardings(plant, ride=2, per_day=5, days=range(3, 13))
    return plant


def test_a_near_empty_capture_is_not_due_calibration(tmp_path: Path) -> None:
    plant = clean_plant()
    plant.tables["guest_boarded"] = plant.rows("guest_boarded")[:1]
    plant.last["boarders_queued_total"] = 1

    assert _planted_verdict(tmp_path, plant) == (False, False)


def test_ride_ratios_of_075_to_085_with_the_counter_equal_to_the_rows_are_due(
    tmp_path: Path,
) -> None:
    assert _planted_verdict(tmp_path, _ratios_075_to_085()) == (False, True)


def test_the_same_ratios_with_boarders_still_pending_are_not_due(tmp_path: Path) -> None:
    plant = _ratios_075_to_085()
    plant.last["boarders_queued_total"] = int(str(plant.last["boarders_queued_total"])) + 2
    plant.last["continuous_items_pending"] = 2  # within rule 4's allowance

    assert _planted_verdict(tmp_path, plant) == (False, False)


# ---- the trace rule's planted cases ----


def _period(worst: float, split: str, guest_fields: float = 0.0) -> PeriodTimes:
    return PeriodTimes(100, worst, "ride", split, 1.0, guest_fields, 10)


def _worst_failure(*failing: PeriodTimes) -> bool | None:
    passing = _period(2.0, "ride:2.000")
    runs = [
        replace(_judgement(worst_tick_ms=max(p.worst_tick_ms for p in failing)), periods=failing),
        replace(_judgement(worst_tick_ms=2.0), periods=(passing,)),
        replace(_judgement(worst_tick_ms=2.0), periods=(passing,)),
    ]
    return combine(runs).failure_traced_to_guest_fields


def test_a_worst_tick_dominated_by_ride_time_is_not_traced() -> None:
    assert _worst_failure(_period(10.5, "ride:10.000|guest_fields:0.500")) is False


def test_one_stalled_period_mostly_guest_fields_is_not_traced() -> None:
    assert _worst_failure(_period(11.0, "guest_fields:9.000|ride:2.000")) is False


def test_two_periods_mostly_boarder_lookups_are_not_traced() -> None:
    lookups = _period(11.0, "boarder_read:9.000|guest_fields:0.100|ride:1.900")
    assert _worst_failure(lookups, lookups) is False


def test_two_periods_each_mostly_guest_fields_are_traced() -> None:
    fields = _period(11.0, "guest_fields:6.000|ride:5.000")
    assert _worst_failure(fields, fields) is True


def test_two_periods_mostly_guest_fields_are_not_traced_when_the_summed_time_is_mostly_rides() -> (
    None
):
    # Guest fields hold 12 of the 52 ms summed over the failing periods, under half.
    fields = _period(11.0, "guest_fields:6.000|ride:5.000")
    assert _worst_failure(fields, fields, _period(30.0, "ride:30.000")) is False


@pytest.mark.parametrize(("mean_tick_ms", "traced"), [(1.4, True), (1.6, False)])
def test_a_mean_failure_is_traced_when_the_mean_without_guest_fields_is_within_limit(
    mean_tick_ms: float, traced: bool
) -> None:
    # 20 ms of guest-field reads over 100 ticks is 0.2 ms per tick.
    periods = (_period(2.0, "ride:2.000", guest_fields=20.0),)
    runs = [replace(_judgement(mean_tick_ms=mean_tick_ms), periods=periods)] + [_judgement()] * 2
    assert combine(runs).failure_traced_to_guest_fields is traced


def test_a_failure_that_is_not_a_limit_is_never_traced() -> None:
    fields = _period(11.0, "guest_fields:6.000|ride:5.000")
    runs = [
        replace(_judgement(worst_tick_ms=11.0), periods=(fields, fields)),
        _judgement(complete=False, completion_reasons=("queue remains",)),
        _judgement(),
    ]
    verdict = combine(runs)
    assert verdict.failure_traced_to_guest_fields is False
    assert verdict_record(verdict, {})["failure_traced_to_guest_fields"] is False
