"""Results command against real DuckDB and Parquet files."""

from __future__ import annotations

import json
import os
import signal
from pathlib import Path

import duckdb
import pytest

from openrct2_analytics.ingest import results
from openrct2_analytics.ingest.results import main

MODE_READ_ONLY = 0o444


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("OPENRCT2_DATA_DIR", str(tmp_path / "data"))
    return tmp_path


def warehouse(project: Path, *, published: bool = False, days: int = 1) -> Path:
    path = project / "warehouse" / ("rehearsal.duckdb" if published else "dev/dev.duckdb")
    path.parent.mkdir(parents=True)
    connection = duckdb.connect(str(path))
    try:
        connection.execute("CREATE SCHEMA staging")
        connection.execute("CREATE SCHEMA marts")
        connection.execute(
            "CREATE TABLE staging.stg_session_start AS SELECT 'park-a' AS park_id, "
            "'warehouse-session' AS session_id, 'Park' AS park_name, 'Scenario' AS scenario_name, "
            "true AS headless, 1 AS game_year, 1 AS game_month, 1 AS game_day, "
            "TIMESTAMP '2026-10-19 00:00:00' AS emitted_at"
        )
        connection.execute(
            "CREATE TABLE marts.fct_park_day AS SELECT 'park-a' AS park_id, "
            "1 AS game_year, 1 AS game_month, n AS game_day, "
            "DATE '2026-10-19' AS company_date, 5 AS guests_in_park, "
            "2 AS admissions_increase, 500 AS park_rating, 12.5 AS cash_usd, "
            "true AS is_kept_operating_day FROM range(1, ?) AS day(n)",
            [days + 1],
        )
        connection.execute(
            "CREATE TABLE marts.fct_park_month AS SELECT 'park-a' AS park_id, "
            "1 AS statement_year, 1 AS statement_month, 2000 AS company_year, "
            "1.0 AS net_cash_change_usd, 2.0 AS operating_profit, "
            "3.0 AS cash_usd, 4.0 AS bank_loan_usd"
        )
        connection.execute(
            "CREATE TABLE marts.fct_ride_day AS SELECT 'park-a' AS park_id, "
            "1 AS game_year, 1 AS game_month, 1 AS game_day, 'ride-1' AS ride_key, "
            "7 AS customers_increase, 2.0 AS profit_usd"
        )
        connection.execute(
            "CREATE TABLE marts.dim_ride AS SELECT 'ride-1' AS ride_key, "
            "'Coaster' AS ride_name, 'ride' AS classification"
        )
    finally:
        connection.close()
    return path


def run_results(
    project: Path,
    *,
    which: str = "build",
    root: str | None = None,
    skipped: str | None = None,
    fields: bool = True,
) -> None:
    models = (
        "stg_session_start",
        "fct_park_day",
        "fct_park_month",
        "fct_ride_day",
        "dim_ride",
        "fct_cleaning_rule_count",
    )
    args: dict[str, object] = {}
    if fields:
        args = {
            "which": which,
            "vars": {"parquet_root": root or str(project / "data/rehearsal/parquet")},
        }
    document = {
        "metadata": {"generated_at": "2026-10-19T12:00:00Z"},
        "args": args,
        "results": [
            {
                "unique_id": f"model.analytics.{model}",
                "status": "skipped" if model == skipped else "success",
            }
            for model in models
        ],
    }
    target = project / "target"
    target.mkdir()
    (target / "run_results.json").write_text(json.dumps(document), encoding="utf-8")


def parquet(project: Path, *, judged: bool = True, audit: bool = True) -> None:
    root = project / "data/rehearsal/parquet"
    (root / "v1").mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(":memory:")
    try:
        if audit:
            (root / "audit").mkdir()
            connection.execute("CREATE TABLE audit AS SELECT 'audit-session' AS session_id")
            connection.execute(
                "COPY audit TO ? (FORMAT PARQUET)", [str(root / "audit/seq_audit.parquet")]
            )
        connection.execute(
            "CREATE TABLE stats AS SELECT 'cost-session' AS session_id, 1 AS seq, "
            "100 AS period_ticks, 50.0 AS work_ms_total, 10.5 AS worst_tick_ms, "
            "77 AS worst_tick_at_ticks, ? AS warmup, 'performance' AS clock, "
            "1 AS game_speed",
            [not judged],
        )
        connection.execute(
            "COPY stats TO ? (FORMAT PARQUET)", [str(root / "v1/plugin_stats.parquet")]
        )
    finally:
        connection.close()


