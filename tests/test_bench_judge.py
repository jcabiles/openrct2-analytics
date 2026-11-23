from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import cast

import duckdb
import pytest

from openrct2_analytics.ingest.bench_judge import NOT_JUDGED, RunFacts, judge_run, unjudged_run
from openrct2_analytics.ingest.capture_report import CostRow, judge_cost
from tests.bench_plant import GUEST_FILES, write_table

JUDGED_DAYS = 2


def _facts(tmp_path: Path, **changes: object) -> RunFacts:
    defaults: dict[str, object] = {
        "judged_days": JUDGED_DAYS,
        "fixture_sha1_before": "before",
        "fixture_sha1_after": "before",
        "malformed_lines": 0,
    }
    defaults.update(changes)
    return RunFacts(
        tmp_path,
        cast(int, defaults["judged_days"]),
        cast(str, defaults["fixture_sha1_before"]),
        cast(str, defaults["fixture_sha1_after"]),
        cast(int, defaults["malformed_lines"]),
    )


@dataclass
class _RunOptions:
    stat_count: int = JUDGED_DAYS + 1
    updates: dict[int, dict[str, object]] | None = None
    extra_rows: list[dict[str, object]] | None = None
    audit_missing: int = 0
    audit_duplicates: int = 0
    audit_first_seq: int = 1
    session_start_seq: int | None = 1
    extra_session_start: bool = False
    include_rides: bool = True
    include_new_columns: bool = True
    missing_ride_index: int | None = None


def _write_run(tmp_path: Path, options: _RunOptions | None = None) -> None:
    options = options or _RunOptions()
    v1, audit = tmp_path / "v1", tmp_path / "audit"
    v1.mkdir()
    audit.mkdir()
    connection = duckdb.connect(":memory:")
    try:
        columns = (
            "session_id VARCHAR, seq BIGINT, period_start_ticks BIGINT, "
            "period_end_ticks BIGINT, period_ticks BIGINT, work_ms_total DOUBLE, "
            "worst_tick_ms DOUBLE, worst_tick_at_ticks BIGINT, warmup BOOLEAN, "
            "clock VARCHAR, game_speed INTEGER, lines_dropped_total BIGINT, "
            "write_partial_total BIGINT, work_units_total BIGINT, "
            "work_items_skipped_total BIGINT, work_queue_length BIGINT, "
            "game_ticks_elapsed BIGINT, work_items_failed_total BIGINT, worst_step_ms DOUBLE, "
            "worst_step_kind VARCHAR, worst_tick_kind_ms VARCHAR, worst_day_start_tick_ms DOUBLE, "
            "guest_fields_ms_total DOUBLE, continuous_items_pending INTEGER, "
            "lines_queued_max INTEGER, guests_known INTEGER, guests_known_in_park INTEGER, "
            "arrivals_recorded_total BIGINT, boarding_polls_total BIGINT, "
            "boarders_queued_total BIGINT"
        )
        connection.execute(f"CREATE TABLE plugin_stats ({columns})")
        rows = [_stat_row(index) for index in range(options.stat_count)]
        for index, change in (options.updates or {}).items():
            rows[index].update(change)
        rows.extend(options.extra_rows or [])
        names = list(rows[0])
        if not options.include_new_columns:
            names = [name for name in names if name not in _NEW_COLUMNS]
        placeholders = ", ".join("?" for _ in names)
        connection.executemany(
            f"INSERT INTO plugin_stats ({', '.join(names)}) VALUES ({placeholders})",
            [tuple(row[name] for name in names) for row in rows],
        )
        _copy(connection, "plugin_stats", v1 / "plugin_stats.parquet", names)
        connection.execute("CREATE TABLE session_start (session_id VARCHAR, seq BIGINT)")
        if options.session_start_seq is not None:
            connection.execute(
                "INSERT INTO session_start VALUES ('session', ?)", [options.session_start_seq]
            )
        if options.extra_session_start:
            connection.execute("INSERT INTO session_start VALUES ('other', 1)")
        _copy(connection, "session_start", v1 / "session_start.parquet", ["session_id", "seq"])
        connection.execute(
            "CREATE TABLE seq_audit (park_id VARCHAR, session_id VARCHAR, "
            "first_seq BIGINT, last_seq BIGINT, row_count BIGINT, missing BIGINT, "
            "duplicates BIGINT, park_count BIGINT)"
        )
        connection.execute(
            "INSERT INTO seq_audit VALUES ('park', 'session', ?, 99, 99, ?, ?, 1)",
            [options.audit_first_seq, options.audit_missing, options.audit_duplicates],
        )
        _copy(
            connection,
            "seq_audit",
            audit / "seq_audit.parquet",
            [
                "park_id",
                "session_id",
                "first_seq",
                "last_seq",
                "row_count",
                "missing",
                "duplicates",
                "park_count",
            ],
        )
        park = [
            {**_PARK, "session_id": row["session_id"], "seq": 100 + index}
            | {"game_ticks_elapsed": row["game_ticks_elapsed"]}
            for index, row in enumerate(rows)
        ]
        write_table(connection, v1 / "park_snapshot.parquet", "park_snapshot", park)
        for name in GUEST_FILES:
            write_table(connection, v1 / f"{name}.parquet", name, [])
        if options.include_rides:
            connection.execute(
                "CREATE TABLE ride_snapshot (session_id VARCHAR, game_ticks_elapsed BIGINT, "
                "ride_id INTEGER, ride_type INTEGER, classification VARCHAR, "
                "total_customers BIGINT, guests_on_ride INTEGER)"
            )
            for index, row in enumerate(rows):
                if (
                    row["session_id"] == "session"
                    and index != 0
                    and index != options.missing_ride_index
                ):
                    connection.execute(
                        "INSERT INTO ride_snapshot VALUES (?, ?, 1, 52, 'ride', 1000, 4)",
                        [row["session_id"], row["period_start_ticks"]],
                    )
            ride_names = ["session_id", "game_ticks_elapsed", "ride_id", "ride_type"]
            ride_names += ["classification", "total_customers", "guests_on_ride"]
            _copy(connection, "ride_snapshot", v1 / "ride_snapshot.parquet", ride_names)
    finally:
        connection.close()


