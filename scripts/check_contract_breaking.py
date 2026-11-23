"""Fail when a data contract changes in a breaking way without a major version bump.

For each added or modified event contract in `contracts/*.odcs.yaml` and reference contract in
`contracts/reference/*.odcs.yaml` that differs from the merge base with `origin/develop`, it runs
`datacontract breaking <base> <head>`. The tool exits 1 for an ERROR-rated change (a removed field,
a changed type). Deleted contract files are breaking as well. A breaking change to an existing
contract requires that file's major version to rise from the merge base. Deleted event contracts
use the highest major across the remaining event contracts; deleted reference contracts use the
highest major across the remaining reference contracts. A contract file that is new on the branch
has no base and passes as an addition. The tool's own ratings decide what is breaking; this script
holds no list of exceptions.

The check runs only while `CI` is set. With `CI` unset it prints a skip notice and exits 0; with
`CI` set and no `origin/develop` it fails.

Usage: python scripts/check_contract_breaking.py [ROOT]    (ROOT defaults to the repo root)
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from openrct2_analytics.ingest.contracts import read_contract_version

BASE_REF = "origin/develop"
CONTRACT_DIR = "contracts"
REFERENCE_CONTRACT_DIR = f"{CONTRACT_DIR}/reference"
CONTRACT_SUFFIX = ".odcs.yaml"
TOOL_OK = 0
TOOL_BREAKING = 1
VERSION_COMPONENT_COUNT = 3
SKIP_LINE = "check_contract_breaking: skipped, runs only while CI is set"


@dataclass
class Findings:
    """What the tool reported: files it rated breaking, and runs that failed outright."""

    breaking: list[str] = field(default_factory=list)
    output: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def git(root: Path, *args: str) -> str:
    """Run git in root and return its output; a failing git command raises."""
    done = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True
    )
    return done.stdout


def has_base(root: Path) -> bool:
    """Return whether `origin/develop` exists in the checkout at root."""
    done = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--verify", "--quiet", f"refs/remotes/{BASE_REF}"],
        capture_output=True,
        text=True,
        check=False,
    )
    return done.returncode == 0


def changed_contracts(root: Path, base: str) -> list[tuple[str, str]]:
    """Return each added, modified, or deleted contract file since base with its status."""
    listing = git(
        root,
        "diff",
        "--no-renames",
        "--name-status",
        "--diff-filter=AMD",
        base,
        "--",
        f"{CONTRACT_DIR}/*{CONTRACT_SUFFIX}",
        f"{REFERENCE_CONTRACT_DIR}/*{CONTRACT_SUFFIX}",
    )
    changes = [line.split("\t") for line in listing.splitlines()]
    return [(name, status) for status, name in changes]


def major_of(text: str, name: str) -> int:
    """Return the major version parsed from a contract's YAML."""
    try:
        version = read_contract_version(text)
    except ValueError as error:
        raise ValueError(f"{name}: {error}") from error
    parts = version.split(".")
    if len(parts) != VERSION_COMPONENT_COUNT or any(not part.isdecimal() for part in parts):
        raise ValueError(
            f"{name}: invalid contract version {version!r}; expected MAJOR.MINOR.PATCH"
        )
    return int(parts[0])


def contract_scope(name: str) -> str:
    """Return the directory whose contracts share a version line."""
    if name.startswith(f"{REFERENCE_CONTRACT_DIR}/"):
        return REFERENCE_CONTRACT_DIR
    return CONTRACT_DIR


def base_major(root: Path, base: str, name: str) -> int:
    """Return the highest major version in this contract's scope at the merge base."""
    scope = contract_scope(name)
    names = git(root, "ls-tree", "--name-only", base, f"{scope}/").split()
    return max(
        major_of(git(root, "show", f"{base}:{name}"), name)
        for name in names
        if name.endswith(CONTRACT_SUFFIX)
    )


def head_major(root: Path, name: str) -> int | None:
    """Return the highest major version in this contract's scope in the working tree."""
    paths = sorted((root / contract_scope(name)).glob(f"*{CONTRACT_SUFFIX}"))
    if not paths:
        return None
    return max(major_of(path.read_text(encoding="utf-8"), path.name) for path in paths)


def contract_major_bumped(root: Path, base: str, name: str) -> bool:
    """Return whether this contract's major version rose from base to head."""
    old_major = major_of(git(root, "show", f"{base}:{name}"), name)
    head_major_version = major_of((root / name).read_text(encoding="utf-8"), name)
    return head_major_version > old_major


def deleted_contract_major_rose(root: Path, base: str, name: str) -> bool:
    """Return whether a remaining contract in this contract's scope has a higher major."""
    head_version = head_major(root, name)
    return head_version is not None and head_version > base_major(root, base, name)


def run_tool(root: Path, base: str, changes: list[tuple[str, str]]) -> Findings:
    """Check each changed contract; additions have no base and deletions are breaking."""
    findings = Findings()
    tool = Path(sys.executable).parent / "datacontract"
    with tempfile.TemporaryDirectory() as folder:
        for name, status in changes:
            if status == "A":
                continue
            if status == "D":
                findings.breaking.append(name)
                continue
            old = Path(folder) / Path(name).name
            old.write_text(git(root, "show", f"{base}:{name}"), encoding="utf-8")
            done = subprocess.run(
                [str(tool), "breaking", str(old), str(root / name)],
                capture_output=True,
                text=True,
                check=False,
            )
            report = f"{name}:\n{done.stdout}{done.stderr}"
            if done.returncode == TOOL_BREAKING:
                findings.breaking.append(name)
                findings.output.append(report)
            elif done.returncode != TOOL_OK:
                findings.errors.append(report)
    return findings


def main(argv: Sequence[str] | None = None) -> int:
    """Check contract changes against origin/develop and return a process exit code."""
    parser = argparse.ArgumentParser(
        description="Fail a breaking contract change with no major bump."
    )
    parser.add_argument(
        "root", nargs="?", type=Path, default=Path(__file__).resolve().parent.parent
    )
    root = parser.parse_args(argv).root
    if not os.environ.get("CI"):
        print(SKIP_LINE)
        return 0
    if not has_base(root):
        print(f"check_contract_breaking: CI is set but {BASE_REF} is not fetched", file=sys.stderr)
        return 1
    base = git(root, "merge-base", "HEAD", BASE_REF).strip()
    changes = changed_contracts(root, base)
    findings = run_tool(root, base, changes)
    if findings.errors:
        print("check_contract_breaking: datacontract failed:", file=sys.stderr)
        print("\n".join(findings.errors), file=sys.stderr)
        return 1
    statuses = dict(changes)
    unbumped = [
        name
        for name in findings.breaking
        if not (
            deleted_contract_major_rose(root, base, name)
            if statuses[name] == "D"
            else contract_major_bumped(root, base, name)
        )
    ]
    if unbumped:
        print(
            "check_contract_breaking: breaking change without a major version bump in "
            + ", ".join(unbumped),
            file=sys.stderr,
        )
        print("\n".join(findings.output), file=sys.stderr)
        return 1
    print("check_contract_breaking: no breaking change without a major bump.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
