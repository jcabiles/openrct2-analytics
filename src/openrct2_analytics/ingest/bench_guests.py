"""Judge one benchmark run's guest capture: rules 1 to 9 of docs/architecture/benchmark.md.

``bench_judge`` calls ``judge_guests`` with the run's converted ``v1`` folder. L is the
session's last ``plugin_stats`` row, and "before L" means a lower ``seq``. An event is "in" a
judged period when its ``game_ticks_elapsed`` is at or after the row's ``period_start_ticks``
and before its ``period_end_ticks``; a judged period is one game day. Guest keys are matched
within the session. A missing column or input file fails completeness. Rule 7 (boardings
against the game's customer counters) lives in ``bench_boardings``; its coverage threshold is
``COVERAGE_THRESHOLD`` here. The guest report and each judged period's time fields go to
``verdict.json`` through ``bench_verdict``.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import duckdb

from openrct2_analytics.ingest.bench_boardings import (
    BoardingJudgement,
    Coverage,
    PeriodBoardings,
    StatsPeriod,
    judge_boardings,
)

# Rule 7 (b): calibrated once, from the lowest measured ride ratio (0.8264) minus 5 points
# (0.7764), rounded down to a whole percent. Rule 7 of docs/architecture/benchmark.md.
COVERAGE_THRESHOLD = 0.77
POLL_INTERVAL_TICKS = 20  # the plugin's seat poll runs at most once per 20 ticks
EXIT_TOLERANCE = 0.02  # rule 3: known guests inside versus the park's guest count
MAX_PENDING_ITEMS = 64  # rule 5: the seats of two full 32-seat trains
ARRIVAL_SLACK = 10  # rule 6: arrivals versus admissions, 10 or 10%, whichever is larger
ARRIVAL_SLACK_SHARE = 0.10
# The nine refusal thought types the guest_refused contract allows; the verdict lists all nine.
REFUSAL_TYPES = (
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
NEW_STATS_COLUMNS = (
    "work_items_failed_total",
    "worst_step_ms",
    "worst_step_kind",
    "worst_tick_kind_ms",
    "worst_day_start_tick_ms",
    "guest_fields_ms_total",
    "continuous_items_pending",
    "lines_queued_max",
    "guests_known",
    "guests_known_in_park",
    "arrivals_recorded_total",
    "boarding_polls_total",
    "boarders_queued_total",
)
RIDE_FILE = "ride_snapshot"
# Each input and the columns the rules read from it.
INPUT_COLUMNS: dict[str, tuple[str, ...]] = {
    "plugin_stats": ("game_ticks_elapsed", *NEW_STATS_COLUMNS),
    "park_snapshot": (
        "session_id",
        "seq",
        "game_ticks_elapsed",
        "guests_in_park",
        "total_admissions",
    ),
    RIDE_FILE: (
        "session_id",
        "game_ticks_elapsed",
        "ride_id",
        "ride_type",
        "classification",
        "total_customers",
        "guests_on_ride",
    ),
    "guest_arrived": ("session_id", "seq", "guest_key", "generated_at_ticks", "in_cohort"),
    "guest_left": ("session_id", "game_ticks_elapsed", "guest_key", "in_cohort"),
    "guest_refused": ("session_id", "thought_type"),
    "guest_snapshot": ("session_id", "game_ticks_elapsed", "guest_key"),
    "guest_boarded": ("session_id", "seq", "game_ticks_elapsed", "ride_id", "detected_at_ticks"),
}


@dataclass(frozen=True)
class PeriodTimes:
    """One judged period's time fields from ``plugin_stats`` (contract 1.3.0).

    Attributes:
        period_ticks: Game ticks in the period.
        worst_tick_ms: The period's worst tick.
        worst_step_kind: Kind of the period's longest step; None when no step ran.
        worst_tick_kind_ms: The worst tick split by time, ``name:ms`` pairs joined by ``|``.
        worst_day_start_tick_ms: The period's highest whole day-start tick time.
        guest_fields_ms_total: The period's summed time of the five boarding guest-field reads.
        lines_queued_max: The period's highest emitter queue length.
    """

    period_ticks: int
    worst_tick_ms: float
    worst_step_kind: str | None
    worst_tick_kind_ms: str | None
    worst_day_start_tick_ms: float | None
    guest_fields_ms_total: float | None
    lines_queued_max: int | None


@dataclass(frozen=True)
class GuestReport:
    """What ``verdict.json`` reports about one run's guest capture.

    Attributes:
        refusals_by_type: ``guest_refused`` rows in the session for each of the nine types.
        boardings_by_period: Each judged period's own rise in ride customers and boardings.
        coverage: Rule 7 (b)'s ratio for the run and per car ride.
        guests_known_outside_park: The last judged row's known guests not inside the park.
        boardings_before_last: ``guest_boarded`` rows before L (rule 4's B).
        boarders_queued_total: L's ``boarders_queued_total``.
    """

    refusals_by_type: dict[str, int]
    boardings_by_period: tuple[PeriodBoardings, ...]
    coverage: Coverage
    guests_known_outside_park: int | None
    boardings_before_last: int
    boarders_queued_total: int | None


@dataclass(frozen=True)
class GuestJudgement:
    """The guest rules' result for one run.

    Attributes:
        reasons: Failed guest completeness rules, in rule order.
        report: The guest report, or None when an input was missing or nothing was judged.
        periods: The judged periods' time fields, in period order.
    """

    reasons: tuple[str, ...]
    report: GuestReport | None
    periods: tuple[PeriodTimes, ...]


@dataclass(frozen=True)
class _Counters:
    """One ``plugin_stats`` row's period and part-2 counters."""

    session_id: str
    seq: int
    period_start_ticks: int
    period_end_ticks: int
    game_ticks_elapsed: int
    work_items_failed_total: int | None
    continuous_items_pending: int | None
    guests_known: int | None
    guests_known_in_park: int | None
    arrivals_recorded_total: int | None
    boarding_polls_total: int | None
    boarders_queued_total: int | None
    times: PeriodTimes

    @property
    def period(self) -> StatsPeriod:
        """The row's period, as the boarding rules read it."""
        return StatsPeriod(self.period_start_ticks, self.period_end_ticks)


@dataclass(frozen=True)
class _Run:
    """The rows the guest rules read: the row before the first judged one, the judged, L."""

    session_id: str
    before_first: _Counters
    judged: tuple[_Counters, ...]
    last: _Counters


def _input_reasons(connection: duckdb.DuckDBPyConnection, v1: Path) -> list[str]:
    """Create a view per input file; return each missing guest file or column."""
    reasons: list[str] = []
    for name, needed in INPUT_COLUMNS.items():
        path = v1 / f"{name}.parquet"
        if not path.exists():
            # The judge's ride rule already reports a missing ride_snapshot file.
            if name != RIDE_FILE:
                reasons.append(f"{name}.parquet is missing")
            continue
        relation = connection.read_parquet(path.as_posix())
        reasons.extend(
            f"{name} has no {column} column" for column in needed if column not in relation.columns
        )
        relation.create_view(name)
    return reasons


def _counters(connection: duckdb.DuckDBPyConnection) -> list[_Counters]:
    """Read every ``plugin_stats`` row in the judge's order."""
    rows = connection.execute(
        "SELECT session_id, seq, period_start_ticks, period_end_ticks, game_ticks_elapsed, "
        "work_items_failed_total, continuous_items_pending, guests_known, guests_known_in_park, "
        "arrivals_recorded_total, boarding_polls_total, boarders_queued_total, period_ticks, "
        "worst_tick_ms, worst_step_kind, worst_tick_kind_ms, worst_day_start_tick_ms, "
        "guest_fields_ms_total, lines_queued_max FROM plugin_stats ORDER BY session_id, seq"
    ).fetchall()
    return [
        _Counters(
            session_id=row[0],
            seq=row[1],
            period_start_ticks=row[2],
            period_end_ticks=row[3],
            game_ticks_elapsed=row[4],
            work_items_failed_total=row[5],
            continuous_items_pending=row[6],
            guests_known=row[7],
            guests_known_in_park=row[8],
            arrivals_recorded_total=row[9],
            boarding_polls_total=row[10],
            boarders_queued_total=row[11],
            times=PeriodTimes(
                period_ticks=row[12],
                worst_tick_ms=row[13],
                worst_step_kind=row[14],
                worst_tick_kind_ms=row[15],
                worst_day_start_tick_ms=row[16],
                guest_fields_ms_total=row[17],
                lines_queued_max=row[18],
            ),
        )
        for row in rows
    ]


def _count(connection: duckdb.DuckDBPyConnection, sql: str, parameters: list[object]) -> int:
    """Return the single count a query selects."""
    found = connection.execute(sql, parameters).fetchone()
    return 0 if found is None else int(found[0])


def _count_before(connection: duckdb.DuckDBPyConnection, table: str, run: _Run) -> int:
    """Rows of ``table`` in the session emitted before L."""
    sql = f"SELECT count(*) FROM {table} WHERE session_id = ? AND seq < ?"  # noqa: S608
    return _count(connection, sql, [run.session_id, run.last.seq])


def _failure_and_poll_reasons(run: _Run) -> list[str]:
    """Rule 1 (no failed step or poll) and rule 2 (polls ran every judged period)."""
    reasons: list[str] = []
    failed = run.last.work_items_failed_total
    if failed is None:
        reasons.append("last plugin_stats row has no work_items_failed_total")
    elif failed != 0:
        reasons.append(f"last plugin_stats row reports {failed} failed steps or polls")
    previous = run.before_first.boarding_polls_total
    for position, row in enumerate(run.judged, start=1):
        minimum = row.times.period_ticks // POLL_INTERVAL_TICKS - 1
        polls = row.boarding_polls_total
        if polls is None or previous is None:
            reasons.append(f"judged row {position} has no boarding_polls_total rise")
        elif polls - previous < minimum:
            reasons.append(f"judged row {position} completed fewer than {minimum} seat polls")
        previous = polls
    return reasons


def _exit_reasons(connection: duckdb.DuckDBPyConnection, run: _Run) -> list[str]:
    """Rule 3: the last judged row's known guests inside match the park's count."""
    row = run.judged[-1]
    park = connection.execute(
        "SELECT guests_in_park FROM park_snapshot WHERE session_id = ? AND game_ticks_elapsed = ? "
        "ORDER BY seq LIMIT 1",
        [run.session_id, row.game_ticks_elapsed],
    ).fetchone()
    known = row.guests_known_in_park
    if known is None:
        return ["last judged row has no guests_known_in_park"]
    if park is None:
        return ["last judged row has no park_snapshot on the same tick"]
    in_park = int(park[0])
    if abs(known - in_park) > EXIT_TOLERANCE * in_park:
        return [
            f"last judged row has {known} known guests in the park against {in_park} in its "
            f"park_snapshot, more than {EXIT_TOLERANCE:.0%} apart"
        ]
    return []


def _accounting_reasons(run: _Run, arrived: int, boarded: int) -> list[str]:
    """Rule 4 (every recorded arrival and boarding is an event or pending) and rule 5."""
    last = run.last
    counters = {
        "arrivals_recorded_total": last.arrivals_recorded_total,
        "boarders_queued_total": last.boarders_queued_total,
        "continuous_items_pending": last.continuous_items_pending,
    }
    missing = [name for name, value in counters.items() if value is None]
    if missing:
        return [f"last plugin_stats row has no {name}" for name in missing]
    recorded, queued, pending = (int(value or 0) for value in counters.values())
    reasons: list[str] = []
    if (
        arrived + boarded != recorded + queued - pending
        or arrived < recorded - pending
        or boarded < queued - pending
    ):
        reasons.append(
            f"{arrived} guest_arrived and {boarded} guest_boarded rows before the last "
            f"plugin_stats row do not account for its {recorded} recorded arrivals and "
            f"{queued} queued boarders with {pending} pending"
        )
    if pending > MAX_PENDING_ITEMS:
        reasons.append(
            f"last plugin_stats row has {pending} continuous items pending, "
            f"above {MAX_PENDING_ITEMS}"
        )
    return reasons


def _admission_reasons(connection: duckdb.DuckDBPyConnection, run: _Run) -> list[str]:
    """Rule 6: the session's arrivals match its change in admissions."""
    arrived = _count(
        connection, "SELECT count(*) FROM guest_arrived WHERE session_id = ?", [run.session_id]
    )
    found = connection.execute(
        "SELECT count(*), arg_max(total_admissions, seq) - arg_min(total_admissions, seq) "
        "FROM park_snapshot WHERE session_id = ?",
        [run.session_id],
    ).fetchone()
    if found is None or int(found[0]) == 0:
        return ["session has no park_snapshot to compare arrivals with admissions"]
    change = int(found[1])
    slack = max(ARRIVAL_SLACK, ARRIVAL_SLACK_SHARE * change)
    if abs(arrived - change) > slack:
        return [
            f"session has {arrived} guest_arrived rows against {change} new admissions, "
            f"more than {slack:g} apart"
        ]
    return []


def _cohort_reasons(connection: duckdb.DuckDBPyConnection, run: _Run) -> list[str]:
    """Rule 8 (arrivals reach the cohort) and rule 9 (one snapshot a day per member)."""
    reasons: list[str] = []
    members = dict(
        connection.execute(
            "SELECT guest_key, min(generated_at_ticks) FROM guest_arrived "
            "WHERE session_id = ? AND in_cohort GROUP BY guest_key",
            [run.session_id],
        ).fetchall()
    )
    recorded = run.last.arrivals_recorded_total
    if recorded is not None and recorded > 0 and not members:
        reasons.append("no guest_arrived row joined the cohort although arrivals were recorded")
    left = dict(
        connection.execute(
            "SELECT guest_key, min(game_ticks_elapsed) FROM guest_left "
            "WHERE session_id = ? AND in_cohort GROUP BY guest_key",
            [run.session_id],
        ).fetchall()
    )
    snapshots = connection.execute(
        "SELECT guest_key, game_ticks_elapsed FROM guest_snapshot WHERE session_id = ?",
        [run.session_id],
    ).fetchall()
    for position, row in enumerate(run.judged, start=1):
        counts = Counter(key for key, tick in snapshots if row.period.contains(tick))
        reasons.extend(_snapshot_reasons(position, row.period, counts, members=members, left=left))
    strangers = sorted({key for key, _ in snapshots if key not in members})
    if strangers:
        reasons.append(f"guest_snapshot rows belong to guests never in the cohort: {strangers}")
    return reasons


def _snapshot_reasons(
    position: int,
    period: StatsPeriod,
    counts: Counter[int],
    *,
    members: dict[int, int],
    left: dict[int, int],
) -> list[str]:
    """Rule 9 for one judged period: each member due a snapshot has exactly one."""
    missing = []
    for key, generated in sorted(members.items()):
        gone = left.get(key)
        if generated >= period.start or (gone is not None and gone < period.start):
            continue
        # A member whose guest_left falls in the period may have no snapshot in it.
        if counts[key] == 0 and not (gone is not None and period.contains(gone)):
            missing.append(key)
    doubled = sorted(key for key, count in counts.items() if count > 1)
    reasons = []
    if missing:
        reasons.append(f"judged row {position} has no snapshot of cohort members {missing}")
    if doubled:
        reasons.append(f"judged row {position} has more than one snapshot of guests {doubled}")
    return reasons


def _refusals(connection: duckdb.DuckDBPyConnection, run: _Run) -> dict[str, int]:
    """``guest_refused`` rows in the session by thought type, all nine types listed."""
    found = dict(
        connection.execute(
            "SELECT thought_type, count(*) FROM guest_refused WHERE session_id = ? "
            "GROUP BY thought_type",
            [run.session_id],
        ).fetchall()
    )
    return {name: int(found.get(name, 0)) for name in REFUSAL_TYPES}


def _outside_park(row: _Counters) -> int | None:
    """Known guests generated but not inside the park, reported and not judged (rule 3)."""
    if row.guests_known is None or row.guests_known_in_park is None:
        return None
    return row.guests_known - row.guests_known_in_park


def judge_guests(
    connection: duckdb.DuckDBPyConnection,
    v1: Path,
    *,
    warmup_rows: int,
    judged_days: int,
    coverage_threshold: float,
) -> GuestJudgement:
    """Judge rules 1 to 9 on one run's converted Parquet.

    Args:
        connection: The judge's DuckDB connection; one view per input file is created on it.
        v1: The run's converted ``v1`` folder.
        warmup_rows: Leading ``plugin_stats`` rows that are never judged (at least 1).
        judged_days: Rows judged after the warm-up.
        coverage_threshold: Rule 7 (b)'s threshold, ``COVERAGE_THRESHOLD`` unless a test sets one.

    Returns:
        The failed guest rules, the guest report and the judged periods' time fields.
    """
    reasons = _input_reasons(connection, v1)
    if reasons or not (v1 / f"{RIDE_FILE}.parquet").exists():
        return GuestJudgement(tuple(reasons), None, ())
    rows = _counters(connection)
    judged = tuple(rows[warmup_rows : warmup_rows + judged_days])
    if not judged:  # the judge's validity rules already fail a run with no judged row
        return GuestJudgement((), None, ())
    run = _Run(rows[-1].session_id, rows[warmup_rows - 1], judged, rows[-1])
    arrived = _count_before(connection, "guest_arrived", run)
    boarded = _count_before(connection, "guest_boarded", run)
    boardings: BoardingJudgement = judge_boardings(
        connection,
        run.session_id,
        tuple(row.period for row in judged),
        coverage_threshold,
    )
    reasons = [
        *_failure_and_poll_reasons(run),
        *_exit_reasons(connection, run),
        *_accounting_reasons(run, arrived, boarded),
        *_admission_reasons(connection, run),
        *boardings.reasons,
        *_cohort_reasons(connection, run),
    ]
    report = GuestReport(
        refusals_by_type=_refusals(connection, run),
        boardings_by_period=boardings.periods,
        coverage=boardings.coverage,
        guests_known_outside_park=_outside_park(judged[-1]),
        boardings_before_last=boarded,
        boarders_queued_total=run.last.boarders_queued_total,
    )
    return GuestJudgement(tuple(reasons), report, tuple(row.times for row in judged))
