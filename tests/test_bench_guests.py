"""The guest completeness rules (docs/architecture/benchmark.md) on planted runs.

Each test starts from ``tests/bench_plant.py``'s clean run, which passes, breaks one thing and
judges the run with the real judge.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from openrct2_analytics.ingest.bench_boardings import (
    BOARDINGS_ABOVE,
    COVERAGE_FAILED,
    Coverage,
    RideCoverage,
)
from openrct2_analytics.ingest.bench_guests import COVERAGE_THRESHOLD, NEW_STATS_COLUMNS
from openrct2_analytics.ingest.bench_judge import RunFacts, RunJudgement, judge_run
from tests.bench_plant import (
    ADMISSIONS,
    CAR_RIDES,
    GUEST_FILES,
    IN_PARK,
    JUDGED_DAYS,
    SESSION,
    TICKS,
    Plant,
    Row,
    clean_plant,
    thin_boardings,
)


def _only(judgement: RunJudgement, *fragments: str) -> None:
    """The run is valid and fails completeness exactly on reasons containing ``fragments``."""
    assert judgement.valid, judgement.validity_reasons
    reasons = judgement.completion_reasons
    assert len(reasons) == len(fragments), reasons
    for reason, fragment in zip(reasons, fragments, strict=True):
        assert fragment in reason, reasons


@pytest.fixture(name="plant")
def plant_fixture() -> Plant:
    return clean_plant()


# ---- the clean run ----


def test_the_clean_run_passes_and_reports_its_guests(plant: Plant, tmp_path: Path) -> None:
    judgement = plant.judge(tmp_path)

    assert judgement.valid and judgement.complete, judgement.reasons
    guests = judgement.guests
    assert guests is not None
    assert guests.coverage == Coverage(
        1.0, (RideCoverage(1, 1, 330, 330, 1.0), RideCoverage(2, 2, 200, 200, 1.0))
    )
    assert guests.refusals_by_type["bad_value"] == 2 and guests.refusals_by_type["intense"] == 1
    assert len(guests.refusals_by_type) == 9 and guests.refusals_by_type["not_safe"] == 0
    assert guests.guests_known_outside_park == 0
    assert guests.boardings_before_last == guests.boarders_queued_total == 750
    # Period 1 is each ride's first snapshot; later periods gain 60 class-ride customers a day.
    first, second = guests.boardings_by_period[:2]
    assert (first.customers_rise, first.boardings) == (0, 50)
    assert (second.customers_rise, second.boardings) == (60, 50)
    assert len(judgement.periods) == JUDGED_DAYS and judgement.periods[0].worst_step_kind == "ride"


# ---- the planted runs: each benchmark rule fails on a planted defect (ADR 0018, FINDINGS) ----


def test_half_the_arrivals_deleted_fails_rules_4_and_6(plant: Plant, tmp_path: Path) -> None:
    plant.keep("guest_arrived", lambda row: int(str(row["guest_key"])) % 2 == 0)

    _only(plant.judge(tmp_path), "do not account for", "new admissions")


def test_half_the_boardings_deleted_fails_rule_4(plant: Plant, tmp_path: Path) -> None:
    plant.keep("guest_boarded", lambda row: int(str(row["seq"])) % 2 == 0)

    reasons = plant.judge(tmp_path).completion_reasons
    assert "do not account for" in reasons[0]


def test_no_boardings_while_customers_rise_fails_rule_7a(plant: Plant, tmp_path: Path) -> None:
    plant.tables["guest_boarded"] = []
    plant.last["boarders_queued_total"] = 0

    reasons = plant.judge(tmp_path).completion_reasons
    assert "judged row 2 gained 60 ride customers with no guest_boarded row" in reasons[0]


def test_one_boarding_against_hundreds_of_customers_fails_only_rule_7b(
    plant: Plant, tmp_path: Path
) -> None:
    plant.tables["guest_boarded"] = plant.rows("guest_boarded")[:1]
    plant.last["boarders_queued_total"] = 1

    _only(plant.judge(tmp_path), COVERAGE_FAILED)


def _judge_at_the_calibrated_threshold(plant: Plant, root: Path) -> RunJudgement:
    """Judge with the shipped default, not the provisional 0.90 that ``Plant.judge`` plants."""
    return judge_run(RunFacts(plant.write(root), plant.judged_days, "a" * 40, "a" * 40, 0))


def _plant_with_window_boardings(kept: int) -> Plant:
    """The clean run, thinned so exactly ``kept`` of its 530 windowed boardings remain."""
    plant = clean_plant()
    dropped = 530 - kept
    thin_boardings(plant, ride=1, per_day=dropped // 11, days=range(3, 14))  # 11 window days
    thin_boardings(plant, ride=2, per_day=1, days=range(3, 3 + dropped % 11))
    return plant


def test_the_calibrated_threshold_is_77_percent() -> None:
    assert COVERAGE_THRESHOLD == 0.77  # noqa: PLR2004


def test_coverage_just_below_the_calibrated_threshold_fails_only_rule_7b(tmp_path: Path) -> None:
    # 408 / 530 = 0.7698
    _only(
        _judge_at_the_calibrated_threshold(_plant_with_window_boardings(408), tmp_path),
        COVERAGE_FAILED,
    )


def test_coverage_at_the_calibrated_threshold_passes(tmp_path: Path) -> None:
    # 409 / 530 = 0.7717
    judgement = _judge_at_the_calibrated_threshold(_plant_with_window_boardings(409), tmp_path)

    assert judgement.valid and judgement.complete, judgement.reasons


def test_a_carless_ride_type_is_not_judged_for_coverage(plant: Plant, tmp_path: Path) -> None:
    # The clean run's maze gains customers with no boarding and passes; as a car ride it fails.
    for row in plant.rows("ride_snapshot"):
        if row["ride_id"] == 3:  # noqa: PLR2004
            row["ride_type"] = 52

    _only(plant.judge(tmp_path), COVERAGE_FAILED)


def test_a_car_ride_window_under_10_days_cannot_be_judged(tmp_path: Path) -> None:
    # 14 judged days leave ride 2 (lag 2) a window of 13 - 2 - 2 = 9 game days.
    _only(clean_plant(14).judge(tmp_path), "ride 2's lagged boarding window is 9 game days")


def _append_after_last(plant: Plant, table: str, rows: list[Row]) -> None:
    """Append ``rows`` with ``seq`` after every row, so rule 4's accounting is unchanged."""
    seq = max(int(str(row["seq"])) for table_rows in plant.tables.values() for row in table_rows)
    plant.rows(table).extend(
        {**row, "session_id": SESSION, "seq": seq + n} for n, row in enumerate(rows, start=1)
    )


