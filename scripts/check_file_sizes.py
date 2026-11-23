"""Fail when a source file is over the line limit, or a baselined file has changed size.

New Python, TypeScript, CSS, SQL, and JavaScript module files stay at or under MAX_LINES. A file
that was already over when the limit arrived sits in BASELINE with its line
count on that date. It may shrink but never grow, and each shrink lowers its
entry in the same change, so the limit only ever tightens.

Inside a git work tree, including a subfolder of a monorepo, the files come
from git, so everything gitignored is skipped. The git pre-commit hook runs the
copy of this script inside its staged snapshot, a temporary folder outside any
work tree that holds only staged files; there the script walks the folder.

Usage: python scripts/check_file_sizes.py [ROOT]    (ROOT defaults to the repo root)
"""

from __future__ import annotations

import argparse
import fnmatch
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

MAX_LINES = 500
CHECKED_SUFFIXES = frozenset({".py", ".ts", ".tsx", ".css", ".sql", ".mjs"})
# Generated files, skipped in both modes. Lockfiles need no entry, because none
# has a checked suffix.
EXCLUDED_FILE_PATTERNS = ("*.gen.ts",)
# Snapshot walk only: installed packages and tool caches, in case one is tracked.
WALK_EXCLUDED_DIRS = frozenset(
    {".git", ".venv", "node_modules", "__pycache__", ".mypy_cache", ".ruff_cache", ".pytest_cache"}
)
# git's message when a folder is outside every repo. A dangling `gitdir:`
# pointer says only "not a git repository: <path>", and must raise instead.
OUTSIDE_ANY_REPO = "not a git repository (or any of the parent directories)"
BASELINE_LOCATION = "`BASELINE` in `scripts/check_file_sizes.py`"
# Files over MAX_LINES when the limit arrived, as "path from repo root": line count.
# Mark each entry with the date and reason, for example:
#     "src/app/big.py": 812,  # BASELINE(2026-09-26): predates the limit
BASELINE: dict[str, int] = {}


def count_lines(path: Path) -> int:
    """Return the number of lines in a file, counting a final unterminated line."""
    with path.open("rb") as handle:
        return sum(1 for _ in handle)


def git_files(root: Path) -> list[str]:
    """Return tracked and untracked, non-ignored files in the git checkout at root."""
    result = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=root,
        capture_output=True,
        check=True,
    )
    return [name for name in result.stdout.decode().split("\0") if name]


def in_git_work_tree(root: Path) -> bool:
    """Return whether root is inside a git work tree, including a monorepo subfolder.

    Raises:
        RuntimeError: if git fails for any reason other than root being outside
            every repo, such as a corrupted `.git` or a dubious-ownership refusal.
    """
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
        capture_output=True,
        text=True,
        check=False,
        # The untranslated message is what OUTSIDE_ANY_REPO matches.
        env={**os.environ, "LC_ALL": "C"},
    )
    if result.returncode == 0:
        return result.stdout.strip() == "true"
    # Outside every repo is the hook-snapshot case, the one expected failure.
    if OUTSIDE_ANY_REPO in result.stderr:
        return False
    raise RuntimeError(f"git rev-parse failed in {root}: {result.stderr.strip()}")


def walked_files(root: Path) -> list[str]:
    """Return every file under root, skipping WALK_EXCLUDED_DIRS, for the hook's snapshot."""
    found: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in WALK_EXCLUDED_DIRS]
        found.extend(Path(dirpath, name).relative_to(root).as_posix() for name in filenames)
    return found


def source_files(root: Path) -> list[str]:
    """Return the checked source files under root, as sorted paths relative to root."""
    names = git_files(root) if in_git_work_tree(root) else walked_files(root)
    return sorted(
        name
        for name in names
        if Path(name).suffix in CHECKED_SUFFIXES
        and not any(fnmatch.fnmatch(Path(name).name, p) for p in EXCLUDED_FILE_PATTERNS)
        # A tracked file deleted from the working tree has no size to check.
        and (root / name).is_file()
    )


def find_problems(
    root: Path, baseline: Mapping[str, int] = BASELINE, max_lines: int = MAX_LINES
) -> list[str]:
    """Return one message per oversized file and per stale or outgrown BASELINE entry."""
    problems: list[str] = []
    seen: set[str] = set()
    for rel in source_files(root):
        lines = count_lines(root / rel)
        if rel not in baseline:
            if lines > max_lines:
                problems.append(
                    f"{rel}: {lines} lines, over the {max_lines}-line limit. "
                    "Split it by responsibility."
                )
            continue
        seen.add(rel)
        recorded = baseline[rel]
        if lines > recorded:
            problems.append(
                f"{rel}: {lines} lines, grew past its entry of {recorded} "
                f"in {BASELINE_LOCATION}. Shrink it back."
            )
        elif lines <= max_lines:
            problems.append(
                f"{rel}: {lines} lines, now within the limit. "
                f"Delete its entry in {BASELINE_LOCATION}."
            )
        elif lines < recorded:
            problems.append(
                f"{rel}: {lines} lines, shrank below its entry of {recorded} "
                f"in {BASELINE_LOCATION}. Lower the entry to {lines}."
            )
    problems.extend(
        f"{rel}: not found. Delete its entry in {BASELINE_LOCATION}."
        for rel in sorted(set(baseline) - seen)
    )
    return problems


def main(argv: Sequence[str] | None = None) -> int:
    """Check the tree and return a process exit code."""
    parser = argparse.ArgumentParser(description="Fail on oversized source files.")
    parser.add_argument(
        "root", nargs="?", type=Path, default=Path(__file__).resolve().parent.parent
    )
    args = parser.parse_args(argv)
    problems = find_problems(args.root)
    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        print(f"check_file_sizes: {len(problems)} problem(s).", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