def _stat_row(index: int) -> dict[str, object]:
    start = index * 100
    return {
        "session_id": "session",
        "seq": index + 2,
        "period_start_ticks": start,
        "period_end_ticks": start + 100,
        "period_ticks": 100,
        "work_ms_total": float(index + 1),
        "worst_tick_ms": float(index + 1),
        "worst_tick_at_ticks": start + 25,
        "warmup": index == 0,
        "clock": "performance",
        "game_speed": 1,
        "lines_dropped_total": 0,
        "write_partial_total": 0,
        "work_units_total": 10,
        "work_items_skipped_total": 0,
        "work_queue_length": 0,
        "game_ticks_elapsed": start + 100,
        "work_items_failed_total": 0,
        "worst_step_ms": 1.0,
        "worst_step_kind": "ride",
        "worst_tick_kind_ms": f"ride:{index + 1}.000",
        "worst_day_start_tick_ms": float(index + 1),
        "guest_fields_ms_total": 0.0,
        "continuous_items_pending": 0,
        "lines_queued_max": 3,
        "guests_known": _PARK["guests_in_park"],
        "guests_known_in_park": _PARK["guests_in_park"],
        "arrivals_recorded_total": 0,
        "boarding_polls_total": index * 5,
        "boarders_queued_total": 0,
    }


# Each statistics row's park_snapshot, built on its tick: no admissions, so no arrivals.
_PARK: dict[str, object] = {"guests_in_park": 50, "total_admissions": 9}


def _copy(connection: duckdb.DuckDBPyConnection, table: str, path: Path, names: list[str]) -> None:
    connection.execute(
        f"COPY (SELECT {', '.join(names)} FROM {table}) TO '{path}' (FORMAT PARQUET)"
    )


_NEW_COLUMNS = {"work_units_total", "work_items_skipped_total", "work_queue_length"}


def test_clean_run_is_valid_complete_and_costed(tmp_path: Path) -> None:
    _write_run(tmp_path)
    judgement = judge_run(_facts(tmp_path))
    assert judgement.valid and judgement.complete and judgement.reasons == ()
    assert judgement.cost == judge_cost(
        [CostRow("session", 100, 2.0, 2.0, 125), CostRow("session", 100, 3.0, 3.0, 225)]
    )
    assert judgement.worst_tick_offset_ticks == 25 and judgement.work_units_total == 10


@pytest.mark.parametrize(
    ("update", "reason"),
    [
        ({"game_speed": 2}, "judged row 1 has game_speed other than 1"),
        ({"warmup": True}, "judged row 1 is marked warmup"),
        ({"clock": "date"}, "judged row 1 does not use the performance clock"),
        ({"period_ticks": 0}, "judged row 1 has no period ticks"),
    ],
)
def test_judged_row_qualification_rules(
    tmp_path: Path, update: dict[str, object], reason: str
) -> None:
    _write_run(tmp_path, _RunOptions(updates={1: update}))
    assert judge_run(_facts(tmp_path)).validity_reasons == (reason,)


