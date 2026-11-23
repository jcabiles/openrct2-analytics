"""Check that the repo's Python environment is whole, without syncing it first.

Usage: .venv/bin/python scripts/doctor.py [--root DIR] [--managed-dir DIR]

Run it with the venv's own Python, never `uv run`: `uv run` syncs first and would hide the damage.
It fails when `.venv/bin/python` is missing, when `.venv/pyvenv.cfg` does not point at a Python
inside uv's managed-Python folder (skipped, with a note, when `uv` is not on PATH), when a file
listed in an installed package's RECORD is missing, or when the venv's own Python cannot import
`dbt.cli.main` and `openrct2_analytics`. Every check works offline: nothing here contacts a server.
"""

from __future__ import annotations

import argparse
import csv
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

MAX_PATHS_PER_PACKAGE = 5
REPAIR = (
    "Repair: rm -rf .venv && make setup\n"
    "`uv sync` alone cannot repair this: it trusts the stale install records (*.dist-info) "
    "and reports every package installed while its code is missing."
)


@dataclass
class Report:
    """What the checks found: `damage` calls for the repair; `errors` and `notes` never do."""

    damage: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class Scan:
    """The RECORD scan of one site-packages folder, keyed by install-record folder name."""

    missing: dict[str, list[str]] = field(default_factory=dict)
    unreadable: dict[str, list[str]] = field(default_factory=dict)
    unverifiable: list[str] = field(default_factory=list)


def find_managed_dir(report: Report) -> Path | None:
    """Ask uv for its managed-Python folder; None when uv is absent or the question failed."""
    uv = shutil.which("uv")
    if uv is None:
        report.notes.append("managed-Python check skipped: uv is not on PATH")
        return None
    try:
        result = subprocess.run([uv, "python", "dir"], capture_output=True, text=True, check=False)
    except OSError as error:
        report.errors.append(
            f"cannot run `uv python dir` to find the managed Python folder: {error}"
        )
        return None
    if result.returncode != 0:
        tail = result.stderr.strip().splitlines()[-1:] or ["no error output"]
        report.errors.append(f"`uv python dir` exited {result.returncode}: {tail[0]}")
        return None
    return Path(result.stdout.strip())


def check_home(venv: Path, managed_dir: Path) -> list[str]:
    """Return a problem when pyvenv.cfg is missing or its `home` is outside the managed folder."""
    cfg = venv / "pyvenv.cfg"
    if not cfg.is_file():
        return [f"{cfg} is missing"]
    home = None
    for line in cfg.read_text(encoding="utf-8").splitlines():
        key, _, value = line.partition("=")
        if key.strip() == "home":
            home = value.strip()
    if home is None:
        return ["pyvenv.cfg has no `home` line"]
    if not Path(home).resolve().is_relative_to(managed_dir.resolve()):
        return [f"pyvenv.cfg home is not inside uv's managed folder {managed_dir} (home = {home})"]
    return []


def lstat_state(path: Path) -> str:
    """Return "present", "missing" or "unreadable" without reading the file's contents."""
    try:
        os.lstat(path)
    except (FileNotFoundError, NotADirectoryError):
        return "missing"
    except PermissionError:
        return "unreadable"
    return "present"


def code_folder_present(site: Path, folder: str) -> bool:
    """True when the package's top-level code (a folder or .py file) exists in site-packages."""
    tops = [folder.rsplit(".", 1)[0].rsplit("-", 1)[0].replace("-", "_")]
    top_level = site / folder / "top_level.txt"
    if top_level.is_file():
        tops = top_level.read_text(encoding="utf-8").split() or tops
    return any(
        lstat_state(site / top) != "missing" or lstat_state(site / f"{top}.py") != "missing"
        for top in tops
    )


def scan_record_files(site: Path) -> Scan:
    """Check every RECORD entry exists; bytecode entries are skipped."""
    scan = Scan()
    for info in [*sorted(site.glob("*.dist-info")), *sorted(site.glob("*.egg-info"))]:
        record = info / "RECORD"
        if not record.is_file():
            # An .egg-info install has no RECORD by design; a dist-info may have lost it.
            if code_folder_present(site, info.name):
                scan.unverifiable.append(info.name)
            else:
                scan.missing.setdefault(info.name, []).append("the code folder (and no RECORD)")
            continue
        # Parsed by hand: importlib's dist.files silently drops entries whose files are absent.
        for row in csv.reader(record.read_text(encoding="utf-8").splitlines()):
            if not row:
                continue
            path = row[0]
            if "__pycache__" in PurePosixPath(path).parts or path.endswith(".pyc"):
                continue
            state = lstat_state(site / path)
            if state == "missing":
                scan.missing.setdefault(info.name, []).append(path)
            elif state == "unreadable":
                scan.unreadable.setdefault(info.name, []).append(path)
    return scan


