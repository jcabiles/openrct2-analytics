"""Remove rebuildable company files before applying verified original changes."""

from __future__ import annotations

import csv
import fnmatch
import hashlib
import os
import shutil
from pathlib import Path

from openrct2_analytics.ingest import play_mode_feed
from openrct2_analytics.ingest.delete_archive import StepObserver
from openrct2_analytics.ingest.delete_plan import (
    Change,
    Plan,
    Scope,
    named_plan,
    removal_change,
)
from openrct2_analytics.ingest.publish_errors import PublishFailed, PublishRefused
from openrct2_analytics.ingest.registry_feed import check_feed

COMPANY = "company"


def _company_candidate(folder: Path) -> bool:
    databases = list(folder.rglob("*.duckdb"))
    if len(databases) > 1 or any(path.name != "company.duckdb" for path in databases):
        return False
    # Label files are not company evidence; a header-only one must not hide the candidate.
    copies = [
        path
        for path in (folder / "landing/registry/v1").glob("*.csv")
        if not fnmatch.fnmatch(path.name, play_mode_feed.FILE_GLOB)
    ]
    evidence = bool(databases)
    for path in copies:
        try:
            with path.open(newline="") as stream:
                rows = list(csv.DictReader(stream))
        except (UnicodeDecodeError, csv.Error):
            # A copy that cannot be read is not proven to be company, so the folder stays.
            return False
        if not rows or any(row.get("data_set") != COMPANY for row in rows):
            return False
        evidence = True
    return evidence


def derived_paths(company: Path, warehouse: Path) -> tuple[list[Path], list[str]]:
    """List exactly the rebuildable paths and explain every retained candidate."""
    paths = [company / "parquet/v1", company / "parquet/audit", *company.glob(".parquet-*")]
    for base in (warehouse / "company.duckdb", warehouse / "previous/company.duckdb"):
        paths.extend((base, Path(f"{base}.wal")))
    paths.extend(
        (warehouse / "previous/company.duckdb.new", warehouse / "previous/company.duckdb.new.wal")
    )
    notes = []
    for folder in sorted((warehouse / "candidate").glob("run-*")):
        if _company_candidate(folder):
            paths.append(folder)
        else:
            notes.append(f"candidate kept (not exclusively company): {folder}")
    return [path for path in paths if os.path.lexists(path)], notes


def build_plan(scope: Scope, company: Path, warehouse: Path, live: str | None) -> Plan:
    """Build the authoritative snapshot; delete-all reads raw lines only to count sessions."""
    plan = named_plan(scope, company) if scope.named else Plan(scope)
    plan.live = live
    plan.derived, notes = derived_paths(company, warehouse)
    plan.notes.extend(notes)
    if not scope.named and live is None:
        events = set((company / "raw").glob("v*/events-*.jsonl"))
        for path in sorted(company.rglob("*")):
            if not path.is_file() or path == company / "parquet.lock":
                continue
            if any(path == derived or path.is_relative_to(derived) for derived in plan.derived):
                continue
            original = path.read_bytes()
            plan.changes.append(
                removal_change(path, original) if path in events else Change(path, original, None)
            )
    root = company.resolve()
    for change in plan.changes:
        if not change.path.resolve().is_relative_to(root):
            raise PublishRefused("unsafe-path", f"{change.path} resolves outside {company}")
    return plan


def registry_problems(company: Path) -> list[str]:
    """Check the current company deliveries; a folder without any is not a problem."""
    if not list((company / "registry/v1").glob("park_registry_*.csv")):
        return []
    return check_feed(company / "registry")


def label_problems(company: Path) -> list[str]:
    """Check the current company label files; a folder without any is clean."""
    return play_mode_feed.check_feed(company / "registry", data_set=COMPANY)


def _change_original(change: Change) -> None:
    if hashlib.sha256(change.path.read_bytes()).hexdigest() != change.digest:
        raise PublishFailed("changed-during-delete", str(change.path))
    if change.kept is None:
        change.path.unlink()
    else:
        temporary = change.path.with_name(f".{change.path.name}.delete-tmp")
        temporary.write_bytes(change.kept)
        os.replace(temporary, change.path)


def apply(plan: Plan, company: Path, on_step: StepObserver) -> None:
    """Invalidate derived files, re-hash and change originals, then check the feed."""
    for path in plan.derived:
        on_step("removing-derived")
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()
    for change in plan.changes:
        on_step("changing-original")
        _change_original(change)
    if plan.scope.named:
        problems = registry_problems(company)
        if problems:
            raise PublishFailed("registry-check", "; ".join(problems))
        problems = label_problems(company)
        if problems:
            raise PublishFailed("label-check", "; ".join(problems))
    if not plan.scope.named and plan.live is None:
        for folder in sorted(company.rglob("*"), key=lambda p: len(p.parts), reverse=True):
            if folder.is_dir() and not any(folder.iterdir()):
                folder.rmdir()
