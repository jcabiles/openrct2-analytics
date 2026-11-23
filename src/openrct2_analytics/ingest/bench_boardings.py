"""Judge one benchmark run's boardings against the game's customer counters (rule 7).

The game counts a rider in ``total_customers`` on leaving, 1 to 7 game days after the
boarding on the benchmark park, so the rule has three parts. (a) On running totals: every
judged period whose ride customers rose since each ride's first snapshot has at least one
``guest_boarded`` row by its end. (b) Over a lagged window: on car rides, boardings reach the
coverage threshold times the customers counted one lag later. (c) Over the same window: on all
car rides, boardings stay within ``MAX_BOARDING_RATIO`` times those customers, and on each car
ride whose customers rose, within that ratio times its own plus ``RIDE_BOARDING_SLACK``. Only
``ride_snapshot`` rows of classification ``ride`` count. ``bench_guests`` calls
``judge_boardings`` and owns part (b)'s threshold.
"""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass

import duckdb

# Ride types with no cars, which record no boardings: 20 is the maze, the benchmark fixture's
# only carless ride. An unlisted carless ride counts as a car ride, so it fails rule 7 (b).
CARLESS_RIDE_TYPES = frozenset({20})
MIN_COVERAGE_SPAN_DAYS = 10
# Every rule 7 (b) ratio failure starts with this; the verdict's calibration rule reads it.
COVERAGE_FAILED = "boarding coverage below the threshold:"
# Rule 7 (c): run B's car rides whose customers rose gave ratios of 0.740 to 1.279, so 1.5
# clears a correct capture while failing a seat poll that re-reports seated guests.
MAX_BOARDING_RATIO = 1.5
# Rule 7 (c) per ride: rows a ride whose customers rose may have beyond MAX_BOARDING_RATIO times
# its own lagged customers, so a small ride's lumpy train loads do not fail a correct capture,
# while one ride's double counting cannot hide in the other rides' room under the summed bound.
RIDE_BOARDING_SLACK = 20
BOARDINGS_ABOVE = "boardings above the upper bound:"


@dataclass(frozen=True)
class StatsPeriod:
    """One ``plugin_stats`` period, from its start tick up to (not including) its end tick.

    Attributes:
        start: ``period_start_ticks``.
        end: ``period_end_ticks``.
    """

    start: int
    end: int

    def contains(self, tick: int) -> bool:
        """Return whether an event at game tick ``tick`` falls in the period."""
        return self.start <= tick < self.end


@dataclass(frozen=True)
class PeriodBoardings:
    """One judged period's own rise in ride customers and its ``guest_boarded`` rows.

    Attributes:
        customers_rise: The period's rise in ``total_customers`` over rides of class ``ride``.
        boardings: ``guest_boarded`` rows emitted in the period.
    """

    customers_rise: int
    boardings: int


@dataclass(frozen=True)
class RideCoverage:
    """Rule 7 (b) for one car ride whose customers rose over the judged rows.

    Attributes:
        ride_id: The ride.
        lag_days: Its mean time aboard by Little's law, rounded up to whole game days.
        boardings: Its boardings in the window, or None when the window cannot be judged.
        customers: Its customers one lag later, or None when the window cannot be judged.
        ratio: Boardings over customers, or None when either is missing or no customer rose.
    """

    ride_id: int
    lag_days: int
    boardings: int | None
    customers: int | None
    ratio: float | None


@dataclass(frozen=True)
class Coverage:
    """Rule 7 (b)'s ratio for the run and per car ride.

    Attributes:
        ratio: Summed boardings over summed lagged customers; None when no customer rose.
        rides: Each car ride whose customers rose, by ride ID.
    """

    ratio: float | None
    rides: tuple[RideCoverage, ...]


@dataclass(frozen=True)
class BoardingJudgement:
    """Rule 7's result for one run.

    Attributes:
        reasons: Failed rule 7 checks, part (a) first.
        periods: Each judged period's rise in customers and boardings.
        coverage: Part (b)'s ratios.
    """

    reasons: tuple[str, ...]
    periods: tuple[PeriodBoardings, ...]
    coverage: Coverage


@dataclass(frozen=True)
class _Snapshot:
    """One ``ride_snapshot`` row of classification ``ride``."""

    ride_id: int
    ride_type: int
    customers: int
    on_ride: int | None
    tick: int


# One map from ride ID to its first snapshot in each judged period, in period order.
_Grouped = list[dict[int, _Snapshot]]