@pytest.mark.parametrize(
    ("options", "reason"),
    [
        (
            _RunOptions(extra_rows=[{**_stat_row(3), "session_id": "zother"}]),
            "plugin_stats rows belong to more than one session",
        ),
        (_RunOptions(stat_count=2), "plugin_stats has fewer than 3 rows"),
        (_RunOptions(audit_missing=1), "session seq audit is not clean"),
        (_RunOptions(audit_duplicates=1), "session seq audit is not clean"),
        (_RunOptions(audit_first_seq=2), "session seq audit is not clean"),
        (_RunOptions(session_start_seq=None), "session has no session_start at seq 1"),
        (_RunOptions(session_start_seq=2), "session has no session_start at seq 1"),
        (
            _RunOptions(extra_session_start=True),
            "audit or session_start contains a different session",
        ),
    ],
)
def test_validity_rules(tmp_path: Path, options: _RunOptions, reason: str) -> None:
    _write_run(tmp_path, options)
    assert reason in judge_run(_facts(tmp_path)).validity_reasons


def test_row_one_must_be_the_warmup(tmp_path: Path) -> None:
    _write_run(tmp_path, _RunOptions(updates={0: {"warmup": False}}))
    assert judge_run(_facts(tmp_path)).validity_reasons == (
        "plugin_stats row 1 is not marked warmup",
    )


def test_a_run_with_more_rows_than_judged_is_judged_on_the_first_rows(tmp_path: Path) -> None:
    _write_run(tmp_path, _RunOptions(stat_count=JUDGED_DAYS + 3))
    assert judge_run(_facts(tmp_path)).valid


@pytest.mark.parametrize(
    ("facts", "reason"),
    [
        ({"fixture_sha1_after": "after"}, "fixture changed during the run"),
        ({"malformed_lines": 1}, "malformed plugin output lines were found"),
    ],
)
def test_external_validity_rules(tmp_path: Path, facts: dict[str, object], reason: str) -> None:
    _write_run(tmp_path)
    assert judge_run(_facts(tmp_path, **facts)).validity_reasons == (reason,)


@pytest.mark.parametrize(
    "options",
    [
        _RunOptions(updates={1: {"work_queue_length": 1}}),
        _RunOptions(missing_ride_index=1),
        _RunOptions(include_rides=False),
        _RunOptions(updates={2: {"lines_dropped_total": 1}}),
        _RunOptions(updates={2: {"work_items_skipped_total": 1}}),
        _RunOptions(updates={2: {"write_partial_total": 1}}),
        _RunOptions(include_new_columns=False),
    ],
)
def test_completion_rules(tmp_path: Path, options: _RunOptions) -> None:
    _write_run(tmp_path, options)
    judgement = judge_run(_facts(tmp_path))
    assert judgement.valid and not judgement.complete and judgement.completion_reasons


def test_validity_and_completion_reasons_are_separate(tmp_path: Path) -> None:
    _write_run(tmp_path, _RunOptions(updates={1: {"clock": "date", "work_queue_length": 1}}))
    judgement = judge_run(_facts(tmp_path))
    assert judgement.validity_reasons == ("judged row 1 does not use the performance clock",)
    assert judgement.completion_reasons == ("judged row 1 has work_queue_length not equal to 0",)
    assert judgement.reasons == judgement.validity_reasons + judgement.completion_reasons


def test_judged_days_below_one_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="judged_days"):
        judge_run(_facts(tmp_path, judged_days=0))


def test_rows_after_window_are_ignored_for_cost(tmp_path: Path) -> None:
    _write_run(
        tmp_path,
        _RunOptions(stat_count=4, updates={3: {"work_ms_total": 10000.0, "worst_tick_ms": 999.0}}),
    )
    assert judge_run(_facts(tmp_path)).cost == judge_cost(
        [CostRow("session", 100, 2.0, 2.0, 125), CostRow("session", 100, 3.0, 3.0, 225)]
    )


def test_a_run_with_no_judgeable_data_is_invalid_for_its_reasons() -> None:
    judgement = unjudged_run(["timed out", "fixture changed during the run"])

    assert not judgement.valid and not judgement.complete
    assert judgement.validity_reasons == ("timed out", "fixture changed during the run")
    assert judgement.completion_reasons == (NOT_JUDGED,)
    assert judgement.cost is None and judgement.lines_dropped_total is None