def test_dev_tables_skipped_model_and_warehouse_only_session(
    project: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = warehouse(project)
    path.chmod(MODE_READ_ONLY)  # a write-mode open of the dev file would fail
    run_results(project, skipped="fct_park_month")
    parquet(project)
    assert main(["--data-set", "rehearsal"], project_dir=project) == 0
    out = capsys.readouterr().out
    for heading in ("Sessions", "Park days", "Months", "Rides and stalls", "Cleaning rule counts"):
        assert heading in out
    assert "Months (company month) — marts.fct_park_month\nnot built" in out
    assert "Cleaning rule counts — marts.fct_cleaning_rule_count\nnot built" in out
    assert "warehouse session warehouse-session absent from seq audit" in out
    assert "Build time: 2026-10-19T12:00:00Z" in out
    assert "admissions_increase | park_rating (rating points) | cash_usd" in out


def test_row_cap(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    warehouse(project, days=41)
    run_results(project)
    assert main(["--data-set", "rehearsal"], project_dir=project) == 0
    out = capsys.readouterr().out
    assert "1 more rows; query marts.fct_park_day for all" in out
    section = out.split("Park days (game date and company date)")[1].split("Months (")[0]
    assert section.count("park-a | 1 | 1 |") == 40


def test_published_read_only_ignores_run_results(
    project: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = warehouse(project, published=True)
    path.chmod(MODE_READ_ONLY)
    assert main(["--data-set", "rehearsal", "--published"], project_dir=project) == 0
    out = capsys.readouterr().out
    assert "Park days (game date and company date) — marts.fct_park_day\n1 rows" in out
    assert "Warehouse modified:" in out
    assert "net_cash_change_usd | operating_profit (US dollars) | cash_usd" in out


def test_cost_failure_and_no_judged_rows(
    project: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    parquet(project)
    assert main(["--data-set", "rehearsal"], project_dir=project) == 0
    assert "10.500 ms / 10.0 ms fail" in capsys.readouterr().out
    path = project / "data/rehearsal/parquet/v1/plugin_stats.parquet"
    path.unlink()
    parquet(project, judged=False, audit=False)
    assert main(["--data-set", "rehearsal"], project_dir=project) == 0
    assert "no judged plugin_stats rows" in capsys.readouterr().out


def test_refusals(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main([], project_dir=project) == 2
    assert capsys.readouterr().out.startswith("results refused: usage: ")
    assert main(["--data-set", "rehearsal", "--published"], project_dir=project) == 2
    out = capsys.readouterr().out
    assert out.startswith("results refused: published-missing: ")
    assert "missing; run make publish DATA_SET=rehearsal" in out


def test_bad_config_is_refused(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("OPENRCT2_DATA_DIR", "")
    assert main(["--data-set", "rehearsal"], project_dir=project) == 2
    assert capsys.readouterr().out.startswith("results refused: config: ")


def test_unreadable_warehouse_fails_with_io_reason(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = project / "warehouse/dev/dev.duckdb"
    path.parent.mkdir(parents=True)
    path.write_text("not a database", encoding="utf-8")
    assert main(["--data-set", "rehearsal"], project_dir=project) == 1
    assert "\nresults failed: io: " in capsys.readouterr().out


def test_sigterm_prints_interrupted_and_exits_130(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    parquet(project)

    def signal_at_cost(path: Path) -> None:
        os.kill(os.getpid(), signal.SIGTERM)

    monkeypatch.setattr(results, "_show_cost", signal_at_cost)
    before = signal.getsignal(signal.SIGTERM)
    assert main(["--data-set", "rehearsal"], project_dir=project) == 130
    assert capsys.readouterr().out.endswith("results interrupted\n")
    assert signal.getsignal(signal.SIGTERM) is before


def test_missing_dev_warehouse(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    parquet(project)
    assert main(["--data-set", "rehearsal"], project_dir=project) == 0
    out = capsys.readouterr().out
    assert out.count("not built") == 6
    assert "make transform DATA_SET=rehearsal" in out
    assert "10.500 ms / 10.0 ms fail" in out


@pytest.mark.parametrize(
    "case",
    [
        ("compile", None, True),
        ("build", "data/company/parquet", True),
        ("build", None, False),
    ],
)
def test_other_run_results_not_built(
    project: Path,
    capsys: pytest.CaptureFixture[str],
    case: tuple[str, str | None, bool],
) -> None:
    warehouse(project)
    which, root, fields = case
    run_results(project, which=which, root=root, fields=fields)
    assert main(["--data-set", "rehearsal"], project_dir=project) == 0
    assert capsys.readouterr().out.count("not built") == 5


def test_missing_run_results_not_built(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    warehouse(project)
    assert main(["--data-set", "rehearsal"], project_dir=project) == 0
    assert capsys.readouterr().out.count("not built") == 5


def test_audit_only_session_stale_dev_and_mtime(
    project: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = warehouse(project)
    run_results(project)
    parquet(project)
    old = path.stat().st_mtime - 100
    os.utime(path, (old, old))
    assert main(["--data-set", "rehearsal"], project_dir=project) == 0
    out = capsys.readouterr().out
    assert "seq audit session audit-session absent from warehouse" in out
    assert "older than seq_audit.parquet" in out
    assert "Warehouse modified:" in out
