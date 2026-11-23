"""Judge the validity, completeness, and cost of one benchmark Parquet run."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import duckdb

from openrct2_analytics.ingest.bench_guests import (
    COVERAGE_THRESHOLD,
    GuestReport,
    PeriodTimes,
    judge_guests,
)
from openrct2_analytics.ingest.capture_report import AUDIT_FILE, CostRow, PluginCost, judge_cost
from openrct2_analytics.ingest.contracts import LANDING_FOLDER
from openrct2_analytics.ingest.convert import VIOLATION_FILTER

V1_FOLDER = Path(LANDING_FOLDER)
PLUGIN_STATS_FILE = V1_FOLDER / "plugin_stats.parquet"
SESSION_START_FILE = V1_FOLDER / "session_start.parquet"
RIDE_SNAPSHOT_FILE = V1_FOLDER / "ride_snapshot.parquet"
WARMUP_ROWS = 1
NORMAL_GAME_SPEED = 1
FIRST_SEQ = 1
FIXTURE_CHANGED = "fixture changed during the run"


@dataclass(frozen=True)
class RunFacts:
    """Inputs external to the Parquet data for one benchmark run.

    Attributes:
        parquet_dir: Folder containing the converter's ``v1`` and ``audit`` output.
        judged_days: Number of non-warm-up daily statistics rows to judge.
        fixture_sha1_before: SHA-1 of the fixture before the benchmark.
        fixture_sha1_after: SHA-1 of the fixture after the benchmark.
        malformed_lines: Number of malformed plugin output lines.
    """

    parquet_dir: Path
    judged_days: int
    fixture_sha1_before: str
    fixture_sha1_after: str
    malformed_lines: int


@dataclass(frozen=True)
class RunJudgement:
    """The result of checking one benchmark run.

    ``worst_tick_offset_ticks`` is the worst row's ``worst_tick_at_ticks`` minus
    its ``period_start_ticks``; 0 is the tick of the day callback that opened the
    period.

    Attributes:
        valid: Whether the run passed its input-validity checks.
        complete: Whether the run completed all daily work and snapshots without loss.
        validity_reasons: Failed validity rules, in rule order.
        completion_reasons: Failed completion rules, in rule order.
        cost: Cost over the judged rows, if those rows contain game ticks.
        worst_tick_offset_ticks: Offset of the worst tick within its reporting period.
        worst_tick_period_ticks: Length of the worst tick's reporting period.
        work_units_total: Value from the session's last statistics row.
        work_items_skipped_total: Value from the session's last statistics row.
        lines_dropped_total: Value from the session's last statistics row.
        write_partial_total: Value from the session's last statistics row.
        periods: The judged periods' time fields, empty when they could not be read.
        guests: The guest report, or None when the guest rules could not run.
    """

    valid: bool
    complete: bool
    validity_reasons: tuple[str, ...]
    completion_reasons: tuple[str, ...]
    cost: PluginCost | None
    worst_tick_offset_ticks: int | None
    worst_tick_period_ticks: int | None
    work_units_total: int | None
    work_items_skipped_total: int | None
    lines_dropped_total: int | None
    write_partial_total: int | None
    periods: tuple[PeriodTimes, ...]
    guests: GuestReport | None

    @property
    def reasons(self) -> tuple[str, ...]:
        """Return validity and completion failures together, in rule order."""
        return self.validity_reasons + self.completion_reasons


@dataclass(frozen=True)
class _StatsRow:
    """Fields from one plugin statistics row needed by the verdict."""

    session_id: str
    seq: int
    period_start_ticks: int
    period_end_ticks: int
    period_ticks: int
    work_ms_total: float
    worst_tick_ms: float
    worst_tick_at_ticks: int
    warmup: bool
    clock: str
    game_speed: int
    lines_dropped_total: int | None
    write_partial_total: int | None
    work_units_total: int | None
    work_items_skipped_total: int | None
    work_queue_length: int | None


def _quoted(path: Path) -> str:
    """Return a DuckDB single-quoted path literal."""
    return path.as_posix().replace("'", "''")


def _column_names(connection: duckdb.DuckDBPyConnection, path: Path) -> set[str]:
    """Return the Parquet column names at ``path``."""
    rows = connection.execute(f"DESCRIBE SELECT * FROM read_parquet('{_quoted(path)}')").fetchall()
    return {str(row[0]) for row in rows}


def _optional_column(columns: set[str], name: str) -> str:
    """Select an optional BIGINT column, or a typed null if it is absent."""
    return name if name in columns else f"NULL::BIGINT AS {name}"


def _stats_rows(
    connection: duckdb.DuckDBPyConnection, path: Path
) -> tuple[list[_StatsRow], set[str]]:
    """Read statistics rows and report the optional columns that were present."""
    columns = _column_names(connection, path)
    optional = (
        "lines_dropped_total",
        "write_partial_total",
        "work_units_total",
        "work_items_skipped_total",
        "work_queue_length",
    )
    selected = ", ".join(_optional_column(columns, name) for name in optional)
    rows = connection.execute(
        "SELECT session_id, seq, period_start_ticks, period_end_ticks, period_ticks, "
        "work_ms_total, worst_tick_ms, worst_tick_at_ticks, warmup, clock, game_speed, "
        f"{selected} FROM read_parquet('{_quoted(path)}') ORDER BY session_id, seq"
    ).fetchall()
    return [
        _StatsRow(
            session_id=str(row[0]),
            seq=int(row[1]),
            period_start_ticks=int(row[2]),
            period_end_ticks=int(row[3]),
            period_ticks=int(row[4]),
            work_ms_total=float(row[5]),
            worst_tick_ms=float(row[6]),
            worst_tick_at_ticks=int(row[7]),
            warmup=bool(row[8]),
            clock=str(row[9]),
            game_speed=int(row[10]),
            lines_dropped_total=_integer_or_none(row[11]),
            write_partial_total=_integer_or_none(row[12]),
            work_units_total=_integer_or_none(row[13]),
            work_items_skipped_total=_integer_or_none(row[14]),
            work_queue_length=_integer_or_none(row[15]),
        )
        for row in rows
    ], columns


def _integer_or_none(value: object) -> int | None:
    """Convert a nullable DuckDB integer value."""
    return None if value is None else _integer(value)


def _integer(value: object) -> int:
    """Return a DuckDB integer value, rejecting an unexpected type."""
    if not isinstance(value, int):
        raise TypeError("expected an integer from DuckDB")
    return value


def _validity_reasons(facts: RunFacts, rows: list[_StatsRow]) -> list[str]:
    """Return failures for validity rules that do not require a second file."""
    reasons: list[str] = []
    if len({row.session_id for row in rows}) > 1:
        reasons.append("plugin_stats rows belong to more than one session")
    required_rows = facts.judged_days + WARMUP_ROWS
    if len(rows) < required_rows:
        reasons.append(f"plugin_stats has fewer than {required_rows} rows")
    if rows and not rows[0].warmup:
        reasons.append("plugin_stats row 1 is not marked warmup")
    for position, row in enumerate(rows[WARMUP_ROWS:required_rows], start=1):
        reasons.extend(_row_qualification_reasons(position, row))
    if facts.fixture_sha1_before != facts.fixture_sha1_after:
        reasons.append(FIXTURE_CHANGED)
    if facts.malformed_lines != 0:
        reasons.append("malformed plugin output lines were found")
    return reasons


def _row_qualification_reasons(position: int, row: _StatsRow) -> list[str]:
    """Return validity failures for one judged statistics row."""
    reasons: list[str] = []
    if row.warmup:
        reasons.append(f"judged row {position} is marked warmup")
    if row.clock != "performance":
        reasons.append(f"judged row {position} does not use the performance clock")
    if row.game_speed != NORMAL_GAME_SPEED:
        reasons.append(f"judged row {position} has game_speed other than {NORMAL_GAME_SPEED}")
    if row.period_ticks <= 0:
        reasons.append(f"judged row {position} has no period ticks")
    return reasons


def _audit_and_start_reasons(
    connection: duckdb.DuckDBPyConnection, facts: RunFacts, session_id: str | None
) -> list[str]:
    """Return validity failures from the audit and session-start files."""
    if session_id is None:
        return []
    audit = _quoted(facts.parquet_dir / AUDIT_FILE)
    clean_audit = connection.execute(
        f"SELECT count(*) FROM read_parquet('{audit}') "
        f"WHERE session_id = ? AND NOT ({VIOLATION_FILTER})",
        [session_id],
    ).fetchone()
    audit_sessions = connection.execute(
        f"SELECT count(*) FROM read_parquet('{audit}') WHERE session_id <> ?",
        [session_id],
    ).fetchone()
    start = _quoted(facts.parquet_dir / SESSION_START_FILE)
    starts = connection.execute(
        f"SELECT count(*) FROM read_parquet('{start}') WHERE session_id = ? AND seq = ?",
        [session_id, FIRST_SEQ],
    ).fetchone()
    start_sessions = connection.execute(
        f"SELECT count(*) FROM read_parquet('{start}') WHERE session_id <> ?",
        [session_id],
    ).fetchone()
    reasons: list[str] = []
    if clean_audit is None or int(clean_audit[0]) == 0:
        reasons.append("session seq audit is not clean")
    if starts is None or int(starts[0]) == 0:
        reasons.append("session has no session_start at seq 1")
    if (audit_sessions is not None and int(audit_sessions[0]) > 0) or (
        start_sessions is not None and int(start_sessions[0]) > 0
    ):
        reasons.append("audit or session_start contains a different session")
    return reasons


def _completion_reasons(
    connection: duckdb.DuckDBPyConnection,
    facts: RunFacts,
    judged: list[_StatsRow],
    *,
    last: _StatsRow | None,
    columns: set[str],
) -> list[str]:
    """Return failures for work, snapshot, and loss completion requirements."""
    reasons = _queue_reasons(judged, columns)
    reasons.extend(_ride_reasons(connection, facts, judged))
    if last is not None and not _nothing_lost(last, columns):
        reasons.append("last plugin_stats row reports lost work")
    return reasons


def _queue_reasons(judged: list[_StatsRow], columns: set[str]) -> list[str]:
    """Return completion failures for non-empty daily work queues."""
    if "work_queue_length" not in columns:
        return ["plugin_stats has no work_queue_length column"]
    return [
        f"judged row {position} has work_queue_length not equal to 0"
        for position, row in enumerate(judged, start=1)
        if row.work_queue_length != 0
    ]


def _ride_reasons(
    connection: duckdb.DuckDBPyConnection, facts: RunFacts, judged: list[_StatsRow]
) -> list[str]:
    """Return completion failures for judged periods without a ride snapshot."""
    ride_file = facts.parquet_dir / RIDE_SNAPSHOT_FILE
    if not ride_file.exists():
        return ["ride_snapshot.parquet is missing"]
    reasons: list[str] = []
    ride_path = _quoted(ride_file)
    for position, row in enumerate(judged, start=1):
        found = connection.execute(
            f"SELECT count(*) FROM read_parquet('{ride_path}') "
            "WHERE session_id = ? AND game_ticks_elapsed >= ? AND game_ticks_elapsed < ?",
            [row.session_id, row.period_start_ticks, row.period_end_ticks],
        ).fetchone()
        if found is None or int(found[0]) == 0:
            reasons.append(f"judged row {position} has no ride snapshot")
    return reasons


def _nothing_lost(last: _StatsRow, columns: set[str]) -> bool:
    """Return whether the last statistics row reports no lost output or work."""
    required = ("lines_dropped_total", "write_partial_total", "work_items_skipped_total")
    values = (last.lines_dropped_total, last.write_partial_total, last.work_items_skipped_total)
    return all(name in columns for name in required) and all(value == 0 for value in values)


def _cost_and_offset(
    judged: list[_StatsRow],
) -> tuple[PluginCost | None, int | None, int | None]:
    """Return judged cost and the worst tick's position within its period."""
    cost = judge_cost(
        [
            CostRow(
                row.session_id,
                row.period_ticks,
                row.work_ms_total,
                row.worst_tick_ms,
                row.worst_tick_at_ticks,
            )
            for row in judged
        ]
    )
    if cost is None:
        return None, None, None
    worst = next(
        row
        for row in judged
        if row.session_id == cost.worst_tick_session_id
        and row.worst_tick_at_ticks == cost.worst_tick_at_ticks
        and row.worst_tick_ms == cost.worst_tick_ms
    )
    return cost, worst.worst_tick_at_ticks - worst.period_start_ticks, worst.period_ticks


