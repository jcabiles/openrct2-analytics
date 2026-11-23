"""A planted benchmark run for the judge's tests, written as Parquet by DuckDB.

``clean_plant`` builds a run that passes every rule, with the contracts' column names: car-ride
customers rising, boardings on each car ride one lag ahead of its customers, arrivals matching
admissions, and cohort members snapshotted daily. Tests change its rows, then write and judge
it. Not a test module itself, like ``tests/bench_standin_game.py``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import duckdb

from openrct2_analytics.ingest.bench_judge import RunFacts, RunJudgement, judge_run

SESSION = "session"
TICKS = 100
JUDGED_DAYS = 15
ADMISSIONS = 500
IN_PARK = 100
ARRIVALS_PER_DAY = 4
COHORT_DAYS = 5  # the first arrival of each of days 1 to 5 joins the cohort
LEAVER_DAY = 8  # the day-1 member leaves on this day
# ride ID: (ride type, classification, customers gained a day, guests on the ride)
RIDES: dict[int, tuple[int, str, int, int]] = {
    1: (52, "ride", 30, 20),  # lag ceil(20 / 30) = 1 day
    2: (51, "ride", 20, 30),  # lag ceil(30 / 20) = 2 days
    3: (20, "ride", 10, 5),  # the maze: no cars, so no boardings
    4: (28, "stall", 50, 0),
}
CAR_RIDES = (1, 2)
STATS_TIMES: dict[str, object] = {
    "worst_step_ms": 1.0,
    "worst_step_kind": "ride",
    "worst_tick_kind_ms": "ride:1.500|other:0.500",
    "worst_day_start_tick_ms": 1.5,
    "guest_fields_ms_total": 0.1,
    "lines_queued_max": 40,
}
TYPES: dict[str, dict[str, str]] = {
    "plugin_stats": {
        "session_id": "VARCHAR",
        "seq": "BIGINT",
        "game_ticks_elapsed": "BIGINT",
        "period_start_ticks": "BIGINT",
        "period_end_ticks": "BIGINT",
        "period_ticks": "BIGINT",
        "work_ms_total": "DOUBLE",
        "worst_tick_ms": "DOUBLE",
        "worst_tick_at_ticks": "BIGINT",
        "warmup": "BOOLEAN",
        "clock": "VARCHAR",
        "game_speed": "INTEGER",
        "lines_dropped_total": "BIGINT",
        "write_partial_total": "BIGINT",
        "work_units_total": "BIGINT",
        "work_items_skipped_total": "BIGINT",
        "work_queue_length": "INTEGER",
        "work_items_failed_total": "BIGINT",
        "worst_step_ms": "DOUBLE",
        "worst_step_kind": "VARCHAR",
        "worst_tick_kind_ms": "VARCHAR",
        "worst_day_start_tick_ms": "DOUBLE",
        "guest_fields_ms_total": "DOUBLE",
        "continuous_items_pending": "INTEGER",
        "lines_queued_max": "INTEGER",
        "guests_known": "INTEGER",
        "guests_known_in_park": "INTEGER",
        "arrivals_recorded_total": "BIGINT",
        "boarding_polls_total": "BIGINT",
        "boarders_queued_total": "BIGINT",
    },
    "session_start": {"session_id": "VARCHAR", "seq": "BIGINT"},
    "park_snapshot": {
        "session_id": "VARCHAR",
        "seq": "BIGINT",
        "game_ticks_elapsed": "BIGINT",
        "guests_in_park": "INTEGER",
        "total_admissions": "BIGINT",
    },
    "ride_snapshot": {
        "session_id": "VARCHAR",
        "seq": "BIGINT",
        "game_ticks_elapsed": "BIGINT",
        "ride_id": "INTEGER",
        "ride_type": "INTEGER",
        "classification": "VARCHAR",
        "total_customers": "BIGINT",
        "guests_on_ride": "INTEGER",
    },
    "guest_arrived": {
        "session_id": "VARCHAR",
        "seq": "BIGINT",
        "game_ticks_elapsed": "BIGINT",
        "guest_key": "INTEGER",
        "generated_at_ticks": "BIGINT",
        "in_cohort": "BOOLEAN",
    },
    "guest_left": {
        "session_id": "VARCHAR",
        "seq": "BIGINT",
        "game_ticks_elapsed": "BIGINT",
        "guest_key": "INTEGER",
        "in_cohort": "BOOLEAN",
    },
    "guest_refused": {
        "session_id": "VARCHAR",
        "seq": "BIGINT",
        "game_ticks_elapsed": "BIGINT",
        "guest_key": "INTEGER",
        "thought_type": "VARCHAR",
    },
    "guest_snapshot": {
        "session_id": "VARCHAR",
        "seq": "BIGINT",
        "game_ticks_elapsed": "BIGINT",
        "guest_key": "INTEGER",
    },
    "guest_boarded": {
        "session_id": "VARCHAR",
        "seq": "BIGINT",
        "game_ticks_elapsed": "BIGINT",
        "ride_id": "INTEGER",
        "detected_at_ticks": "BIGINT",
    },
}
GUEST_FILES = ("guest_arrived", "guest_left", "guest_refused", "guest_snapshot", "guest_boarded")
Row = dict[str, object]


def write_table(
    connection: duckdb.DuckDBPyConnection, path: Path, table: str, rows: list[Row]
) -> None:
    """Write ``rows`` (any subset of ``TYPES[table]``'s columns) as one Parquet file."""
    columns = TYPES[table]
    names = [name for name in columns if not rows or name in rows[0]]
    connection.execute(
        f"CREATE OR REPLACE TABLE t ({', '.join(f'{n} {columns[n]}' for n in names)})"
    )
    if rows:
        marks = ", ".join("?" for _ in names)
        connection.executemany(
            f"INSERT INTO t VALUES ({marks})", [[r[n] for n in names] for r in rows]
        )
    connection.execute(f"COPY t TO '{path}' (FORMAT PARQUET)")


def write_audit(connection: duckdb.DuckDBPyConnection, root: Path) -> None:
    """A clean ``seq`` audit for ``SESSION``."""
    (root / "audit").mkdir(parents=True, exist_ok=True)
    connection.execute(
        "COPY (SELECT 'park' AS park_id, ? AS session_id, 1::BIGINT AS first_seq, "
        "99::BIGINT AS last_seq, 99::BIGINT AS row_count, 0::BIGINT AS missing, "
        "0::BIGINT AS duplicates, 1::BIGINT AS park_count) "
        f"TO '{root / 'audit' / 'seq_audit.parquet'}' (FORMAT PARQUET)",
        [SESSION],
    )


@dataclass
class Plant:
    """A planted run: rows per table, in ``seq`` order."""

    tables: dict[str, list[Row]]
    judged_days: int

    def rows(self, table: str) -> list[Row]:
        return self.tables[table]

    @property
    def last(self) -> Row:
        return self.tables["plugin_stats"][-1]

    def keep(self, table: str, wanted: Callable[[Row], bool]) -> None:
        """Keep only the rows of ``table`` for which ``wanted(row)`` is true."""
        self.tables[table] = [row for row in self.tables[table] if wanted(row)]

    def write(self, root: Path, *, drop: tuple[str, str] | None = None) -> Path:
        """Write the run under ``root``; ``drop`` leaves one (table, column) out."""
        (root / "v1").mkdir(parents=True)
        connection = duckdb.connect(":memory:")
        try:
            for table, rows in self.tables.items():
                if drop is not None and drop[0] == table:
                    rows = [{k: v for k, v in row.items() if k != drop[1]} for row in rows]
                write_table(connection, root / "v1" / f"{table}.parquet", table, rows)
            write_audit(connection, root)
        finally:
            connection.close()
        return root

    def judge(self, root: Path, *, drop: tuple[str, str] | None = None) -> RunJudgement:
        facts = RunFacts(self.write(root, drop=drop), self.judged_days, "a" * 40, "a" * 40, 0)
        return judge_run(facts, coverage_threshold=0.90)


def _stats(day: int, totals: dict[str, int]) -> Row:
    start = day * TICKS
    return {
        "session_id": SESSION,
        "game_ticks_elapsed": start + TICKS,
        "period_start_ticks": start,
        "period_end_ticks": start + TICKS,
        "period_ticks": TICKS,
        "work_ms_total": 10.0,
        "worst_tick_ms": 2.0,
        "worst_tick_at_ticks": start + 25,
        "warmup": day == 0,
        "clock": "performance",
        "game_speed": 1,
        "lines_dropped_total": 0,
        "write_partial_total": 0,
        "work_units_total": 10,
        "work_items_skipped_total": 0,
        "work_queue_length": 0,
        "work_items_failed_total": 0,
        "continuous_items_pending": 0,
        "guests_known": IN_PARK,
        "guests_known_in_park": IN_PARK,
        "boarding_polls_total": day * (TICKS // 20),
        **STATS_TIMES,
        **totals,
    }


def _day_events(
    day: int, members: dict[int, int], left: dict[int, int]
) -> list[tuple[int, str, Row]]:
    """One judged day's events: snapshots, arrivals, boardings, cohort snapshots and exits."""
    start = day * TICKS
    events: list[tuple[int, str, Row]] = []
    for ride, (ride_type, classification, rise, aboard) in RIDES.items():
        customers = 1000 + rise * (day - 1)
        snapshot = {"ride_id": ride, "ride_type": ride_type, "classification": classification}
        snapshot.update(total_customers=customers, guests_on_ride=aboard)
        events.append((start + 10, "ride_snapshot", snapshot))
        if ride in CAR_RIDES:
            board = {"ride_id": ride, "detected_at_ticks": start + 40}
            events += [(start + 41, "guest_boarded", dict(board)) for _ in range(rise)]
    for number in range(ARRIVALS_PER_DAY):
        key = day * 10 + number
        joins = number == 0 and day <= COHORT_DAYS
        arrived: Row = {"guest_key": key, "generated_at_ticks": start + 20, "in_cohort": joins}
        events.append((start + 21, "guest_arrived", arrived))
        if joins:
            members[key] = start + 20
    if day == LEAVER_DAY:
        left[10] = start + 30
        events.append((start + 30, "guest_left", {"guest_key": 10, "in_cohort": True}))
    for key, generated in members.items():
        if generated < start and key not in left:
            events.append((start + 60, "guest_snapshot", {"guest_key": key}))
    if day == 1:
        refusals = ("bad_value", "bad_value", "intense")
        events += [
            (start + 70, "guest_refused", {"guest_key": 11, "thought_type": t}) for t in refusals
        ]
    return events


def clean_plant(judged_days: int = JUDGED_DAYS) -> Plant:
    """A planted run that passes every rule."""
    events: list[tuple[int, str, Row]] = []
    members: dict[int, int] = {}
    left: dict[int, int] = {}
    totals = {"arrivals_recorded_total": 0, "boarders_queued_total": 0}
    for day in range(judged_days + 1):
        if day > 0:
            today = _day_events(day, members, left)
            totals["arrivals_recorded_total"] += sum(e[1] == "guest_arrived" for e in today)
            totals["boarders_queued_total"] += sum(e[1] == "guest_boarded" for e in today)
            events += today
        end = (day + 1) * TICKS
        events.append((end, "plugin_stats", _stats(day, dict(totals))))
        park: Row = {
            "guests_in_park": IN_PARK,
            "total_admissions": ADMISSIONS + ARRIVALS_PER_DAY * day,
        }
        events.append((end, "park_snapshot", park))
    tables: dict[str, list[Row]] = {name: [] for name in TYPES}
    tables["session_start"].append({"session_id": SESSION, "seq": 1})
    for seq, (tick, table, row) in enumerate(sorted(events, key=lambda e: e[0]), start=2):
        tables[table].append({"session_id": SESSION, "seq": seq, "game_ticks_elapsed": tick, **row})
    return Plant(tables, judged_days)


def thin_boardings(plant: Plant, ride: int, per_day: int, days: range) -> None:
    """Delete ``per_day`` of ``ride``'s boardings on each day in ``days``."""
    dropped: dict[int, int] = {}
    kept = []
    for row in plant.rows("guest_boarded"):
        day = int(str(row["detected_at_ticks"])) // TICKS
        if row["ride_id"] == ride and day in days and dropped.get(day, 0) < per_day:
            dropped[day] = dropped.get(day, 0) + 1
            continue
        kept.append(row)
    plant.tables["guest_boarded"] = kept
    plant.last["boarders_queued_total"] = len(kept)
