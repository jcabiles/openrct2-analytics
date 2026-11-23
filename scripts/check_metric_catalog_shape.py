"""Fail when dbt's own parser rejects metrics/*.yml as dbt 1.11 semantic models and metrics.

It copies the dbt project to a temporary folder, adds each catalog file under `models/` as
`metric_catalog_<stem>.yml`, a minimal time spine and a one-line stub for each planned semantic
model, and runs `dbt parse` there, so nothing
is written to the repo. docs/CONVENTIONS.md and ARCHITECTURE.md describe the check.

dbt-core 1.11.15's semantic validator creates a process pool, which raises `PermissionError` inside
Claude Code's sandbox. The parse therefore runs with that pool swapped for a thread pool. If the
crash still happens, the skip rule applies: allowed while `CI` is unset, refused when it is set.

Usage: python scripts/check_metric_catalog_shape.py [ROOT]    (ROOT defaults to the repo root)
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from dbt.clients.checked_load import checked_load

from metric_catalog_yaml import CATALOG_DIR, REF, as_map, as_text, catalog_files, maps, meta_of

SKIP_LINE = "skipped: sandbox process-pool limit; allowed only while CI is unset"
SANDBOX_MARKERS = ("PermissionError", "SC_SEM_NSEMS_MAX")
COPIED = ("dbt_project.yml", "profiles.yml", "models", "macros", "tests/dbt")
TIME_SPINE_SQL = "select cast('2020-01-01' as date) as date_day\n"
TIME_SPINE_YAML = """version: 2
models:
  - name: metricflow_time_spine
    time_spine:
      standard_granularity_column: date_day
    columns:
      - name: date_day
        granularity: day
"""
# Runs dbt's CLI with the validator's process pool replaced by a thread pool, so the semantic
# validator runs inside the sandbox. Reading the name first fails loudly if dbt moves it.
PARSE_WITH_THREADS = """
import sys
from concurrent.futures import ThreadPoolExecutor
import dbt_semantic_interfaces.validations.semantic_manifest_validator as validator
validator.ProcessPoolExecutor
validator.ProcessPoolExecutor = ThreadPoolExecutor
from dbt.cli.main import cli
cli.main(args=sys.argv[1:], prog_name="dbt")
"""


@dataclass(frozen=True)
class Decision:
    """What the script prints and the exit code it returns."""

    exit_code: int
    message: str


def decide(returncode: int, output: str, ci: str | None) -> Decision:
    """Turn dbt's exit code and output, and the `CI` value, into the script's verdict."""
    if returncode == 0:
        return Decision(0, "check_metric_catalog_shape: dbt parse accepts the catalog.")
    if all(marker in output for marker in SANDBOX_MARKERS) and not ci:
        return Decision(0, SKIP_LINE)
    return Decision(1, output)


def planned_stubs(catalogs: list[Path]) -> list[str]:
    """Return the dbt model name of each semantic model marked planned_model: true."""
    refs = [
        REF.search(as_text(model.get("model")))
        for catalog in catalogs
        for model in maps(
            as_map(checked_load(catalog.read_text(encoding="utf-8"))[0]).get("semantic_models")
        )
        if meta_of(model).get("planned_model") is True
    ]
    return [match.group(1) for match in refs if match]


def build_project(root: Path, work: Path) -> None:
    """Copy the dbt project from root into work and add the catalog, time spine and stubs."""
    for name in COPIED:
        source = root / name
        if source.is_dir():
            shutil.copytree(source, work / name)
        elif source.is_file():
            shutil.copy2(source, work / name)
    models = work / "models"
    models.mkdir(exist_ok=True)
    catalogs = catalog_files(root)
    for catalog in catalogs:
        shutil.copy2(catalog, models / f"metric_catalog_{catalog.stem}.yml")
    (models / "metricflow_time_spine.sql").write_text(TIME_SPINE_SQL, encoding="utf-8")
    (models / "metricflow_time_spine.yml").write_text(TIME_SPINE_YAML, encoding="utf-8")
    for name in planned_stubs(catalogs):
        stub = models / f"{name}.sql"
        if not stub.exists():
            stub.write_text("select 1 as id\n", encoding="utf-8")


def run_parse(work: Path) -> tuple[int, str]:
    """Run `dbt parse` in work; return its exit code and its combined output."""
    done = subprocess.run(
        [
            sys.executable,
            "-c",
            PARSE_WITH_THREADS,
            "parse",
            "--profiles-dir",
            ".",
            "--no-use-colors",
        ],
        cwd=work,
        capture_output=True,
        text=True,
        check=False,
    )
    return done.returncode, done.stdout + done.stderr


def main(argv: Sequence[str] | None = None) -> int:
    """Check the catalog's shape with dbt and return a process exit code."""
    parser = argparse.ArgumentParser(description="Have dbt parse the metric catalog.")
    parser.add_argument(
        "root", nargs="?", type=Path, default=Path(__file__).resolve().parent.parent
    )
    root = parser.parse_args(argv).root
    if not catalog_files(root):
        print(f"{CATALOG_DIR}/: no catalog file", file=sys.stderr)
        return 1
    with tempfile.TemporaryDirectory() as folder:
        work = Path(folder)
        build_project(root, work)
        returncode, output = run_parse(work)
    decision = decide(returncode, output, os.environ.get("CI"))
    print(decision.message, file=sys.stderr if decision.exit_code else sys.stdout)
    return decision.exit_code


if __name__ == "__main__":
    sys.exit(main())