def run_probe(command: list[str], label: str) -> str | None:
    """Run a command; return a problem when it cannot launch or exits non-zero."""
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
    except OSError as error:
        return f"{label} cannot be launched: {error}"
    if result.returncode != 0:
        tail = result.stderr.strip().splitlines()[-1:] or ["no error output"]
        return f"{label} exited {result.returncode}: {tail[0]}"
    return None


def check_tools(venv: Path) -> list[str]:
    """Return problems with `bin/dbt` and with importing dbt and this project, run offline."""
    problems = []
    dbt = venv / "bin" / "dbt"
    if not dbt.exists():
        problems.append(f"{dbt} is missing")
    elif not os.access(dbt, os.X_OK):
        problems.append(f"{dbt} is not executable")
    imports = run_probe(
        [str(venv / "bin" / "python"), "-c", "import dbt.cli.main, openrct2_analytics"],
        "importing dbt and openrct2_analytics with the venv's Python",
    )
    if imports:
        problems.append(imports)
    return problems


def summarize_missing(missing: dict[str, list[str]]) -> list[str]:
    """Summary first (a count per package), then at most MAX_PATHS_PER_PACKAGE paths per package."""
    total = sum(len(paths) for paths in missing.values())
    lines = [f"{len(missing)} package(s) with {total} missing file(s):"]
    lines.extend(
        f"    {package}: {len(paths)} missing" for package, paths in sorted(missing.items())
    )
    for package, paths in sorted(missing.items()):
        shown = sorted(paths)[:MAX_PATHS_PER_PACKAGE]
        lines.extend(f"    {package}: {path}" for path in shown)
        if len(paths) > len(shown):
            lines.append(f"    {package}: ... and {len(paths) - len(shown)} more")
    return lines


def diagnose(venv: Path, managed_dir: Path | None, report: Report) -> None:
    """Fill `report` with every problem found in the venv; empty damage and errors means healthy."""
    if lstat_state(venv / "bin" / "python") == "missing":
        report.damage.append(f"{venv / 'bin' / 'python'} is missing")
        return
    if managed_dir is not None:
        report.damage.extend(check_home(venv, managed_dir))
    elif not (venv / "pyvenv.cfg").is_file():
        report.damage.append(f"{venv / 'pyvenv.cfg'} is missing")
    site_dirs = sorted(venv.glob("lib/python*/site-packages"))
    if not site_dirs:
        report.damage.append(f"no site-packages folder under {venv / 'lib'}")
    for site in site_dirs:
        scan = scan_record_files(site)
        report.notes.extend(f"cannot verify: {folder}" for folder in scan.unverifiable)
        for package, paths in sorted(scan.unreadable.items()):
            report.notes.append(
                f"present but unreadable here: {package}, {len(paths)} file(s), e.g. {paths[0]}"
            )
        if scan.missing:
            report.damage.extend(summarize_missing(scan.missing))
    report.damage.extend(check_tools(venv))


def main(argv: Sequence[str] | None = None) -> int:
    """Run the checks, print the result and timing, and return a process exit code."""
    parser = argparse.ArgumentParser(description="Check the Python environment is whole.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument(
        "--managed-dir", type=Path, help="uv's managed-Python folder; asked of uv if omitted"
    )
    args = parser.parse_args(argv)
    started = time.perf_counter()
    report = Report()
    managed_dir = args.managed_dir if args.managed_dir is not None else find_managed_dir(report)
    diagnose(args.root / ".venv", managed_dir, report)
    elapsed = time.perf_counter() - started
    failed = bool(report.damage or report.errors)
    stream = sys.stderr if failed else sys.stdout
    if report.damage:
        print("doctor: the Python environment is damaged.", file=stream)
    elif report.errors:
        print("doctor: a check could not run.", file=stream)
    else:
        print("doctor: the Python environment is whole.", file=stream)
    for line in [*report.damage, *report.errors]:
        print(f"  {line}", file=stream)
    for note in report.notes:
        print(f"  note: {note}", file=stream)
    if report.damage:
        print(REPAIR, file=stream)
    print(f"doctor: took {elapsed:.2f}s")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
