"""Behavioral tests for scripts/check_model_columns.py, on a real temporary DuckDB file.

The manifest is a small JSON document shaped like dbt's manifest.json (only the keys the script
reads).
Rules (a) to (d) each have a planted violation and a passing form.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import duckdb
import pytest

from check_model_columns import main


def node(
    name: str,
    columns: list[str],
    *,
    path: str = "models/staging/stg_x.sql",
    materialized: str = "table",
    resource_type: str = "model",
) -> dict[str, Any]:
    return {
        "unique_id": f"{resource_type}.p.{name}",
        "resource_type": resource_type,
        "name": name,
        "alias": name,
        "schema": "main",
        "database": "ci",
        "original_file_path": path,
        "config": {"materialized": materialized},
        "columns": {c: {"name": c} for c in columns},
    }


def run(tmp_path: Path, built: dict[str, str], nodes: list[dict[str, Any]]) -> int:
    """Build the relations (name -> column list sql), write the manifest, and run main()."""
    db = tmp_path / "ci.duckdb"
    con = duckdb.connect(str(db))
    for name, select in built.items():
        con.execute(f"create table {name} as select {select}")
    con.close()
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"nodes": {n["unique_id"]: n for n in nodes}}), encoding="utf-8")
    return main([str(manifest), str(db)])


def test_matching_columns_pass(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = run(
        tmp_path, {"stg_x": "1 as ID, 2 as value_tenths"}, [node("stg_x", ["id", "value_tenths"])]
    )
    assert code == 0
    assert "matches" in capsys.readouterr().out


def test_built_column_without_yaml_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = run(tmp_path, {"stg_x": "1 as id, 1 as undocumented_column"}, [node("stg_x", ["id"])])
    assert code == 1
    assert "stg_x: built column undocumented_column has no YAML entry" in capsys.readouterr().err


def test_yaml_column_not_built_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = run(tmp_path, {"stg_x": "1 as id"}, [node("stg_x", ["id", "ghost"])])
    assert code == 1
    assert "stg_x: YAML column ghost is not built" in capsys.readouterr().err


def test_tenths_outside_staging_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    mart = node("int_plant", ["value_tenths"], path="models/intermediate/int_plant.sql")
    code = run(tmp_path, {"int_plant": "1 as value_tenths"}, [mart])
    assert code == 1
    assert "int_plant: built column value_tenths ends _tenths outside models/staging/" in (
        capsys.readouterr().err
    )


def test_missing_relation_fails_closed(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = run(tmp_path, {"stg_x": "1 as id"}, [node("stg_x", ["id"]), node("stg_gone", ["id"])])
    assert code == 1
    assert "stg_gone: no built relation main.stg_gone" in capsys.readouterr().err


def test_ephemeral_skipped_and_non_models_ignored(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    nodes = [
        node("stg_x", ["id"]),
        node("eph", ["id"], materialized="ephemeral"),
        node("a_test", [], resource_type="test"),
    ]
    code = run(tmp_path, {"stg_x": "1 as id"}, nodes)
    assert code == 0
    assert "skipped ephemeral model eph" in capsys.readouterr().out
