"""The warehouse-path guard, through its module entry, on `$TMPDIR` fixtures."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from openrct2_analytics.ingest.warehouse_guard import (
    UnsafeWarehousePath,
    check_warehouse_path,
    is_published,
)

PUBLISHED = ("rehearsal.duckdb", "company.duckdb")


def guard(project: Path, root: Path, path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "openrct2_analytics.ingest.warehouse_guard",
            "--project-dir",
            str(project),
            "--root",
            str(root),
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def snapshot(folder: Path) -> dict[str, tuple[bytes, int, int]]:
    """Bytes, mode and modification time of every file under folder."""
    return {
        str(item): (item.read_bytes(), item.stat().st_mode, item.stat().st_mtime_ns)
        for item in sorted(folder.rglob("*"))
        if item.is_file()
    }


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A project copy holding writable stand-ins of both published files."""
    warehouse = tmp_path / "project" / "warehouse"
    warehouse.mkdir(parents=True)
    for name in PUBLISHED:
        (warehouse / name).write_bytes(f"stand-in {name}".encode())
    return tmp_path / "project"


@pytest.fixture
def ci_dir(tmp_path: Path) -> Path:
    folder = tmp_path / "ci"
    folder.mkdir()
    return folder


@pytest.mark.parametrize("name", PUBLISHED)
def test_ci_file_linked_to_a_published_file_is_refused_and_the_file_is_untouched(
    project: Path, ci_dir: Path, name: str
) -> None:
    (ci_dir / "ci.duckdb").symlink_to(project / "warehouse" / name)
    before = snapshot(project)

    done = guard(project, ci_dir, ci_dir / "ci.duckdb")

    assert done.returncode == 2
    assert "warehouse path refused: symlink:" in done.stderr
    assert snapshot(project) == before
    assert not list(project.rglob("*.wal"))


def test_ci_folder_that_is_a_link_is_refused(project: Path, tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(real)

    done = guard(project, linked, linked / "ci.duckdb")

    assert done.returncode == 2
    assert "warehouse path refused: symlink:" in done.stderr


def test_hard_link_to_a_published_file_is_refused_as_published(project: Path, ci_dir: Path) -> None:
    os.link(project / "warehouse" / "rehearsal.duckdb", ci_dir / "ci.duckdb")

    done = guard(project, ci_dir, ci_dir / "ci.duckdb")

    assert done.returncode == 2
    assert "warehouse path refused: published:" in done.stderr


def test_warehouse_folder_that_is_a_link_is_refused(project: Path, tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (project / "warehouse").rename(tmp_path / "moved")
    (project / "warehouse").symlink_to(elsewhere)
    candidate = project / "warehouse" / "candidate" / "run-x" / "rehearsal.duckdb"

    done = guard(project, project / "warehouse", candidate)

    assert done.returncode == 2
    assert "warehouse path refused: symlink:" in done.stderr
    assert not list(elsewhere.iterdir())


def test_path_that_leaves_the_root_without_a_link_is_refused(project: Path, ci_dir: Path) -> None:
    before = snapshot(project.parent)

    done = guard(project, ci_dir, ci_dir / ".." / "outside.duckdb")

    assert done.returncode == 2
    assert "warehouse path refused: outside-root:" in done.stderr
    assert snapshot(project.parent) == before


def test_parent_component_after_symlink_is_refused_as_outside_root(
    project: Path, tmp_path: Path
) -> None:
    external = tmp_path / "elsewhere"
    (external / "sub").mkdir(parents=True)
    (project / "warehouse" / "candidate").symlink_to(external / "sub")
    path = project / "warehouse" / "candidate" / ".." / "evil.duckdb"

    done = guard(project, project / "warehouse", path)

    assert done.returncode == 2
    assert "warehouse path refused: outside-root:" in done.stderr


def test_parent_component_without_a_link_is_refused_as_outside_root(project: Path) -> None:
    path = project / "warehouse" / ".." / "x.duckdb"

    done = guard(project, project / "warehouse", path)

    assert done.returncode == 2
    assert "warehouse path refused: outside-root:" in done.stderr


def test_fresh_folder_is_safe(project: Path, ci_dir: Path) -> None:
    done = guard(project, ci_dir, ci_dir / "ci.duckdb")

    assert (done.returncode, done.stderr) == (0, "")


def test_candidate_path_under_a_missing_folder_is_safe(project: Path) -> None:
    candidate = project / "warehouse" / "candidate" / "run-x" / "rehearsal.duckdb"

    assert guard(project, project / "warehouse", candidate).returncode == 0


def test_published_and_previous_paths_are_refused_by_name(project: Path) -> None:
    root = project / "warehouse"
    for path in (root / "company.duckdb", root / "previous" / "rehearsal.duckdb"):
        with pytest.raises(UnsafeWarehousePath) as refused:
            check_warehouse_path(path, root=root, project_dir=project)
        assert refused.value.reason == "published"
    assert is_published(root / "rehearsal.duckdb", project_dir=project)
    assert not is_published(root / "dev" / "dev.duckdb", project_dir=project)


def test_link_in_an_ancestor_of_the_root_is_refused(project: Path, tmp_path: Path) -> None:
    real = tmp_path / "real"
    (real / "ci").mkdir(parents=True)
    (tmp_path / "linked").symlink_to(real)
    root = tmp_path / "linked" / "ci"

    done = guard(project, root, root / "ci.duckdb")

    assert done.returncode == 2
    assert "warehouse path refused: symlink:" in done.stderr


def test_hard_link_to_a_previous_file_outside_previous_is_refused(
    project: Path, ci_dir: Path
) -> None:
    previous = project / "warehouse" / "previous"
    previous.mkdir()
    (previous / "rehearsal.duckdb").write_bytes(b"older")
    os.link(previous / "rehearsal.duckdb", ci_dir / "ci.duckdb")

    assert is_published(ci_dir / "ci.duckdb", project_dir=project)
    done = guard(project, ci_dir, ci_dir / "ci.duckdb")

    assert done.returncode == 2
    assert "warehouse path refused: published:" in done.stderr
