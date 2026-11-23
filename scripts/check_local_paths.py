"""Fail when a tracked text file holds an absolute path to a folder on a local machine.

The repo rule forbids private machine paths in committed files. There is no allowed prefix and
no file-level exemption: a doc that needs a path writes a placeholder or plain words, and a test
builds its planted path at run time.

Files come from `git ls-files` (tracked only, so untracked scratch never fails the run). Outside
a git work tree the folder is walked. Each file is read as bytes and matched with byte
patterns, so one undecodable byte cannot hide a path; a file with a NUL byte is binary and
skipped. A symbolic link is checked by its target text.

Usage: python scripts/check_local_paths.py [ROOT]    (ROOT defaults to the repo root)
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from check_file_sizes import in_git_work_tree, walked_files

MESSAGE = "absolute local path (reword it, or build it at run time in a test)"
# The one list of forbidden forms. Each pattern is written so its own text does not match it
# (a bracketed slash where the path would continue), which keeps this file clean. The left
# boundary keeps `docs/tmp/x` and a web URL out; FOLLOW is the character a folder name may
# start with.
LEFT = rb"(?<![A-Za-z0-9_.~$}-])"
FOLLOW = rb"[A-Za-z0-9_.]"
FORMS: tuple[re.Pattern[bytes], ...] = tuple(
    re.compile(pattern)
    for pattern in (
        LEFT + rb"/private/(?:tmp|var)[/]",
        LEFT + rb"/var/(?:folders|tmp)[/]",
        LEFT + rb"/tmp[/]" + FOLLOW,
        LEFT + rb"/home[/]" + FOLLOW,
        LEFT + rb"/root[/]" + FOLLOW,
        LEFT + rb"/Volumes[/]" + FOLLOW,
        LEFT + rb"/Users[/]" + FOLLOW,
        # The left boundary above hides /Users after the "Data" folder name.
        LEFT + rb"/System/Volumes/Data[/]Users[/]" + FOLLOW,
        # A lone drive letter, so regex text such as a time pattern does not match.
        rb"(?<![A-Za-z0-9_\\])[A-Za-z]:\\[A-Za-z]",
        # A local file link, with or without the host name `localhost`, in any letter case.
        LEFT + rb"(?i:file:[/]{2}(?:localhost)?[/])",
    )
)


def tracked_files(root: Path) -> list[str]:
    """Return the tracked files under root, or every file when root is not in a work tree."""
    if not in_git_work_tree(root):
        return walked_files(root)
    result = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True)
    return [name for name in result.stdout.decode().split("\0") if name]


def find_problems(root: Path) -> list[str]:
    """Return one message per line that holds an absolute local path, in path and line order.

    Raises:
        OSError: if a listed regular file or link cannot be read.
    """
    problems: list[str] = []
    # A file in a merge conflict is listed once per stage; scan and report it once.
    for rel in sorted(set(tracked_files(root))):
        path = root / rel
        # Git commits a link's target as text, so the target string is scanned, never followed.
        if path.is_symlink():
            data = os.fsencode(os.readlink(path))
        # A tracked file deleted from the work tree has nothing to scan.
        elif path.is_file():
            data = path.read_bytes()
        else:
            continue
        if b"\0" in data:
            continue
        for number, line in enumerate(data.split(b"\n"), start=1):
            if any(form.search(line) for form in FORMS):
                problems.append(f"{rel}:{number}: {MESSAGE}")
    return problems


def main(argv: Sequence[str] | None = None) -> int:
    """Check the tree and return a process exit code."""
    parser = argparse.ArgumentParser(description="Fail on absolute local paths in tracked files.")
    parser.add_argument(
        "root", nargs="?", type=Path, default=Path(__file__).resolve().parent.parent
    )
    args = parser.parse_args(argv)
    if not args.root.is_dir():
        print(f"check_local_paths: not a folder: {args.root}", file=sys.stderr)
        return 2
    try:
        problems = find_problems(args.root)
    except OSError as error:
        print(f"check_local_paths: cannot read {error.filename}: {error.strerror}", file=sys.stderr)
        return 1
    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        print(f"check_local_paths: {len(problems)} problem(s).", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
