"""The sample record of the site export: a real temporary DuckDB file, no mocks."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import duckdb
import pytest

from openrct2_analytics.showcase.export import load_allowlist, main
from openrct2_analytics.showcase.export import run as export_run

SAMPLE_RELATION = "marts.obt_park_year, marts.fct_park_day, staging.stg_session_start"
ALLOWLIST_TEXT = (
    '[[export]]\nname = "park"\nrelation = "marts.dim_park"\noutput = "park.json"\n'
    'columns = ["park_id", "park_number"]\norder_by = ["park_number", "park_id"]\n'
)


@pytest.fixture
def warehouse(tmp_path: Path) -> Path:
    (tmp_path / "exports.toml").write_text(ALLOWLIST_TEXT)
    path = tmp_path / "wh.duckdb"
    connection = duckdb.connect(str(path))
    connection.execute("create schema marts")
    connection.execute("create schema staging")
    connection.execute(
        "create table marts.obt_park_year as select * from "
        "(values ('p1'), ('p1'), ('p2')) t(park_id)"
    )
    connection.execute(
        "create table marts.dim_park as select * from (values ('p1', 1, 'company')) "
        "t(park_id, park_number, data_set)"
    )
    connection.execute(
        "create table marts.fct_park_day as select * from (values "
        "('s1', date '2026-03-01'), ('s1', date '2026-03-02'), ('s2', date '2026-03-01'), "
        "('s3', date '2026-03-01')) t(session_id, company_date)"
    )
    connection.execute(
        "create table staging.stg_session_start as select * from (values "
        "('s1', true), ('s2', true), ('s3', true), ('s9', false)) t(session_id, headless)"
    )
    connection.close()
    return path


def _allowlist(warehouse: Path) -> Path:
    return warehouse.parent / "exports.toml"


def run(mode: str, warehouse: Path, served: Path, *extra: str) -> int:
    return main(
        [mode, "--warehouse", str(warehouse), "--served-dir", str(served)]
        + ["--allowlist", str(_allowlist(warehouse)), *extra]
    )


def _sample_document(served: Path) -> dict[str, Any]:
    return json.loads((served / "sample.json").read_text())  # type: ignore[no-any-return]


def _sql(warehouse: Path, *statements: str) -> None:
    connection = duckdb.connect(str(warehouse))
    for statement in statements:
        connection.execute(statement)
    connection.close()


def test_sample_record_counts_parks_sessions_and_players(warehouse: Path, tmp_path: Path) -> None:
    served = tmp_path / "served"
    assert run("write", warehouse, served) == 0
    document = _sample_document(served)
    assert document["name"] == "sample"
    assert document["columns"] == ["data_set", "parks", "sessions", "player_played"]
    assert document["rows"] == [
        {"data_set": "sample", "parks": 2, "sessions": 3, "player_played": False}
    ]


def test_sample_record_header_names_the_three_source_tables(
    warehouse: Path, tmp_path: Path
) -> None:
    served = tmp_path / "served"
    run("write", warehouse, served)
    assert _sample_document(served)["relation"] == SAMPLE_RELATION


def test_a_session_with_a_player_sets_player_played(warehouse: Path, tmp_path: Path) -> None:
    _sql(warehouse, "update staging.stg_session_start set headless = false where session_id = 's2'")
    served = tmp_path / "served"
    run("write", warehouse, served)
    assert _sample_document(served)["rows"][0]["player_played"] is True


@pytest.mark.parametrize("table", ["staging.stg_session_start", "marts.fct_park_day"])
def test_a_missing_source_table_is_refused_and_named(
    warehouse: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str], table: str
) -> None:
    _sql(warehouse, f"drop table {table}")
    served = tmp_path / "served"
    assert run("write", warehouse, served) == 2
    out = capsys.readouterr().out
    assert out.startswith("export refused: ")
    assert table in out


def test_relation_run_writes_no_sample_record(warehouse: Path, tmp_path: Path) -> None:
    served = tmp_path / "served"
    assert run("write", warehouse, served, "--relation", "marts.dim_park") == 0
    assert not (served / "sample.json").exists()


def test_relation_check_does_not_need_a_sample_record(warehouse: Path, tmp_path: Path) -> None:
    served = tmp_path / "served"
    run("write", warehouse, served)
    (served / "sample.json").unlink()
    assert run("check", warehouse, served, "--relation", "marts.dim_park") == 0


def test_zero_rows_give_a_zero_record(warehouse: Path, tmp_path: Path) -> None:
    _sql(
        warehouse,
        "delete from marts.obt_park_year",
        "delete from marts.fct_park_day",
        "delete from staging.stg_session_start",
    )
    served = tmp_path / "served"
    assert run("write", warehouse, served) == 0
    assert _sample_document(served)["rows"] == [
        {"data_set": "sample", "parks": 0, "sessions": 0, "player_played": False}
    ]


def test_check_flags_a_changed_sample_record(
    warehouse: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    served = tmp_path / "served"
    run("write", warehouse, served)
    file = served / "sample.json"
    file.write_text(file.read_text().replace('"sessions": 3', '"sessions": 4'))
    assert run("check", warehouse, served) == 1
    out = capsys.readouterr().out
    assert "sample: row data_set=sample column sessions differs" in out


def test_check_flags_a_missing_sample_record(
    warehouse: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    served = tmp_path / "served"
    run("write", warehouse, served)
    (served / "sample.json").unlink()
    assert run("check", warehouse, served) == 1
    assert "sample: served file" in capsys.readouterr().out


def test_company_label_passes_when_every_park_is_company(warehouse: Path, tmp_path: Path) -> None:
    served = tmp_path / "served"
    entries = load_allowlist(_allowlist(warehouse))
    export_run("write", warehouse, entries, served, data_set="company")
    assert _sample_document(served)["rows"][0]["data_set"] == "company"
    export_run("check", warehouse, entries, served, data_set="company")


def test_company_label_is_refused_when_one_park_is_not_company(
    warehouse: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _sql(warehouse, "insert into marts.dim_park values ('p2', 2, 'rehearsal')")
    served = tmp_path / "served"
    assert run("write", warehouse, served, "--data-set", "company") == 2
    out = capsys.readouterr().out
    assert out.startswith("export refused: ")
    assert "data_set company" in out
    assert not served.exists()


def test_company_label_on_an_empty_dim_park_is_refused(warehouse: Path, tmp_path: Path) -> None:
    _sql(warehouse, "delete from marts.dim_park")
    assert run("write", warehouse, tmp_path / "served", "--data-set", "company") == 2


def test_default_label_reads_no_dim_park(warehouse: Path, tmp_path: Path) -> None:
    _sql(warehouse, "drop table marts.dim_park")
    served = tmp_path / "served"
    export_run("write", warehouse, [], served)
    assert _sample_document(served)["rows"][0]["data_set"] == "sample"


def test_company_label_without_dim_park_is_refused_and_names_the_table(
    warehouse: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _sql(warehouse, "drop table marts.dim_park")
    _allowlist(warehouse).write_text(
        '[[export]]\nname = "years"\nrelation = "marts.obt_park_year"\noutput = "years.json"\n'
        'columns = ["park_id"]\norder_by = ["park_id"]\n'
    )
    served = tmp_path / "served"
    assert run("write", warehouse, served, "--data-set", "company") == 2
    out = capsys.readouterr().out
    assert out.startswith(
        "export refused: marts.dim_park or its data_set column is missing, "
        "so data_set company cannot be checked: "
    )
    assert not served.exists()