NOT_JUDGED = "the run produced no data to judge"


def unjudged_run(reasons: Sequence[str]) -> RunJudgement:
    """Return the judgement of a run that produced no judgeable data.

    A run that timed out, whose game exited early, or whose raw lines did not convert has
    no Parquet to judge, so it is invalid for the given reasons and has no cost.

    Args:
        reasons: Why the run could not be judged, in the order they were found.

    Returns:
        An invalid, incomplete judgement with no cost or counters.
    """
    return RunJudgement(
        valid=False,
        complete=False,
        validity_reasons=tuple(reasons),
        completion_reasons=(NOT_JUDGED,),
        cost=None,
        worst_tick_offset_ticks=None,
        worst_tick_period_ticks=None,
        work_units_total=None,
        work_items_skipped_total=None,
        lines_dropped_total=None,
        write_partial_total=None,
        periods=(),
        guests=None,
    )


def judge_run(facts: RunFacts, *, coverage_threshold: float = COVERAGE_THRESHOLD) -> RunJudgement:
    """Judge one benchmark run from converter-produced Parquet files.

    Completeness includes the guest rules (``bench_guests``), after part 1's rules.

    Args:
        facts: The run folder and benchmark facts not represented in Parquet.
        coverage_threshold: The guest rules' boarding coverage threshold (rule 7 (b)).

    Returns:
        Validity and completion decisions, all failed rules, and judged plugin cost.

    Raises:
        ValueError: If ``facts.judged_days`` is below one.
    """
    if facts.judged_days < 1:
        raise ValueError("judged_days must be at least 1")
    connection = duckdb.connect(":memory:")
    try:
        connection.execute("SET TimeZone='UTC'")
        rows, columns = _stats_rows(connection, facts.parquet_dir / PLUGIN_STATS_FILE)
        required_rows = facts.judged_days + WARMUP_ROWS
        judged = rows[WARMUP_ROWS:required_rows]
        last = rows[-1] if rows else None
        validity = _validity_reasons(facts, rows)
        validity.extend(
            _audit_and_start_reasons(connection, facts, None if last is None else last.session_id)
        )
        completion = _completion_reasons(connection, facts, judged, last=last, columns=columns)
        guests = judge_guests(
            connection,
            facts.parquet_dir / V1_FOLDER,
            warmup_rows=WARMUP_ROWS,
            judged_days=facts.judged_days,
            coverage_threshold=coverage_threshold,
        )
        completion.extend(guests.reasons)
        cost, offset, period_ticks = _cost_and_offset(judged)
        return RunJudgement(
            valid=not validity,
            complete=not completion,
            validity_reasons=tuple(validity),
            completion_reasons=tuple(completion),
            cost=cost,
            worst_tick_offset_ticks=offset,
            worst_tick_period_ticks=period_ticks,
            work_units_total=None if last is None else last.work_units_total,
            work_items_skipped_total=None if last is None else last.work_items_skipped_total,
            lines_dropped_total=None if last is None else last.lines_dropped_total,
            write_partial_total=None if last is None else last.write_partial_total,
            periods=guests.periods,
            guests=guests.report,
        )
    finally:
        connection.close()