def _grouped(
    connection: duckdb.DuckDBPyConnection, session_id: str, periods: tuple[StatsPeriod, ...]
) -> tuple[_Grouped, dict[int, int]]:
    """Group the session's ride snapshots by judged period; also each ride's first customers."""
    rows = connection.execute(
        "SELECT ride_id, ride_type, total_customers, guests_on_ride, game_ticks_elapsed "
        "FROM ride_snapshot WHERE session_id = ? AND classification = 'ride' "
        "ORDER BY game_ticks_elapsed",
        [session_id],
    ).fetchall()
    grouped: _Grouped = [{} for _ in periods]
    first: dict[int, int] = {}
    for row in rows:
        snapshot = _Snapshot(*row)
        first.setdefault(snapshot.ride_id, snapshot.customers)
        for index, period in enumerate(periods):
            if period.contains(snapshot.tick):
                grouped[index].setdefault(snapshot.ride_id, snapshot)
                break
    return grouped, first


def _running_totals(
    grouped: _Grouped,
    first: dict[int, int],
    periods: tuple[StatsPeriod, ...],
    boarded_ticks: list[int],
) -> tuple[list[str], tuple[PeriodBoardings, ...]]:
    """Part (a), and each judged period's own rise in customers and boardings."""
    # The warm-up period holds no ride snapshot (the first day callback queues the first
    # ones), so each ride's first snapshot in the session stands in for the warm-up rows.
    reasons: list[str] = []
    rows: list[PeriodBoardings] = []
    previous = 0
    for position, (period, snapshots) in enumerate(zip(periods, grouped, strict=True), start=1):
        rise = sum(s.customers - first[s.ride_id] for s in snapshots.values())
        by_end = bisect_left(boarded_ticks, period.end)
        rows.append(
            PeriodBoardings(rise - previous, by_end - bisect_left(boarded_ticks, period.start))
        )
        previous = rise
        if rise > 0 and by_end == 0:
            reasons.append(
                f"judged row {position} gained {rise} ride customers with no guest_boarded row "
                "by its end"
            )
    return reasons, tuple(rows)