def _boardings(ride: int, ticks: list[int], plant: Plant) -> list[Row]:
    after = int(str(plant.last["game_ticks_elapsed"])) + 1
    return [{"ride_id": ride, "detected_at_ticks": t, "game_ticks_elapsed": after} for t in ticks]


def test_seated_guests_reported_at_every_poll_fail_only_rule_7c(
    plant: Plant, tmp_path: Path
) -> None:
    # Run B's pattern: a car ride whose customers never rise, with the same 10 seated guests
    # reported as new boarders at every 20-tick poll.
    stuck = [
        {**row, "ride_id": 5, "total_customers": 2000, "guests_on_ride": 0}
        for row in plant.rows("ride_snapshot")
        if row["ride_id"] == 1
    ]
    _append_after_last(plant, "ride_snapshot", stuck)
    polls = [tick for tick in range(TICKS, (JUDGED_DAYS + 1) * TICKS, 20) for _ in range(10)]
    _append_after_last(plant, "guest_boarded", _boardings(5, polls, plant))

    _only(plant.judge(tmp_path), f"{BOARDINGS_ABOVE} 1030 boardings against 530 lagged customers")


@pytest.mark.parametrize(("added", "fails"), [(212, False), (265, False), (266, True)])
def test_boardings_more_than_150_percent_of_lagged_customers_fail_rule_7c(
    plant: Plant, tmp_path: Path, added: int, fails: bool
) -> None:
    # The clean run's window holds 530 boardings against 530 lagged customers: 212 more is a
    # ratio of 1.4, 265 more is exactly 1.5, which passes. 105 of them go to ride 2 (200 rows,
    # 200 customers) and the rest to ride 1 (330 and 330), so each ride stays within its own bound.
    tick = 5 * TICKS + 40
    _append_after_last(plant, "guest_boarded", _boardings(1, [tick] * (added - 105), plant))
    _append_after_last(plant, "guest_boarded", _boardings(2, [tick] * 105, plant))

    judgement = plant.judge(tmp_path)

    if fails:
        _only(judgement, f"{BOARDINGS_ABOVE} 796 boardings against 530 lagged customers")
    else:
        assert judgement.complete, judgement.reasons


