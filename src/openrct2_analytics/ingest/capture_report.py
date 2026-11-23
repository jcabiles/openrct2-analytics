"""Summarize one capture run from the converted Parquet and render it as plain text.

"This run" means the sessions with any event whose ``received_at`` is at or after a
start time. The plugin's cost is judged by the method in ``docs/FINDINGS.md`` and the
limits of ``docs/adr/0005-plugin-per-tick-budget.md``. DuckDB reads only
``<parquet>/v1/*.parquet`` and ``<parquet>/audit/seq_audit.parquet``; it never opens
the warehouse.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import duckdb

from openrct2_analytics.ingest.contracts import LANDING_FOLDER

# docs/adr/0005-plugin-per-tick-budget.md
WORST_TICK_LIMIT_MS = 10.0
MEAN_TICK_LIMIT_MS = 1.25
AUDIT_FILE = Path("audit") / "seq_audit.parquet"
JUDGED_COST_FILTER = "NOT warmup AND clock = 'performance' AND game_speed = 1"

# Sessions that have an event received at or after the start time.
RUN_SESSIONS = "SELECT DISTINCT session_id FROM events WHERE received_at >= $since"


@dataclass(frozen=True)
class SessionSummary:
    """One session of this run.

    Attributes:
        session_id: The session's full id.
        park_id: The park the session's first event names.
        park_name: Park name from its ``session_start``; None when it has none.
        headless: Whether its ``session_start`` says the game had no window; None when
            it has no ``session_start``.
        first_seq: Smallest ``seq`` of any event type.
        last_seq: Largest ``seq`` of any event type.
        seq_problem: Plain-words description of the ``seq`` violation, or None when the
            audit passed.
        lines_dropped_total: Largest ``lines_dropped_total`` its ``plugin_stats`` rows
            report; None when it has no ``plugin_stats`` row.
    """

    session_id: str
    park_id: str
    park_name: str | None
    headless: bool | None
    first_seq: int
    last_seq: int
    seq_problem: str | None
    lines_dropped_total: int | None

    @property
    def has_session_start(self) -> bool:
        """True when the session sent a ``session_start`` event."""
        return self.park_name is not None


@dataclass(frozen=True)
class PluginCost:
    """The plugin's cost over this run's judged ``plugin_stats`` rows.

    Attributes:
        judged_ticks: Sum of ``period_ticks``, in game ticks.
        worst_tick_ms: Largest ``worst_tick_ms``, in milliseconds of wall-clock time.
        worst_tick_session_id: Session that had the worst tick.
        worst_tick_at_ticks: Game tick at which the worst tick happened.
        mean_tick_ms: Sum of ``work_ms_total`` over ``judged_ticks``, in ms per tick.
    """

    judged_ticks: int
    worst_tick_ms: float
    worst_tick_session_id: str
    worst_tick_at_ticks: int
    mean_tick_ms: float

    @property
    def worst_within_limit(self) -> bool:
        """True when the worst tick is at most 10 ms."""
        return self.worst_tick_ms <= WORST_TICK_LIMIT_MS

    @property
    def mean_within_limit(self) -> bool:
        """True when the mean is at most 1.25 ms per tick."""
        return self.mean_tick_ms <= MEAN_TICK_LIMIT_MS


@dataclass(frozen=True)
class CostRow:
    """One judged ``plugin_stats`` row.

    Attributes:
        session_id: Session that produced the row.
        period_ticks: Number of game ticks in the row's period.
        work_ms_total: Total work in the period, in milliseconds.
        worst_tick_ms: Longest single tick in the period, in milliseconds.
        worst_tick_at_ticks: Game tick at which the longest tick happened.
    """

    session_id: str
    period_ticks: int
    work_ms_total: float
    worst_tick_ms: float
    worst_tick_at_ticks: int


def judge_cost(rows: Sequence[CostRow]) -> PluginCost | None:
    """Judge the plugin cost represented by already-filtered statistics rows.

    Args:
        rows: Judged ``plugin_stats`` rows from one or more sessions.

    Returns:
        The aggregate plugin cost, or None when the rows have no game ticks.
    """
    judged_ticks = sum(row.period_ticks for row in rows)
    if not rows or not judged_ticks:
        return None
    worst = min(
        rows,
        key=lambda row: (-row.worst_tick_ms, row.session_id, row.worst_tick_at_ticks),
    )
    return PluginCost(
        judged_ticks=judged_ticks,
        worst_tick_ms=worst.worst_tick_ms,
        worst_tick_session_id=worst.session_id,
        worst_tick_at_ticks=worst.worst_tick_at_ticks,
        mean_tick_ms=sum(row.work_ms_total for row in rows) / judged_ticks,
    )


@dataclass(frozen=True)
class CaptureSummary:
    """What one capture run landed.

    Attributes:
        events_by_type: Event count per event type, for this run's sessions only,
            sorted by type; types with no event are absent.
        total_events: Sum of ``events_by_type``.
        sessions: This run's sessions, ordered by session id.
        cost: The plugin's cost, or None when no ``plugin_stats`` row was judged.
        finance_months: Number of ``finance_month`` events in this run's sessions.
        earlier_violations: One plain-words line per ``seq`` violation in a session that
            is not in this run.
    """

    events_by_type: dict[str, int]
    total_events: int
    sessions: list[SessionSummary]
    cost: PluginCost | None
    finance_months: int
    earlier_violations: list[str] = field(default_factory=list)


def _describe_problem(missing: int, duplicates: int, first_seq: int, park_count: int) -> str | None:
    problems = []
    if missing:
        problems.append(f"{missing} seq number(s) missing")
    if duplicates:
        problems.append(f"{duplicates} repeated seq row(s)")
    if first_seq != 1:
        problems.append(f"first seq is {first_seq}, not 1")
    if park_count > 1:
        problems.append(f"{park_count} different park ids")
    return "; ".join(problems) or None


def _events_by_type(
    connection: duckdb.DuckDBPyConnection, since: datetime
) -> tuple[dict[str, int], int]:
    rows = connection.execute(
        f"SELECT event_type, count(*) FROM events WHERE session_id IN ({RUN_SESSIONS}) "
        "GROUP BY event_type ORDER BY event_type",
        {"since": since},
    ).fetchall()
    counts = {str(kind): int(count) for kind, count in rows}
    return counts, counts.get("finance_month", 0)


def _cost(connection: duckdb.DuckDBPyConnection, since: datetime) -> PluginCost | None:
    judged = (
        f"FROM events WHERE event_type = 'plugin_stats' AND session_id IN ({RUN_SESSIONS}) "
        f"AND {JUDGED_COST_FILTER}"
    )
    rows = connection.execute(
        "SELECT session_id, period_ticks, work_ms_total, worst_tick_ms, "
        f"worst_tick_at_ticks {judged} ORDER BY session_id, seq",
        {"since": since},
    ).fetchall()
    return judge_cost(
        [
            CostRow(
                session_id=str(session_id),
                period_ticks=int(period_ticks),
                work_ms_total=float(work_ms_total),
                worst_tick_ms=float(worst_tick_ms),
                worst_tick_at_ticks=int(worst_tick_at_ticks),
            )
            for session_id, period_ticks, work_ms_total, worst_tick_ms, worst_tick_at_ticks in rows
        ]
    )


def _sessions(
    connection: duckdb.DuckDBPyConnection, since: datetime
) -> tuple[list[SessionSummary], list[str]]:
    rows = connection.execute(
        f"""
        SELECT a.session_id, a.park_id, a.first_seq, a.last_seq,
               a.missing, a.duplicates, a.park_count,
               a.session_id IN ({RUN_SESSIONS}) AS in_run,
               (SELECT arg_min(park_name, seq) FROM events s
                 WHERE s.event_type = 'session_start' AND s.session_id = a.session_id),
               (SELECT arg_min(headless, seq) FROM events s
                 WHERE s.event_type = 'session_start' AND s.session_id = a.session_id),
               (SELECT max(lines_dropped_total) FROM events s
                 WHERE s.event_type = 'plugin_stats' AND s.session_id = a.session_id)
        FROM audit a ORDER BY a.session_id
        """,
        {"since": since},
    ).fetchall()
    sessions: list[SessionSummary] = []
    earlier: list[str] = []
    for sid, park, first, last, missing, dups, parks, in_run, name, headless, dropped in rows:
        problem = _describe_problem(missing, dups, first, parks)
        if in_run:
            sessions.append(
                SessionSummary(sid, park, name, headless, first, last, problem, dropped)
            )
        elif problem:
            earlier.append(f"session {sid}: {problem}")
    return sessions, earlier


def summarize(parquet_dir: Path, since: datetime) -> CaptureSummary:
    """Summarize this run's sessions from the converted Parquet.

    Every ``plugin_stats`` row of a session in this run is judged by the method in
    ``docs/FINDINGS.md`` (not warm-up, ``clock = 'performance'``, ``game_speed = 1``).

    Args:
        parquet_dir: Folder the converter wrote, holding ``v1/`` and ``audit/``.
        since: Start of the run, with a time zone. A session is in this run when any of
            its events has ``received_at`` at or after it.

    Returns:
        The summary of this run's sessions, plus a warning line for each earlier session
        whose ``seq`` audit failed.

    Raises:
        ValueError: if ``since`` has no time zone.
        duckdb.IOException: if the Parquet files are missing.
    """
    if since.tzinfo is None:
        raise ValueError("since must carry a time zone")
    events = (parquet_dir / LANDING_FOLDER / "*.parquet").as_posix().replace("'", "''")
    audit = (parquet_dir / AUDIT_FILE).as_posix().replace("'", "''")
    connection = duckdb.connect(":memory:")
    try:
        connection.execute("SET TimeZone='UTC'")
        connection.execute(
            f"CREATE VIEW events AS SELECT * FROM read_parquet('{events}', union_by_name = true)"
        )
        connection.execute(f"CREATE VIEW audit AS SELECT * FROM read_parquet('{audit}')")
        counts, finance_months = _events_by_type(connection, since)
        sessions, earlier = _sessions(connection, since)
        return CaptureSummary(
            events_by_type=counts,
            total_events=sum(counts.values()),
            sessions=sessions,
            cost=_cost(connection, since),
            finance_months=finance_months,
            earlier_violations=earlier,
        )
    finally:
        connection.close()


def _session_lines(session: SessionSummary) -> list[str]:
    start = (
        f"{session.park_name}, headless {'yes' if session.headless else 'no'}"
        if session.has_session_start
        else "no session_start"
    )
    audit = f"seq audit FAILED ({session.seq_problem})" if session.seq_problem else "seq audit ok"
    dropped = (
        "no plugin_stats"
        if session.lines_dropped_total is None
        else (f"{session.lines_dropped_total} lines dropped")
    )
    ids = f"session {session.session_id}, park {session.park_id}"
    return [
        f"  {ids}: {start}",
        f"    seq {session.first_seq} to {session.last_seq}; {audit}; {dropped} (largest total)",
    ]


def _cost_lines(cost: PluginCost | None) -> list[str]:
    if cost is None:
        return [
            "Plugin cost: no judged rows (none with warmup false, clock performance and "
            "game speed 1), so no numbers."
        ]
    verdict = {True: "within", False: "OVER"}
    return [
        f"Plugin cost over {cost.judged_ticks} judged ticks:",
        f"  worst tick {cost.worst_tick_ms:.3f} ms (limit {WORST_TICK_LIMIT_MS:g} ms, "
        f"{verdict[cost.worst_within_limit]} the limit), in session "
        f"{cost.worst_tick_session_id} at game tick {cost.worst_tick_at_ticks}",
        f"  mean {cost.mean_tick_ms:.4f} ms per tick (limit {MEAN_TICK_LIMIT_MS:g} ms per tick, "
        f"{verdict[cost.mean_within_limit]} the limit)",
    ]


def render(summary: CaptureSummary, malformed_lines: int) -> str:
    """Render a summary as plain text, with units.

    Args:
        summary: The result of ``summarize``.
        malformed_lines: The converter's count of raw lines it could not parse.

    Returns:
        The report text, without the line about the plugin file being removed.
    """
    by_type = ", ".join(f"{kind} {count}" for kind, count in summary.events_by_type.items())
    lines = [
        f"Events landed this run: {summary.total_events}" + (f" ({by_type})" if by_type else "")
    ]
    lines.append(f"Sessions this run: {len(summary.sessions)}")
    for session in summary.sessions:
        lines.extend(_session_lines(session))
    lines.extend(_cost_lines(summary.cost))
    lines.append(f"Malformed raw lines in the whole raw folder (not converted): {malformed_lines}")
    lines.append(f"Monthly statements (finance_month) received: {summary.finance_months}")
    for warning in summary.earlier_violations:
        lines.append(f"WARNING, earlier run: {warning}")
    return "\n".join(lines)
