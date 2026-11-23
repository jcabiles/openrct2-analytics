"""Fail when a built dbt model's real columns differ from its YAML, or leak a `_tenths` column.

It reads the manifest of a finished dbt build and, for every model node, the built relation's
columns from the DuckDB file through `information_schema.columns`. Names compare case-insensitively.
Each problem is reported as `<model>: <what is wrong>`:
(a) a built column has no YAML entry, (b) a YAML column is not built, (c) a model outside
`models/staging/` has a built column ending `_tenths`, (d) the model has no built relation.
Ephemeral models have no relation and are skipped and reported. Tests, seeds and sources are out
of scope.

Usage: python scripts/check_model_columns.py MANIFEST DUCKDB_FILE
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import duckdb

STAGING_PREFIX = "models/staging/"
TENTHS_SUFFIX = "_tenths"


def built_columns(con: duckdb.DuckDBPyConnection, schema: str, name: str) -> list[str]:
    """Return the column names of one built relation, empty when the relation does not exist."""
    rows = con.execute(
        "select column_name from information_schema.columns "
        "where lower(table_schema) = lower(?) and lower(table_name) = lower(?)",
        [schema, name],
    ).fetchall()
    return [str(row[0]) for row in rows]


def find_problems(manifest: dict[str, Any], con: duckdb.DuckDBPyConnection) -> list[str]:
    """Return one line per model whose built columns break a rule; skipped models print a note."""
    problems: list[str] = []
    for node in sorted(manifest["nodes"].values(), key=lambda n: n["unique_id"]):
        if node["resource_type"] != "model":
            continue
        name = node["name"]
        if node["config"]["materialized"] == "ephemeral":
            print(f"check_model_columns: skipped ephemeral model {name}.")
            continue
        built = built_columns(con, node["schema"], node["alias"])
        if not built:
            problems.append(f"{name}: no built relation {node['schema']}.{node['alias']}")
            continue
        built_by_key = {column.lower(): column for column in built}
        yaml_by_key = {column.lower(): column for column in node["columns"]}
        problems += [
            f"{name}: built column {built_by_key[key]} has no YAML entry"
            for key in built_by_key.keys() - yaml_by_key.keys()
        ]
        problems += [
            f"{name}: YAML column {yaml_by_key[key]} is not built"
            for key in yaml_by_key.keys() - built_by_key.keys()
        ]
        if not node["original_file_path"].replace("\\", "/").startswith(STAGING_PREFIX):
            problems += [
                f"{name}: built column {column} ends {TENTHS_SUFFIX} outside {STAGING_PREFIX}"
                for column in built
                if column.lower().endswith(TENTHS_SUFFIX)
            ]
    return sorted(problems)


def main(argv: Sequence[str] | None = None) -> int:
    """Check the built models and return a process exit code."""
    parser = argparse.ArgumentParser(description="Compare built model columns with their YAML.")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("database", type=Path)
    args = parser.parse_args(argv)
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    con = duckdb.connect(str(args.database), read_only=True)
    try:
        problems = find_problems(manifest, con)
    finally:
        con.close()
    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        print(f"check_model_columns: {len(problems)} problem(s).", file=sys.stderr)
        return 1
    print("check_model_columns: every built model matches its YAML columns.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
