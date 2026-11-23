"""Behavioral checks for the contract-driven zero-row extract."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import duckdb

from openrct2_analytics.ingest.contracts import CONTRACTS_DIR, Field, load_fields
from openrct2_analytics.ingest.convert import convert
from openrct2_analytics.ingest.empty_extract import main


def _schema(path: Path) -> list[tuple[str, str]]:
    with duckdb.connect(":memory:") as connection:
        return [
            (str(name), str(physical_type))
            for name, physical_type, *_ in connection.execute(
                "DESCRIBE SELECT * FROM read_parquet(?)", [path.as_posix()]
            ).fetchall()
        ]


def _row_count(path: Path) -> int:
    with duckdb.connect(":memory:") as connection:
        row = connection.execute(
            "SELECT count(*) FROM read_parquet(?)", [path.as_posix()]
        ).fetchone()
    assert row is not None
    return int(row[0])


def _fixture_value(logical: str) -> object:
    if logical == "string":
        return "fixture"
    if logical == "timestamp":
        return "2026-10-09T12:00:00Z"
    if logical == "boolean":
        return True
    if logical == "number":
        return 1.5
    return 1


def _one_line_fixture(event_type: str, fields: Sequence[Field]) -> str:
    values = {
        field.name: _fixture_value(field.logical)
        for field in fields
        if field.name not in {"_raw_file", "_raw_line"}
    }
    values.update(
        schema_version=1,
        event_type=event_type,
        plugin_version="fixture",
        park_id="park-fixture",
        session_id="session-fixture",
        seq=1,
        event_id=f"fixture-{event_type}",
        game_year=1,
        game_month=0,
        game_day=1,
        game_ticks_elapsed=1,
        emitted_at="2026-10-09T12:00:00Z",
        received_at="2026-10-09T12:00:01Z",
    )
    return json.dumps(values)


def test_writes_zero_row_files_only_under_the_requested_output(tmp_path: Path) -> None:
    fields = load_fields(CONTRACTS_DIR)
    out_dir = tmp_path / "out"

    assert main(["--out-dir", str(out_dir)]) == 0

    expected_names = {f"{event_type}.parquet" for event_type in fields}
    assert {path.name for path in (out_dir / "v1").iterdir()} == expected_names
    sample_v1 = Path(__file__).resolve().parents[1] / "data" / "sample" / "rehearsal" / "v1"
    assert {path.name for path in (out_dir / "v1").iterdir()} == {
        path.name for path in sample_v1.glob("*.parquet")
    }
    assert {path.name for path in out_dir.iterdir()} == {"v1"}
    assert set(tmp_path.iterdir()) == {out_dir}
    for event_type in fields:
        path = out_dir / "v1" / f"{event_type}.parquet"
        assert _row_count(path) == 0


def test_empty_file_schema_matches_converter_for_every_contract_type(tmp_path: Path) -> None:
    fields = load_fields(CONTRACTS_DIR)
    empty_dir = tmp_path / "empty"
    assert main(["--out-dir", str(empty_dir)]) == 0

    for event_type, event_fields in fields.items():
        raw_dir = tmp_path / "raw" / event_type
        raw_v1 = raw_dir / "v1"
        raw_v1.mkdir(parents=True)
        (raw_v1 / "events-fixture.jsonl").write_text(
            _one_line_fixture(event_type, event_fields) + "\n", encoding="utf-8"
        )
        converted_dir = tmp_path / "converted" / event_type

        result = convert(raw_dir, converted_dir)

        assert result.ok, result.schema_errors
        empty_file = empty_dir / "v1" / f"{event_type}.parquet"
        converted_file = converted_dir / "v1" / f"{event_type}.parquet"
        assert _row_count(converted_file) == 1
        assert _schema(empty_file) == _schema(converted_file)