def test_one_ride_counting_each_boarding_twice_fails_rule_7c_under_the_summed_bound(
    plant: Plant, tmp_path: Path
) -> None:
    # Ride 2's 200 boardings each reported twice: 400 rows against its 200 lagged customers,
    # while all car rides' 730 rows stay under 1.5 times their 530.
    twice = [dict(row) for row in plant.rows("guest_boarded") if row["ride_id"] == 2]  # noqa: PLR2004
    _append_after_last(plant, "guest_boarded", twice)

    _only(plant.judge(tmp_path), f"{BOARDINGS_ABOVE} ride 2's 400 boardings against its 200")


@pytest.mark.parametrize(("added", "fails"), [(120, False), (121, True)])
def test_one_ride_more_than_150_percent_plus_20_of_its_customers_fails_rule_7c(
    plant: Plant, tmp_path: Path, added: int, fails: bool
) -> None:
    # Ride 2's window holds 200 boardings against 200 lagged customers: 120 more is exactly
    # 1.5 times plus 20, which passes; the sum, 650 against 530, stays under 1.5 times.
    _append_after_last(plant, "guest_boarded", _boardings(2, [5 * TICKS + 40] * added, plant))

    judgement = plant.judge(tmp_path)

    if fails:
        _only(judgement, f"{BOARDINGS_ABOVE} ride 2's 321 boardings against its 200")
    else:
        assert judgement.complete, judgement.reasons


def test_boardings_with_no_rise_in_car_ride_customers_fail_only_rule_7c(
    plant: Plant, tmp_path: Path
) -> None:
    # No car ride's customers rise, so the window has no lag and no lagged customer; the maze's
    # rise keeps rule 7 (a) satisfied.
    for row in plant.rows("ride_snapshot"):
        if row["ride_id"] in CAR_RIDES:
            row["total_customers"] = 1000

    _only(plant.judge(tmp_path), f"{BOARDINGS_ABOVE} 700 boardings against 0 lagged customers")


def test_no_arrival_in_the_cohort_fails_rule_8(plant: Plant, tmp_path: Path) -> None:
    for row in plant.rows("guest_arrived"):
        row["in_cohort"] = False
    plant.tables["guest_snapshot"] = []
    plant.tables["guest_left"] = []

    _only(plant.judge(tmp_path), "no guest_arrived row joined the cohort")


def test_a_swapped_snapshot_with_an_unchanged_row_count_fails_rule_9(
    plant: Plant, tmp_path: Path
) -> None:
    day_10 = [row for row in plant.rows("guest_snapshot") if row["game_ticks_elapsed"] == 1060]
    day_10[0]["guest_key"] = day_10[1]["guest_key"]

    _only(
        plant.judge(tmp_path),
        "judged row 10 has no snapshot of cohort members [20]",
        "judged row 10 has more than one snapshot of guests [30]",
    )


def test_a_member_missing_its_snapshot_on_a_day_fails_rule_9(plant: Plant, tmp_path: Path) -> None:
    plant.keep(
        "guest_snapshot", lambda row: (row["game_ticks_elapsed"], row["guest_key"]) != (760, 40)
    )

    _only(plant.judge(tmp_path), "judged row 7 has no snapshot of cohort members [40]")


def test_a_snapshot_of_a_guest_never_in_the_cohort_fails_rule_9(
    plant: Plant, tmp_path: Path
) -> None:
    plant.rows("guest_snapshot")[0]["guest_key"] = 11

    reasons = plant.judge(tmp_path).completion_reasons
    assert "guests never in the cohort: [11]" in reasons[-1]


def test_a_failed_step_or_poll_fails_rule_1(plant: Plant, tmp_path: Path) -> None:
    plant.last["work_items_failed_total"] = 1

    _only(plant.judge(tmp_path), "reports 1 failed steps or polls")


@pytest.mark.parametrize(("pending", "fails"), [(64, False), (65, True)])
def test_more_than_64_pending_items_fails_rule_5(
    plant: Plant, tmp_path: Path, pending: int, fails: bool
) -> None:
    # Arrivals recorded but still pending keep rule 4 balanced.
    plant.last["continuous_items_pending"] = pending
    plant.last["arrivals_recorded_total"] = (
        int(str(plant.last["arrivals_recorded_total"])) + pending
    )

    judgement = plant.judge(tmp_path)

    if fails:
        _only(judgement, "65 continuous items pending, above 64")
    else:
        assert judgement.complete, judgement.reasons


@pytest.mark.parametrize(("rise", "fails"), [(4, False), (3, True)])
def test_too_few_seat_polls_in_a_period_fails_rule_2(
    plant: Plant, tmp_path: Path, rise: int, fails: bool
) -> None:
    rows = plant.rows("plugin_stats")
    for row in rows[7:]:
        row["boarding_polls_total"] = int(str(row["boarding_polls_total"])) - (5 - rise)

    judgement = plant.judge(tmp_path)

    if fails:
        _only(judgement, "judged row 7 completed fewer than 4 seat polls")
    else:
        assert judgement.complete, judgement.reasons


