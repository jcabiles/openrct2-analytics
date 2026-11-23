"""Fail when a model's known cleaning filter has no row in the counts mart.

The script checks the SQL text patterns listed in the row of ``docs/CONVENTIONS.md`` section 4
that requires a counts row for each cleaning filter. Only the forms in that row are seen;
``not (...)``, a reversed comparison, ``delivery_rank <= 1`` and a nullif over an expression,
among others, are not. Patterns inside string literals count.
Guest exits with no arrival have no filter pattern, so their count is not enforced here. The
script does not check for stale count rows; it checks stale exemptions instead.

Usage: python scripts/check_cleaning_rule_counts.py MANIFEST DUCKDB_FILE
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import duckdb

from dbt_rules import strip_comments

ABANDONED_RULE = "abandoned_branch"
COUNTS_MODEL = "fct_cleaning_rule_count"
EXEMPTIONS = {
    ("dim_date", ABANDONED_RULE): (
        "its kept filter counts statements, while dim_date contains calendar dates; row 13 "
        "already counts that rule on the same input"
    ),
    ("dim_park", ABANDONED_RULE): (
        "it filters abandoned session starts before selecting registered parks, and no layer "
        "holds those starts for an honest count"
    ),
}
DELIVERY_FILTER = re.compile(r"\bdelivery_rank\s*=\s*1\b", re.IGNORECASE)
TIMELINE_FILTER = re.compile(
    r"(?:\btimeline_status\s*(?:=\s*['\"]kept['\"]|<>\s*['\"]abandoned['\"]|"
    r"!=\s*['\"]abandoned['\"])|\{\{-?\s*timeline_status\s*\([^}]*?\)\s*-?\}\}\s*"
    r"(?:=\s*['\"]kept['\"]|<>\s*['\"]abandoned['\"]|!=\s*['\"]abandoned['\"]))",
    re.IGNORECASE,
)
NULLIF_FILTER = re.compile(
    r'\bnullif\s*\(\s*"?\w+"?(?:\s*\.\s*"?\w+"?)*\s*,\s*(-1|255|1275|65535)\s*\)',
    re.IGNORECASE,
)
COUNTER_CHANGE_FILTER = re.compile(r"\bcounter_change\s*\(", re.IGNORECASE)
PLACEHOLDER_RULES = {
    "-1": "placeholder_null_minus_1",
    "255": "placeholder_null_255",
    "1275": "placeholder_null_1275",
    "65535": "placeholder_null_65535",
}


def detected_pairs(manifest: dict[str, Any]) -> tuple[set[tuple[str, str]], set[str]]:
    """Return each recognized rule/model pair and the model names present in the manifest."""
    pairs: set[tuple[str, str]] = set()
    model_names: set[str] = set()
    for node in manifest["nodes"].values():
        if node["resource_type"] != "model":
            continue
        name = str(node["name"])
        model_names.add(name)
        sql = strip_comments(str(node["raw_code"]))
        if DELIVERY_FILTER.search(sql):
            pairs.add((name, "repeat_delivery"))
        if TIMELINE_FILTER.search(sql):
            pairs.add((name, ABANDONED_RULE))
        pairs.update((name, PLACEHOLDER_RULES[value]) for value in NULLIF_FILTER.findall(sql))
        if COUNTER_CHANGE_FILTER.search(sql):
            pairs.add((name, "last_reading_null"))
    return pairs, model_names


def quoted(identifier: str) -> str:
    """Quote a DuckDB identifier, escaping embedded double quotes."""
    return '"' + identifier.replace('"', '""') + '"'


def counts_relation(manifest: dict[str, Any]) -> tuple[str, str]:
    """Find the counts mart's schema and alias in the manifest."""
    nodes = manifest["nodes"].values()
    for node in nodes:
        if node["resource_type"] == "model" and node["name"] == COUNTS_MODEL:
            return str(node["schema"]), str(node["alias"])
    raise ValueError(f"manifest has no {COUNTS_MODEL} model")


def find_problems(manifest: dict[str, Any], con: duckdb.DuckDBPyConnection) -> list[str]:
    """Return missing cleaning-count pairs and stale exemption problems."""
    pairs, model_names = detected_pairs(manifest)
    problems: list[str] = []
    for (name, rule), reason in EXEMPTIONS.items():
        if name not in model_names or (name, rule) not in pairs:
            problems.append(f"{name}: stale {rule} exemption: {reason}")
        pairs.discard((name, rule))

    schema, alias = counts_relation(manifest)
    relation = f"{quoted(schema)}.{quoted(alias)}"
    try:
        rows = con.execute(f"select rule_name, model_name from {relation}").fetchall()
    except duckdb.Error as error:
        raise ValueError(f"cannot read {COUNTS_MODEL} table {schema}.{alias}: {error}") from error
    present = {(str(model), str(rule)) for rule, model in rows}
    problems.extend(
        f"{name}: {rule}: filter found, no row in {COUNTS_MODEL}"
        for name, rule in sorted(pairs - present)
    )
    return sorted(problems)


def validate_nodes(manifest: object, path: Path) -> None:
    """Reject a manifest whose nodes are not a mapping of nodes that each have a resource type."""
    if not isinstance(manifest, dict) or "nodes" not in manifest:
        raise ValueError(f"manifest {path} has no 'nodes' key")
    if not isinstance(manifest["nodes"], dict):
        raise ValueError(f"manifest {path}: 'nodes' is not an object")
    for key, item in manifest["nodes"].items():
        if not isinstance(item, dict) or "resource_type" not in item:
            raise ValueError(f"manifest {path}: node {key} has no resource_type")


def main(argv: Sequence[str] | None = None) -> int:
    """Check SQL filters against the built counts mart and return a process exit code."""
    parser = argparse.ArgumentParser(
        description="Check known cleaning filters against their counts."
    )
    parser.add_argument("manifest", type=Path)
    parser.add_argument("database", type=Path)
    args = parser.parse_args(argv)
    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        validate_nodes(manifest, args.manifest)
        with duckdb.connect(str(args.database), read_only=True) as con:
            problems = find_problems(manifest, con)
    except (OSError, json.JSONDecodeError, duckdb.Error, KeyError, TypeError, ValueError) as error:
        print(f"check_cleaning_rule_counts: {error}", file=sys.stderr)
        return 1
    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        print(f"check_cleaning_rule_counts: {len(problems)} problem(s).", file=sys.stderr)
        return 1
    print("check_cleaning_rule_counts: every known cleaning filter has a counts row.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
