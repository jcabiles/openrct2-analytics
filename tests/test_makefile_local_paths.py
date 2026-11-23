"""The private-path check's place in `make check`, read as make sees the recipe.

Kept apart from `tests/test_makefile.py`, which is at the 500-line limit.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

from tests.test_makefile import MAKEFILE, make_n

DOCS_STEP = "${RUN}python scripts/check_docs.py && \\"
LOCAL_PATHS_STEP = "${RUN}python scripts/check_local_paths.py && \\"
CATALOG_STEP = "${RUN}python scripts/check_metric_catalog.py && \\"


def check_recipe_lines() -> list[str]:
    """The `check` recipe as `make -n check` prints it, one stripped line each."""
    result = make_n("check")
    assert result.returncode == 0, result.stderr
    return [line.strip() for line in result.stdout.splitlines()]


def test_check_runs_the_local_path_check_right_after_the_docs_check() -> None:
    lines = check_recipe_lines()

    # The step must end `&& \` exactly: `|| true`, `; true` or a `-` prefix would change it.
    assert lines.count(LOCAL_PATHS_STEP) == 1
    at = lines.index(LOCAL_PATHS_STEP)
    assert lines[at - 1] == DOCS_STEP
    assert lines[at + 1] == CATALOG_STEP


def test_make_knows_one_check_rule_and_no_ignore_covers_it() -> None:
    database = make_n("-p", "check")
    lines = database.stdout.splitlines()

    assert "overriding" not in database.stderr  # make 3.81: "commands", 4.x: "recipe"
    assert sum(1 for line in lines if re.match(r"check:", line)) == 1
    assert not [line for line in lines if re.match(r"\.IGNORE\b", line)]


def test_no_line_of_the_check_recipe_starts_with_an_ignore_dash() -> None:
    # `make -n` strips the prefixes; the rule database keeps them as written. A leading `-`
    # on the recipe's first line would let the whole recipe fail without failing `make check`.
    lines = make_n("-p", "check").stdout.splitlines()
    start = lines.index("check:")
    recipe = []
    for line in lines[start + 1 :]:
        if not line.startswith("\t"):
            if line.startswith("#"):
                continue
            break
        recipe.append(line.lstrip("\t"))

    assert recipe[0] == "@set -e; \\"
    assert not [line for line in recipe if line.startswith("-")]


def test_check_description_names_absolute_local_paths_after_docs() -> None:
    help_lines = [
        line
        for line in MAKEFILE.read_text(encoding="utf-8").splitlines()
        if line.startswith("check:")
    ]

    assert len(help_lines) == 1
    assert "file sizes, docs, absolute local paths, metric catalog rules," in help_lines[0]


def run_local_path_step(tmp_path: Path, tracked_text: str) -> subprocess.CompletedProcess[str]:
    """Run the recipe's own path-check step in a temporary git repo holding one tracked file."""
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    for name in ("check_local_paths.py", "check_file_sizes.py"):
        shutil.copy(MAKEFILE.parent / "scripts" / name, scripts / name)
    (tmp_path / "notes.md").write_text(tracked_text, encoding="utf-8")
    subprocess.run(["git", "init", "--quiet"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    step = next(line for line in check_recipe_lines() if "scripts/check_local_paths.py" in line)
    command = step.removesuffix("&& \\").replace("${RUN}python", sys.executable)
    return subprocess.run(
        command, shell=True, cwd=tmp_path, capture_output=True, text=True, check=False
    )


def test_the_check_step_passes_on_a_clean_tree(tmp_path: Path) -> None:
    result = run_local_path_step(tmp_path, "a clean line\n")

    assert result.returncode == 0


def test_the_check_step_fails_on_a_planted_private_path(tmp_path: Path) -> None:
    planted = "see " + "/" + "Users" + "/" + "someone/notes\n"

    result = run_local_path_step(tmp_path, planted)

    assert result.returncode == 1
    assert "notes.md:1: absolute local path" in result.stderr