def test_known_guests_3_percent_outside_the_park_pass_rule_3(plant: Plant, tmp_path: Path) -> None:
    plant.rows("plugin_stats")[JUDGED_DAYS]["guests_known"] = IN_PARK + 3

    judgement = plant.judge(tmp_path)

    assert judgement.complete, judgement.reasons
    assert judgement.guests is not None and judgement.guests.guests_known_outside_park == 3  # noqa: PLR2004


@pytest.mark.parametrize(("above", "fails"), [(2, False), (3, True)])
def test_known_guests_inside_more_than_2_percent_above_the_park_count_fail_rule_3(
    plant: Plant, tmp_path: Path, above: int, fails: bool
) -> None:
    plant.rows("plugin_stats")[JUDGED_DAYS]["guests_known_in_park"] = IN_PARK + above

    judgement = plant.judge(tmp_path)

    if fails:
        _only(judgement, "103 known guests in the park against 100")
    else:
        assert judgement.complete, judgement.reasons


def test_arrivals_with_no_new_admissions_fail_rule_6(plant: Plant, tmp_path: Path) -> None:
    for row in plant.rows("park_snapshot"):
        row["total_admissions"] = ADMISSIONS

    _only(plant.judge(tmp_path), "60 guest_arrived rows against 0 new admissions")


@pytest.mark.parametrize(("arrivals", "fails"), [(275, False), (330, False), (335, True)])
def test_arrivals_more_than_10_percent_from_a_large_admissions_change_fail_rule_6(
    plant: Plant, tmp_path: Path, arrivals: int, fails: bool
) -> None:
    # An admissions change of 300 allows 30 apart (10% of it), not 10. The added arrivals come after
    # the last plugin_stats row, so rule 4's accounting is unchanged.
    plant.rows("park_snapshot")[-1]["total_admissions"] = ADMISSIONS + 300
    seq = max(int(str(row["seq"])) for rows in plant.tables.values() for row in rows)
    tick = int(str(plant.last["game_ticks_elapsed"])) + 1
    added = arrivals - len(plant.rows("guest_arrived"))
    plant.rows("guest_arrived").extend(
        {
            "session_id": SESSION,
            "seq": seq + n,
            "game_ticks_elapsed": tick,
            "guest_key": 1000 + n,
            "generated_at_ticks": tick,
            "in_cohort": False,
        }
        for n in range(1, added + 1)
    )

    judgement = plant.judge(tmp_path)

    if fails:
        _only(judgement, "335 guest_arrived rows against 300 new admissions, more than 30 apart")
    else:
        assert judgement.complete, judgement.reasons


# ---- missing inputs fail completeness, never crash ----


@pytest.mark.parametrize("column", NEW_STATS_COLUMNS)
def test_each_new_plugin_stats_column_dropped_fails_completeness(
    plant: Plant, tmp_path: Path, column: str
) -> None:
    _only(
        plant.judge(tmp_path, drop=("plugin_stats", column)), f"plugin_stats has no {column} column"
    )


@pytest.mark.parametrize("table", [*GUEST_FILES, "park_snapshot"])
def test_a_missing_guest_or_park_file_fails_completeness(
    plant: Plant, tmp_path: Path, table: str
) -> None:
    root = plant.write(tmp_path)
    (root / "v1" / f"{table}.parquet").unlink()

    judgement = judge_run(RunFacts(root, JUDGED_DAYS, "a" * 40, "a" * 40, 0))

    _only(judgement, f"{table}.parquet is missing")
    assert judgement.guests is None and judgement.periods == ()


def test_a_guest_file_missing_a_column_fails_completeness(plant: Plant, tmp_path: Path) -> None:
    judgement = plant.judge(tmp_path, drop=("guest_boarded", "detected_at_ticks"))

    _only(judgement, "guest_boarded has no detected_at_ticks column")


def test_null_new_counters_fail_completeness_with_a_reason_each(
    plant: Plant, tmp_path: Path
) -> None:
    for row in plant.rows("plugin_stats"):
        row.update(dict.fromkeys(NEW_STATS_COLUMNS))

    judgement = plant.judge(tmp_path)

    assert judgement.valid and not judgement.complete
    assert judgement.completion_reasons[0] == "last plugin_stats row has no work_items_failed_total"
    assert "no guest_arrived row joined" not in " ".join(judgement.completion_reasons)
    assert judgement.guests is not None and judgement.guests.guests_known_outside_park is None