def _lag(grouped: _Grouped, ride: int) -> tuple[int | None, str | None]:
    """A car ride's lag in game days, or None when its customers did not rise; or why not known.

    Mean time aboard by Little's law, from the judged rows: mean ``guests_on_ride`` over the
    rise in customers per game day, a judged period being one game day. A ride whose customers
    rose with no ``guests_on_ride`` reading has no known lag and cannot be judged.
    """
    indexes = [index for index, snapshots in enumerate(grouped) if ride in snapshots]
    rise = grouped[indexes[-1]][ride].customers - grouped[indexes[0]][ride].customers
    if rise <= 0:
        return None, None
    known = [grouped[i][ride].on_ride for i in indexes if grouped[i][ride].on_ride is not None]
    if not known:
        return None, f"ride {ride}'s customers rose but no ride_snapshot reports guests_on_ride"
    days = indexes[-1] - indexes[0]
    return -(-(sum(v or 0 for v in known) * days) // (len(known) * rise)), None  # rounded up


def _ride_coverage(
    connection: duckdb.DuckDBPyConnection,
    session_id: str,
    grouped: _Grouped,
    *,
    ride: int,
    lag: int,
    start: int,
) -> tuple[str | None, RideCoverage]:
    """One car ride over the lagged window: why it cannot be judged, or its counts."""
    end = len(grouped) - 1
    absent = sorted({i + 1 for i in (start, end - lag, start + lag, end) if ride not in grouped[i]})
    if absent:
        reason = f"ride {ride} has no ride_snapshot in judged rows {absent} of its boarding window"
        return reason, RideCoverage(ride, lag, None, None, None)
    found = connection.execute(
        "SELECT count(*) FROM guest_boarded WHERE session_id = ? AND ride_id = ? "
        "AND detected_at_ticks BETWEEN ? AND ?",
        [session_id, ride, grouped[start][ride].tick, grouped[end - lag][ride].tick],
    ).fetchone()
    boardings = 0 if found is None else int(found[0])
    customers = grouped[end][ride].customers - grouped[start + lag][ride].customers
    ratio = boardings / customers if customers > 0 else None
    return None, RideCoverage(ride, lag, boardings, customers, ratio)


def _upper_bound(
    connection: duckdb.DuckDBPyConnection,
    session_id: str,
    grouped: _Grouped,
    *,
    rides: list[RideCoverage],
    flat: list[int],
    start: int,
) -> list[str]:
    """Part (c): boardings on all car rides, and on each ride that rose, stay within the bound.

    A car ride whose customers did not rise has no lag of its own, so it takes the largest:
    its window is the part every other ride's window shares. Its lagged customers are 0 over
    any span, so it needs no minimum span; part (b) checks the span of the rides that rose. When
    twice the largest lag passes the last judged row, that ride's span already fails part (b),
    and the window holds no judged row for the others.
    """
    reasons: list[str] = []
    boardings = sum(r.boardings or 0 for r in rides)
    for ride in flat if 2 * start < len(grouped) else []:
        reason, ride_coverage = _ride_coverage(
            connection, session_id, grouped, ride=ride, lag=start, start=start
        )
        reasons.extend([] if reason is None else [reason])
        boardings += ride_coverage.boardings or 0
    customers = sum(r.customers or 0 for r in rides)
    if boardings > MAX_BOARDING_RATIO * customers:
        reasons.append(
            f"{BOARDINGS_ABOVE} {boardings} boardings against {customers} lagged customers on "
            f"car rides, more than {MAX_BOARDING_RATIO:g} times"
        )
    for coverage in rides:
        found, rise = coverage.boardings, coverage.customers
        if found is None or rise is None or rise <= 0:
            continue
        if found > MAX_BOARDING_RATIO * rise + RIDE_BOARDING_SLACK:
            reasons.append(
                f"{BOARDINGS_ABOVE} ride {coverage.ride_id}'s {found} boardings against its "
                f"{rise} lagged customers, more than {MAX_BOARDING_RATIO:g} times plus "
                f"{RIDE_BOARDING_SLACK}"
            )
    return reasons


def _coverage(
    connection: duckdb.DuckDBPyConnection,
    session_id: str,
    grouped: _Grouped,
    threshold: float,
) -> tuple[list[str], Coverage]:
    """Parts (b) and (c): boardings on car rides against the customers over the lagged window."""
    reasons: list[str] = []
    lags: dict[int, int] = {}
    flat: list[int] = []
    car_rides = {
        ride
        for snapshots in grouped
        for ride, snapshot in snapshots.items()
        if snapshot.ride_type not in CARLESS_RIDE_TYPES
    }
    for ride in sorted(car_rides):
        lag, unknown = _lag(grouped, ride)
        reasons.extend([] if unknown is None else [unknown])
        if lag is not None:
            lags[ride] = lag
        elif unknown is None:
            flat.append(ride)
    # The window starts K game days after the first judged period, K the largest lag (0 when
    # no car ride's customers rose).
    start = max(lags.values(), default=0)
    rides: list[RideCoverage] = []
    for ride, lag in lags.items():
        span = len(grouped) - 1 - lag - start
        if span < MIN_COVERAGE_SPAN_DAYS:
            reasons.append(
                f"ride {ride}'s lagged boarding window is {span} game days, under "
                f"{MIN_COVERAGE_SPAN_DAYS}, so its coverage cannot be judged"
            )
            rides.append(RideCoverage(ride, lag, None, None, None))
            continue
        reason, ride_coverage = _ride_coverage(
            connection, session_id, grouped, ride=ride, lag=lag, start=start
        )
        reasons.extend([] if reason is None else [reason])
        rides.append(ride_coverage)
    boardings = sum(r.boardings or 0 for r in rides)
    customers = sum(r.customers or 0 for r in rides)
    ratio = boardings / customers if customers > 0 else None
    if ratio is not None and boardings < threshold * customers:
        reasons.append(
            f"{COVERAGE_FAILED} {boardings} boardings against {customers} lagged customers on "
            f"car rides, a ratio of {ratio:.3f} under {threshold:g}"
        )
    reasons += _upper_bound(connection, session_id, grouped, rides=rides, flat=flat, start=start)
    return reasons, Coverage(ratio, tuple(rides))


def judge_boardings(
    connection: duckdb.DuckDBPyConnection,
    session_id: str,
    periods: tuple[StatsPeriod, ...],
    threshold: float,
) -> BoardingJudgement:
    """Judge rule 7 over the judged periods of one session.

    Args:
        connection: A connection with ``ride_snapshot`` and ``guest_boarded`` views.
        session_id: The judged session.
        periods: The judged periods, in order.
        threshold: Part (b)'s coverage threshold.

    Returns:
        The failed rule 7 checks, each period's customers and boardings, and part (b)'s ratios.
    """
    grouped, first = _grouped(connection, session_id, periods)
    boarded_ticks = sorted(
        int(row[0])
        for row in connection.execute(
            "SELECT game_ticks_elapsed FROM guest_boarded WHERE session_id = ?", [session_id]
        ).fetchall()
    )
    reasons, rows = _running_totals(grouped, first, periods, boarded_ticks)
    coverage_reasons, coverage = _coverage(connection, session_id, grouped, threshold)
    return BoardingJudgement((*reasons, *coverage_reasons), rows, coverage)
