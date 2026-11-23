"""Real Parquet, DuckDB and record-file coverage for the play-status command."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pytest

from openrct2_analytics.ingest import play_status, registry_feed

# WEAKENED-OK: test_landing_puts_a_relative_data_folder_under_the_project moved,
# with its two assertions, to tests/test_landing_paths.py (spec R2: the shared module's own tests;
# R9: the list of test files the work may edit).

HEADER = ",".join(registry_feed.HEADER)


def _copy(path: Path, query: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(":memory:") as connection:
        connection.execute(f"COPY ({query}) TO '{path.as_posix()}' (FORMAT PARQUET)")


def _warehouse(project: Path, sessions: list[str]) -> Path:
    path = project / "warehouse" / "dev" / "dev.duckdb"
    path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(path)) as connection:
        connection.execute("CREATE SCHEMA staging")
        connection.execute("CREATE TABLE staging.stg_session_start (session_id VARCHAR)")
        for session_id in sessions:
            connection.execute("INSERT INTO staging.stg_session_start VALUES (?)", [session_id])
    return path


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    data = tmp_path / "data" / "company"
    _copy(
        data / "parquet" / "v1" / "session_start.parquet",
        "SELECT 's1' AS session_id, 'park-a' AS park_id, 'Alpha Park' AS park_name, "
        "TIMESTAMPTZ '2026-10-01 10:00:00+00' AS emitted_at "
        "UNION ALL SELECT 's2', 'park-b', 'Beta Park', TIMESTAMPTZ '2026-10-02 10:00:00+00'",
    )
    _copy(
        data / "parquet" / "v1" / "save_written.parquet",
        "SELECT 'e1' AS event_id, 'save-1' AS save_id, 'park-b' AS park_id, "
        "'s2' AS session_id, TIMESTAMPTZ '2026-10-02 10:30:00+00' AS emitted_at, "
        "TIMESTAMPTZ '2026-10-02 10:30:00.100+00' AS received_at, "
        "'events.jsonl' AS _raw_file, 4 AS _raw_line",
    )
    records = data / "save_files" / "v1" / "save_file_observation_2026-10-02.jsonl"
    records.parent.mkdir(parents=True)
    record = {
        "run_started_at": "2026-10-02T09:59:00.000Z",
        "observation": "modified",
        "file_name": "beta-main.park",
        "folder_kind": "save",
        "modified_at": "2026-10-02T10:30:01.000Z",
        "size_bytes": 1024,
        "observed_at": "2026-10-02T10:30:02.000Z",
    }
    records.write_text(json.dumps(record) + "\n", encoding="utf-8")
    feed = data / "registry" / "v1"
    feed.mkdir(parents=True)
    (feed / "park_registry_2026-10-01_01.csv").write_text(
        f"{HEADER}\npark-a,2000,3,company,,2026-10-01\n", encoding="utf-8"
    )
    monkeypatch.setenv("OPENRCT2_DATA_DIR", str(tmp_path / "data"))
    return tmp_path


def _status(project: Path, capsys: pytest.CaptureFixture[str]) -> tuple[int, dict[str, object]]:
    code = play_status.main(["--data-set", "company"], project_dir=project)
    out = capsys.readouterr().out
    assert out.count("\n") == 1
    return code, json.loads(out)


def _tree(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        digest.update(str(path.relative_to(root)).encode())
        if path.is_file():
            digest.update(path.read_bytes())
    return digest.hexdigest()


ALPHA = {
    "session_id": "s1",
    "captured_at": "2026-10-01T10:00:00+00:00",
    "parks": [
        {"park_id": "park-a", "park_name": "Alpha Park", "registered": True, "last_save_file": None}
    ],
}
BETA = {
    "session_id": "s2",
    "captured_at": "2026-10-02T10:00:00+00:00",
    "parks": [
        {
            "park_id": "park-b",
            "park_name": "Beta Park",
            "registered": False,
            "last_save_file": "beta-main.park",
        }
    ],
}


def test_processed_session_is_left_out_and_nothing_is_written(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _warehouse(project, ["s1"])
    before = _tree(project)
    code, status = _status(project, capsys)
    assert code == 0
    assert status == {"data_set": "company", "warehouse": "ready", "sessions_waiting": [BETA]}
    assert _tree(project) == before


def test_missing_warehouse_lists_every_converted_session(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, status = _status(project, capsys)
    assert code == 0
    assert status == {
        "data_set": "company",
        "warehouse": "missing",
        "sessions_waiting": [ALPHA, BETA],
    }
    assert not (project / "warehouse").exists()


def test_warehouse_without_the_sessions_table_lists_every_session(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = project / "warehouse" / "dev" / "dev.duckdb"
    path.parent.mkdir(parents=True)
    duckdb.connect(str(path)).close()
    code, status = _status(project, capsys)
    assert code == 0
    assert status["warehouse"] == "ready"
    assert status["sessions_waiting"] == [ALPHA, BETA]


@contextmanager
def _writer_holds(path: Path) -> Iterator[None]:
    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import duckdb, sys; c = duckdb.connect(sys.argv[1]); print('held', flush=True); "
            "sys.stdin.read()",
            str(path),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    assert holder.stdin is not None and holder.stdout is not None
    try:
        assert holder.stdout.readline().strip() == "held"
        yield
    finally:
        holder.stdin.close()
        holder.wait(timeout=30)


def test_warehouse_locked_by_a_writer_reads_as_building(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _warehouse(project, ["s1"])
    with _writer_holds(path):
        code, status = _status(project, capsys)
    assert code == 0
    assert status["warehouse"] == "building"
    assert status["sessions_waiting"] == [ALPHA, BETA]


def test_damaged_warehouse_fails(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = project / "warehouse" / "dev" / "dev.duckdb"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"not a database" * 100)
    assert play_status.main(["--data-set", "company"], project_dir=project) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "play-status failed: io:" in captured.err


def test_unconverted_data_set_has_no_waiting_sessions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("OPENRCT2_DATA_DIR", str(tmp_path / "data"))
    code, status = _status(tmp_path, capsys)
    assert code == 0
    assert status == {"data_set": "company", "warehouse": "missing", "sessions_waiting": []}


@pytest.mark.parametrize("args", [[], ["--data-set", "other"]])
def test_bad_data_set_is_refused(
    project: Path, capsys: pytest.CaptureFixture[str], args: list[str]
) -> None:
    assert play_status.main(args, project_dir=project) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "play-status refused: usage:" in captured.err


def test_public_reader_calls_a_planted_warehouse_ready(project: Path) -> None:
    path = _warehouse(project, ["s1", "s3"])
    assert play_status.warehouse_sessions(path, project) == ("ready", {"s1", "s3"})


def test_public_reader_calls_a_written_warehouse_building(project: Path) -> None:
    path = _warehouse(project, ["s1", "s3"])
    with _writer_holds(path):
        assert play_status.warehouse_sessions(path, project) == ("building", None)


def test_public_reader_calls_an_absent_warehouse_missing(project: Path) -> None:
    path = project / "warehouse" / "dev" / "absent.duckdb"
    assert play_status.warehouse_sessions(path, project) == ("missing", None)


def test_converted_starts_returns_the_rows_read_status_uses(project: Path) -> None:
    starts = project / "data" / "company" / "parquet" / "v1" / "session_start.parquet"
    assert play_status.converted_starts(starts) == [
        ("s1", "park-a", "Alpha Park", datetime(2026, 10, 1, 10, 0, tzinfo=UTC)),
        ("s2", "park-b", "Beta Park", datetime(2026, 10, 2, 10, 0, tzinfo=UTC)),
    ]
