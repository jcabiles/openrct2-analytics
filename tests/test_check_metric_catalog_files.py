"""Planted faults across several catalog files, on real temporary catalogs.

Each case writes the small clean catalog of tests/test_check_metric_catalog.py to
`metrics/catalog.yml`, adds files beside it, and expects each problem to name the right file.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

from check_file_sizes import MAX_LINES
from check_metric_catalog import find_problems
from tests.test_check_metric_catalog import (
    EXPECTED,
    Doc,
    base_catalog,
    get,
    write_root,
)

FIRST = "metrics/catalog.yml"
SECOND = "metrics/extra.yml"


def write_second(root: Path, text: str, name: str = "extra.yml") -> None:
    (root / "metrics" / name).write_text(text, encoding="utf-8")


def second_with(metrics: list[Doc]) -> str:
    return json.dumps({"semantic_models": [], "metrics": metrics})


def problems_in(root: Path) -> list[str]:
    problems: list[str] = find_problems(root, EXPECTED)
    return problems


def test_a_catalog_split_across_two_files_passes(tmp_path: Path) -> None:
    doc = base_catalog()
    moved = [m for m in doc["metrics"] if m["name"] == "sales"]
    doc["metrics"] = [m for m in doc["metrics"] if m["name"] != "sales"]
    write_second(write_root(tmp_path, json.dumps(doc)), second_with(moved))

    assert problems_in(tmp_path) == []


def test_a_metric_defined_in_two_files_is_rule_2c_naming_both_files(tmp_path: Path) -> None:
    root = write_root(tmp_path, json.dumps(base_catalog()))
    write_second(root, second_with([copy.deepcopy(get(base_catalog(), "sales"))]))

    lines = [line for line in problems_in(tmp_path) if "rule 2c" in line]

    assert len(lines) == 1
    assert FIRST in lines[0]
    assert SECOND in lines[0]


def test_a_second_north_star_in_another_file_is_rule_8a_on_the_merged_catalog(
    tmp_path: Path,
) -> None:
    root = write_root(tmp_path, json.dumps(base_catalog()))
    star = copy.deepcopy(get(base_catalog(), "north"))
    star["name"] = "north_two"
    write_second(root, second_with([star]))

    lines = [line for line in problems_in(tmp_path) if "rule 8a" in line]

    assert lines == ["metrics/: rule 8a: 2 metrics have role north_star, not exactly one"]


def test_a_missing_tree_parent_is_named_in_the_file_of_the_child(tmp_path: Path) -> None:
    root = write_root(tmp_path, json.dumps(base_catalog()))
    child = copy.deepcopy(get(base_catalog(), "sales"))
    child["name"] = "orphan"
    child["config"]["meta"]["tree"]["parent"] = "ghost"
    write_second(root, second_with([child]))

    lines = [line for line in problems_in(tmp_path) if "rule 8d" in line]

    assert len(lines) == 1
    assert lines[0].startswith(f"{SECOND}: rule 8d: metric 'orphan'")


def test_a_stray_file_without_the_top_keys_is_rule_1e(tmp_path: Path) -> None:
    write_second(write_root(tmp_path, json.dumps(base_catalog())), "notes: hello\n", "notes.yml")

    lines = [line for line in problems_in(tmp_path) if "rule 1e" in line]

    assert len(lines) == 1
    assert lines[0].startswith("metrics/notes.yml: rule 1e")


def test_an_empty_file_is_rule_1e(tmp_path: Path) -> None:
    write_second(write_root(tmp_path, json.dumps(base_catalog())), "", "empty.yml")

    lines = [line for line in problems_in(tmp_path) if "rule 1e" in line]

    assert len(lines) == 1
    assert lines[0].startswith("metrics/empty.yml: rule 1e")


def test_a_file_with_one_top_key_is_rule_1e(tmp_path: Path) -> None:
    write_second(
        write_root(tmp_path, json.dumps(base_catalog())), "semantic_models: []\n", "half.yml"
    )

    lines = [line for line in problems_in(tmp_path) if "rule 1e" in line]

    assert len(lines) == 1
    assert lines[0].startswith("metrics/half.yml: rule 1e")
    assert "metrics" in lines[0]


def test_an_empty_metrics_folder_is_rule_1a(tmp_path: Path) -> None:
    write_root(tmp_path, json.dumps(base_catalog()))
    (tmp_path / FIRST).unlink()

    assert problems_in(tmp_path) == ["metrics/: rule 1a: no catalog file"]


def test_a_copy_that_breaks_a_per_entry_rule_names_only_its_own_file(tmp_path: Path) -> None:
    root = write_root(tmp_path, json.dumps(base_catalog()))
    broken = copy.deepcopy(get(base_catalog(), "sales"))
    del broken["label"]
    write_second(root, second_with([broken]))

    problems = problems_in(tmp_path)
    per_entry = [line for line in problems if "rule 3a" in line]
    duplicate = [line for line in problems if "rule 2c" in line]

    assert len(per_entry) == 1
    assert per_entry[0].startswith(f"{SECOND}: rule 3a: metric 'sales'")
    assert FIRST not in per_entry[0]
    assert FIRST in duplicate[0]
    assert SECOND in duplicate[0]


def padded_to(lines: int) -> str:
    """Return a valid second catalog file of exactly `lines` lines, padded with comments."""
    return second_with([]) + "\n" + "# padding\n" * (lines - 1)


def test_a_file_of_exactly_500_lines_passes_rule_1f(tmp_path: Path) -> None:
    write_second(write_root(tmp_path, json.dumps(base_catalog())), padded_to(MAX_LINES))

    assert problems_in(tmp_path) == []


def test_a_file_of_501_lines_is_rule_1f_naming_that_file(tmp_path: Path) -> None:
    write_second(write_root(tmp_path, json.dumps(base_catalog())), padded_to(MAX_LINES + 1))

    assert problems_in(tmp_path) == [f"{SECOND}: rule 1f: 501 lines; at most {MAX_LINES}"]


def test_a_name_defined_twice_in_one_file_names_that_file_once(tmp_path: Path) -> None:
    doc = base_catalog()
    doc["metrics"].append(copy.deepcopy(get(base_catalog(), "sales")))
    write_root(tmp_path, json.dumps(doc))

    lines = [line for line in problems_in(tmp_path) if "rule 2c" in line]

    assert len(lines) == 1
    assert lines[0].endswith(f"(in {FIRST})")


def test_an_unknown_column_in_a_measure_is_rule_6a_naming_the_file_of_its_model(
    tmp_path: Path,
) -> None:
    root = write_root(tmp_path, json.dumps(base_catalog()))
    model = {
        "name": "extra_day",
        "model": "ref('stg_extra')",
        "primary_entity": "extra_day",
        "measures": [{"name": "extra_count", "agg": "sum", "expr": "no_such_column"}],
    }
    write_second(root, json.dumps({"semantic_models": [model], "metrics": []}))

    lines = [line for line in problems_in(tmp_path) if "rule 6a" in line and "extra_count" in line]

    assert len(lines) == 1
    assert lines[0].startswith(f"{SECOND}: rule 6a: measure 'extra_count'")
