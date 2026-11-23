"""Fail when the metric catalog in metrics/*.yml breaks a house rule.

It loads every `metrics/*.yml` file, merges them into one catalog and runs the metric catalog's
house rules (docs/CONVENTIONS.md), which live in scripts/metric_catalog_rules.py;
each problem is reported as `rule <number><letter>` and names the file that holds the offending
entry. It checks house rules only; scripts/check_metric_catalog_shape.py hands the files to dbt's
own parser.

Usage: python scripts/check_metric_catalog.py [ROOT]    (ROOT defaults to the repo root)
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Collection, Sequence
from pathlib import Path

from dbt.clients.checked_load import checked_load
from dbt_common.exceptions import DbtValidationError

from check_file_sizes import MAX_LINES, count_lines
from metric_catalog_files import Catalog
from metric_catalog_rules import (
    check_columns,
    check_cycles,
    check_metric,
    check_models,
    check_names,
    check_tree_roots,
)
from metric_catalog_yaml import CATALOG_DIR, Map, as_map, as_text, catalog_files, maps

TOP_KEYS = frozenset({"semantic_models", "metrics"})
# The 37 metrics of the requirements brief's section 7 (docs/requirements-brief.md) plus the two
# helpers. Changing this list changes the brief and this script together.
# fmt: off
EXPECTED_METRICS = frozenset({
    "operating_profit", "operating_revenue", "ride_revenue", "food_drink_revenue",
    "merchandise_revenue", "entrance_revenue", "ride_revenue_by_ride",
    "food_drink_revenue_by_item", "merchandise_revenue_by_item", "operating_costs",
    "ride_running_costs", "staff_wages", "stock_costs", "marketing_costs", "research_costs",
    "capital_spending", "interest_costs", "guest_visits", "average_park_rating",
    "operating_days", "revenue_per_visit", "ride_revenue_per_visit",
    "food_drink_revenue_per_visit", "merchandise_revenue_per_visit",
    "revenue_per_operating_day", "ride_profit", "stall_profit", "stall_units_sold",
    "ride_popularity", "same_park_guest_visits_yoy", "same_park_operating_revenue_yoy",
    "same_park_operating_profit_yoy", "same_park_operating_costs_yoy",
    "company_guest_visits_yoy", "company_operating_revenue_yoy", "company_operating_profit_yoy",
    "company_operating_costs_yoy", "ride_boardings", "ride_open_days",
})
# fmt: on
def load_model_columns(root: Path) -> tuple[dict[str, set[str]], list[str]]:
    """Read the columns of every model named in models/**/*.yml; return them and load problems."""
    columns: dict[str, set[str]] = {}
    problems: list[str] = []
    for path in sorted((root / "models").glob("**/*.yml")):
        try:
            data, _ = checked_load(path.read_text(encoding="utf-8"))
        except DbtValidationError as error:
            problems.append(f"{path.relative_to(root)}: rule 1b: does not load: {error}")
            continue
        for model in maps(as_map(data).get("models")):
            names = {as_text(column.get("name")) for column in maps(model.get("columns"))}
            columns[as_text(model.get("name"))] = names
    return columns, problems


def read_file(path: Path, name: str) -> tuple[Map | None, list[str]]:
    """Read one catalog file (rules 1b to 1e); return its mapping, or None if it has none."""
    try:
        data, failures = checked_load(path.read_text(encoding="utf-8"))
    except DbtValidationError as error:
        return None, [f"{name}: rule 1b: does not load: {error}"]
    if data is None:
        data = {}
    if not isinstance(data, dict):
        return None, [f"{name}: rule 1b: the top level is not a mapping"]
    problems = [f"{name}: rule 1c: {failure.message}" for failure in failures]
    extra = sorted(set(data) - TOP_KEYS)
    if extra:
        problems.append(f"{name}: rule 1d: unexpected top-level key(s) {', '.join(extra)}")
    missing = sorted(TOP_KEYS - set(data))
    if missing:
        problems.append(f"{name}: rule 1e: lacks top-level key(s) {', '.join(missing)}")
    return as_map(data), problems


def merge_file(catalog: Catalog, name: str, data: Map) -> None:
    """Add one file's semantic models and metrics to catalog, recording the file of each entry."""

    def record(kind: str, entry: Map) -> None:
        files = catalog.defined_in.setdefault((kind, as_text(entry.get("name"))), [])
        if name not in files:
            files.append(name)

    for model in maps(data.get("semantic_models")):
        catalog.semantic_models.append(model)
        catalog.sources[id(model)] = name
        record("semantic model", model)
        for measure in maps(model.get("measures")):
            record("measure", measure)
    for metric in maps(data.get("metrics")):
        catalog.metrics.append(metric)
        catalog.sources[id(metric)] = name
        record("metric", metric)


def load_catalog(root: Path) -> tuple[Catalog | None, list[str]]:
    """Load and merge every catalog file (rules 1a to 1f); return it, or None if no rule can run."""
    paths = catalog_files(root)
    if not paths:
        return None, [f"{CATALOG_DIR}/: rule 1a: no catalog file"]
    columns, model_problems = load_model_columns(root)
    catalog = Catalog([], [], columns)
    problems: list[str] = []
    unreadable = False
    for path in paths:
        name = path.relative_to(root).as_posix()
        lines = count_lines(path)
        if lines > MAX_LINES:
            problems.append(f"{name}: rule 1f: {lines} lines; at most {MAX_LINES}")
        data, file_problems = read_file(path, name)
        problems += file_problems
        if data is None:
            unreadable = True
        else:
            merge_file(catalog, name, data)
    return (None if unreadable else catalog), problems + model_problems


def find_problems(root: Path, expected: Collection[str] = EXPECTED_METRICS) -> list[str]:
    """Return one line per rule the catalog under root breaks."""
    catalog, problems = load_catalog(root)
    if catalog is None:
        return problems
    checks: tuple[Callable[[Catalog], None], ...] = (
        lambda c: check_names(c, expected),
        check_models,
        check_columns,
        check_tree_roots,
        check_cycles,
    )
    for check in checks:
        check(catalog)
    for metric in catalog.metrics:
        check_metric(catalog, metric)
    return problems + catalog.problems


def main(argv: Sequence[str] | None = None) -> int:
    """Check the catalog and return a process exit code."""
    parser = argparse.ArgumentParser(
        description="Fail when the metric catalog breaks a house rule."
    )
    parser.add_argument(
        "root", nargs="?", type=Path, default=Path(__file__).resolve().parent.parent
    )
    args = parser.parse_args(argv)
    problems = find_problems(args.root)
    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        print(f"check_metric_catalog: {len(problems)} problem(s).", file=sys.stderr)
        return 1
    print("check_metric_catalog: the catalog passes every house rule.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
