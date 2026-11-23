"""Print results for one data set.

Exit 0 on success, 1 on read failure, 2 on refusal, and 130 on interrupt.
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Never, cast

import duckdb

from openrct2_analytics.config import DATA_SETS, ConfigError, landing_dirs
from openrct2_analytics.ingest import lock
from openrct2_analytics.ingest.capture_report import (
    AUDIT_FILE,
    JUDGED_COST_FILTER,
    MEAN_TICK_LIMIT_MS,
    WORST_TICK_LIMIT_MS,
    CostRow,
    judge_cost,
)
from openrct2_analytics.ingest.landing_paths import project_path
from openrct2_analytics.ingest.publish_audit import open_warehouse

PROJECT_DIR = Path(__file__).resolve().parents[3]
ROW_CAP = 40

# Printed headings for columns whose names carry no unit (units from the models' YAML).
HEADING_UNITS = {
    "operating_profit": "operating_profit (US dollars)",
    "park_rating": "park_rating (rating points)",
}

# Heading, relation, printed columns, key order, and any extra model needed by the query.
TABLES = (
    (
        "Sessions (game date)",
        "staging.stg_session_start",
        "park_id, session_id, park_name, scenario_name, headless, "
        "game_year, game_month, game_day, emitted_at",
        "park_id, session_id",
        (),
    ),
    (
        "Park days (game date and company date)",
        "marts.fct_park_day",
        "park_id, game_year, game_month, game_day, company_date, guests_in_park, "
        "admissions_increase, park_rating, cash_usd, is_kept_operating_day",
        "park_id, game_year, game_month, game_day",
        (),
    ),
    (
        "Months (company month)",
        "marts.fct_park_month",
        "park_id, statement_year, statement_month, company_year, "
        "net_cash_change_usd, operating_profit, cash_usd, bank_loan_usd",
        "park_id, statement_year, statement_month",
        (),
    ),
    (
        "Rides and stalls (game date)",
        "marts.fct_ride_day",
        "park_id, game_year, game_month, game_day, ride_name, "
        "classification, customers_increase, profit_usd",
        "park_id, game_year, game_month, game_day, ride_key",
        ("dim_ride",),
    ),
    (
        "Cleaning rule counts",
        "marts.fct_cleaning_rule_count",
        "rule_name, model_name, rows_in, rows_kept, rows_excluded, rows_changed",
        "rule_name, model_name",
        (),
    ),
)


class _Refused(Exception):
    """The command was refused before reading anything."""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


class _ResultsParser(argparse.ArgumentParser):
    """Argument parser that reports invalid input as a results refusal."""

    def error(self, message: str) -> Never:
        raise _Refused("usage", message)


def _successful_models(results: object) -> set[str]:
    if not isinstance(results, list):
        return set()
    built: set[str] = set()
    for result in results:
        if not isinstance(result, dict) or result.get("status") != "success":
            continue
        unique_id = result.get("unique_id")
        if not isinstance(unique_id, str):
            node = result.get("node")
            unique_id = node.get("unique_id") if isinstance(node, dict) else None
        if isinstance(unique_id, str) and unique_id.startswith("model."):
            built.add(unique_id.rsplit(".", 1)[-1])
    return built


def _build_result(project_dir: Path, parquet_dir: Path) -> tuple[str | None, set[str]]:
    path = project_dir / "target" / "run_results.json"
    if not path.exists():
        return None, set()
    raw: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return None, set()
    document = cast(dict[str, object], raw)
    metadata = document.get("metadata")
    generated = metadata.get("generated_at") if isinstance(metadata, dict) else None
    build_time = generated if isinstance(generated, str) else None
    args = document.get("args")
    if not isinstance(args, dict) or args.get("which") not in ("build", "run"):
        return build_time, set()
    variables = args.get("vars")
    if not isinstance(variables, dict):
        return build_time, set()
    root = variables.get("parquet_root")
    if not isinstance(root, str) or project_path(Path(root), project_dir).resolve() != parquet_dir:
        return build_time, set()
    return build_time, _successful_models(document.get("results"))


def _existing(connection: duckdb.DuckDBPyConnection) -> set[str]:
    rows = connection.execute(
        "SELECT table_schema || '.' || table_name FROM information_schema.tables"
    ).fetchall()
    return {str(row[0]) for row in rows}


def _show_table(
    connection: duckdb.DuckDBPyConnection | None,
    table: tuple[str, str, str, str, tuple[str, ...]],
    available: set[str],
    built: set[str] | None,
) -> None:
    heading, relation, columns, order, dependencies = table
    print(f"\n{heading} — {relation}")
    name = relation.rsplit(".", 1)[-1]
    if (
        connection is None
        or relation not in available
        or (
            built is not None
            and (name not in built or any(dep not in built for dep in dependencies))
        )
        or any(f"marts.{dep}" not in available for dep in dependencies)
    ):
        print("not built")
        return
    source = relation
    if dependencies:
        source = (
            "marts.fct_ride_day AS ride_day JOIN marts.dim_ride AS ride "
            "ON ride_day.ride_key = ride.ride_key"
        )
        columns = (
            "ride_day.park_id, ride_day.game_year, ride_day.game_month, ride_day.game_day, "
            "ride.ride_name, ride.classification, ride_day.customers_increase, ride_day.profit_usd"
        )
        order = (
            "ride_day.park_id, ride_day.game_year, ride_day.game_month, "
            "ride_day.game_day, ride_day.ride_key"
        )
    count_row = connection.execute(f"SELECT count(*) FROM {source}").fetchone()
    if count_row is None:
        raise ValueError(f"count query returned no row for {relation}")
    total = int(count_row[0])
    rows = connection.execute(
        f"SELECT {columns} FROM {source} ORDER BY {order} LIMIT {ROW_CAP}"
    ).fetchall()
    print(f"{total} rows")
    names = (part.strip().split(".")[-1] for part in columns.split(","))
    print(" | ".join(HEADING_UNITS.get(name, name) for name in names))
    for row in rows:
        print(" | ".join("null" if value is None else str(value) for value in row))
    if total > ROW_CAP:
        print(f"{total - ROW_CAP} more rows; query {relation} for all")


def _parquet_sessions(path: Path) -> set[str]:
    if not path.exists():
        return set()
    connection = duckdb.connect(":memory:")
    try:
        rows = connection.execute(
            "SELECT DISTINCT session_id FROM read_parquet(?)", [str(path)]
        ).fetchall()
        return {str(row[0]) for row in rows}
    finally:
        connection.close()


def _show_cost(path: Path) -> None:
    print("\nPlugin tick cost — plugin_stats.parquet")
    if not path.exists():
        print("no judged plugin_stats rows")
        return
    connection = duckdb.connect(":memory:")
    try:
        rows = connection.execute(
            "SELECT session_id, period_ticks, work_ms_total, worst_tick_ms, worst_tick_at_ticks "
            f"FROM read_parquet(?) WHERE {JUDGED_COST_FILTER} ORDER BY session_id, seq",
            [str(path)],
        ).fetchall()
    finally:
        connection.close()
    sessions: dict[str, list[CostRow]] = {}
    for sid, ticks, work, worst, at_tick in rows:
        session_id = str(sid)
        sessions.setdefault(session_id, []).append(
            CostRow(session_id, int(ticks), float(work), float(worst), int(at_tick))
        )
    if not sessions:
        print("no judged plugin_stats rows")
    for session_id, session_rows in sessions.items():
        cost = judge_cost(session_rows)
        if cost is None:
            print(f"{session_id}: no judged plugin_stats rows")
            continue
        worst_result = "pass" if cost.worst_within_limit else "fail"
        mean_result = "pass" if cost.mean_within_limit else "fail"
        print(
            f"{session_id}: {len(session_rows)} judged periods, {cost.judged_ticks} ticks; "
            f"worst {cost.worst_tick_ms:.3f} ms / {WORST_TICK_LIMIT_MS:.1f} ms {worst_result}; "
            f"mean {cost.mean_tick_ms:.4f} ms / {MEAN_TICK_LIMIT_MS:.2f} ms {mean_result}"
        )


def _show_sessions(
    connection: duckdb.DuckDBPyConnection | None,
    available: set[str],
    built: set[str] | None,
    audit_path: Path,
) -> None:
    if (
        connection is None
        or "staging.stg_session_start" not in available
        or (built is not None and "stg_session_start" not in built)
        or not audit_path.exists()
    ):
        return
    warehouse = {
        str(row[0])
        for row in connection.execute(
            "SELECT DISTINCT session_id FROM staging.stg_session_start"
        ).fetchall()
    }
    audit = _parquet_sessions(audit_path)
    for session_id in sorted(warehouse - audit):
        print(f"WARNING: warehouse session {session_id} absent from seq audit")
    for session_id in sorted(audit - warehouse):
        print(f"WARNING: seq audit session {session_id} absent from warehouse")


def _run(data_set: str, *, published: bool, project_dir: Path) -> int:
    parquet_dir = project_path(landing_dirs(data_set).parquet, project_dir).resolve()
    warehouse = (
        project_dir / "warehouse" / (f"{data_set}.duckdb" if published else "dev/dev.duckdb")
    )
    if published and not warehouse.is_file():
        raise _Refused(
            "published-missing", f"{warehouse} missing; run make publish DATA_SET={data_set}"
        )
    print(f"Warehouse: {warehouse}")
    print(
        f"Warehouse modified: {datetime.fromtimestamp(warehouse.stat().st_mtime).isoformat()}"
        if warehouse.is_file()
        else "Warehouse modified: unavailable"
    )
    build_time, built = (None, None) if published else _build_result(project_dir, parquet_dir)
    if not published:
        print(f"Build time: {build_time or 'unavailable'}")
    audit_path = parquet_dir / AUDIT_FILE
    if (
        warehouse.is_file()
        and not published
        and audit_path.exists()
        and warehouse.stat().st_mtime < audit_path.stat().st_mtime
    ):
        print("WARNING: dev warehouse is older than seq_audit.parquet; build may be stale")
    if not warehouse.is_file():
        print(f"Warehouse not built; run make transform DATA_SET={data_set}")
    connection = (
        open_warehouse(warehouse, project_dir=project_dir, read_only=True)
        if warehouse.is_file()
        else None
    )
    try:
        available = _existing(connection) if connection is not None else set()
        _show_sessions(connection, available, built, audit_path)
        for table in TABLES:
            _show_table(connection, table, available, built)
    finally:
        if connection is not None:
            connection.close()
    _show_cost(parquet_dir / "v1" / "plugin_stats.parquet")
    return 0


def main(argv: Sequence[str] | None = None, *, project_dir: Path = PROJECT_DIR) -> int:
    """Print warehouse tables and plugin cost for one data set."""
    parser = _ResultsParser(description=__doc__)
    parser.add_argument("--data-set", choices=DATA_SETS, required=True)
    parser.add_argument("--published", action="store_true")
    handlers = {
        name: signal.getsignal(getattr(signal, name))
        for name in lock.SIGNAL_NAMES
        if hasattr(signal, name)
    }
    lock.set_signal_handlers(lock.raise_interrupted)
    try:
        args = parser.parse_args(argv)
        code = _run(args.data_set, published=args.published, project_dir=project_dir)
    except _Refused as error:
        print(f"results refused: {error.reason}: {error.detail}")
        code = 2
    except ConfigError as error:
        print(f"results refused: config: {error}")
        code = 2
    except (OSError, ValueError, duckdb.Error) as error:
        print(f"results failed: io: {error}")
        code = 1
    except (lock.Interrupted, KeyboardInterrupt):
        print("results interrupted")
        code = 130
    finally:
        for name, handler in handlers.items():
            signal.signal(getattr(signal, name), handler)
    return code


if __name__ == "__main__":
    sys.exit(main())
