"""Fail when a dbt model or file in models/ breaks one of the dbt house rules.

It loads every `models/**/*.yml` file and runs the five rules of scripts/dbt_rules.py: (a) required
tests, (b) a unit and a clock statement in every description, (c) the contract version and the
`stg_envelope` type list, (d) no `_tenths` read outside staging, no `select *` from a source and no
`packages.yml`, and (e) the repeat-delivery test applied. Each problem is reported as
`<file>: rule <letter>: <what is wrong>`. Contract fields come from
`openrct2_analytics.ingest.contracts.load_fields`.

Usage: python scripts/check_dbt_rules.py [ROOT]    (ROOT defaults to the repo root)
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from dbt.clients.checked_load import checked_load
from dbt_common.exceptions import DbtValidationError

from dbt_rules import (
    MODELS_DIR,
    Model,
    Project,
    check_contract,
    check_descriptions,
    check_forbidden,
    check_repeat_test,
    check_required_tests,
)
from metric_catalog_yaml import as_map, as_text, maps
from openrct2_analytics.ingest.contracts import load_fields

RULES: tuple[Callable[[Project], list[str]], ...] = (
    check_required_tests,
    check_descriptions,
    check_contract,
    check_forbidden,
    check_repeat_test,
)


def load_models(root: Path) -> tuple[list[Model], list[str]]:
    """Read every model named under `models:` in models/**/*.yml; return them and load problems."""
    models: list[Model] = []
    problems: list[str] = []
    for path in sorted((root / MODELS_DIR).glob("**/*.yml")):
        name = path.relative_to(root).as_posix()
        try:
            data, _ = checked_load(path.read_text(encoding="utf-8"))
        except DbtValidationError as error:
            problems.append(f"{name}: does not load: {error}")
            continue
        models.extend(
            Model(as_text(m.get("name")), name, m) for m in maps(as_map(data).get("models"))
        )
    return models, problems


def find_problems(root: Path) -> list[str]:
    """Return one line per rule the dbt project under root breaks."""
    models, problems = load_models(root)
    project = Project(root, models, load_fields(root / "contracts"))
    for rule in RULES:
        problems += rule(project)
    return problems


def main(argv: Sequence[str] | None = None) -> int:
    """Check the dbt project and return a process exit code."""
    parser = argparse.ArgumentParser(description="Fail when a dbt model breaks a house rule.")
    parser.add_argument(
        "root", nargs="?", type=Path, default=Path(__file__).resolve().parent.parent
    )
    args = parser.parse_args(argv)
    problems = find_problems(args.root)
    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        print(f"check_dbt_rules: {len(problems)} problem(s).", file=sys.stderr)
        return 1
    print("check_dbt_rules: the dbt project passes every house rule.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
