"""Command-line recovery after publisher crashes at rotation boundaries."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path

import pytest

from openrct2_analytics.ingest.publish import main, publish
from tests.publish_standin import read_stamp, start_crashing_process, write_stamped
from tests.test_publish import land_sample, standin

WAIT_SECONDS = 30
LOCK_LINE_PREFIX = "crashed-run "


@dataclass(frozen=True)
class CrashCase:
    """One crash-table row and its expected disk state."""

    row: str
    step: str
    first_publish: bool
    before: tuple[str | None, str | None, str | None]
    recovery_output: str
    rollback_result: tuple[str | None, str | None, str | None]
    publish_result: tuple[str, str]


CASES = (
    CrashCase(
        "C4",
        "previous-linked",
        False,
        ("2", "1", "2"),
        "it was the same file",
        ("1", None, None),
        ("4", "2"),
    ),
    CrashCase(
        "C5",
        "renamed",
        False,
        ("3", "1", "2"),
        "moved",
        ("2", None, None),
        ("4", "3"),
    ),
    CrashCase(
        "C6",
        "renamed",
        True,
        ("1", None, None),
        "no interrupted rotation",
        ("1", None, None),
        ("2", "1"),
    ),
    CrashCase(
        "C7",
        "previous-rotated",
        False,
        ("3", "2", None),
        "no interrupted rotation",
        ("2", None, None),
        ("4", "3"),
    ),
)


def _paths(project: Path) -> tuple[Path, Path, Path, Path, Path]:
    warehouse = project / "warehouse"
    published = warehouse / "rehearsal.duckdb"
    previous = warehouse / "previous" / "rehearsal.duckdb"
    new_file = previous.with_name(f"{previous.name}.new")
    lock = warehouse / "rehearsal.lock"
    return published, previous, new_file, lock, warehouse / "candidate"


def _optional_stamp(path: Path) -> str | None:
    return read_stamp(path) if path.exists() else None


def _stamps(published: Path, previous: Path, new_file: Path) -> tuple[str | None, ...]:
    return tuple(_optional_stamp(path) for path in (published, previous, new_file))


def _publish_child(
    project: Path, run_id: str, version: str, on_step: Callable[[str], None]
) -> None:
    """Publish in a spawned process so the stand-in can exit without cleanup."""
    publish(
        "rehearsal",
        run_id=run_id,
        build=standin("rehearsal", version=version),
        on_step=on_step,
        project_dir=project,
    )


def _crash_and_clear_lock(
    tmp_path: Path,
    landing_root: Path,
    capsys: pytest.CaptureFixture[str],
    case: CrashCase,
) -> tuple[Path, Path, Path, Path]:
    """Crash at one table row, check the lock refusal, then follow stale-lock steps."""
    land_sample(landing_root, "rehearsal")
    project = tmp_path / case.row
    project.mkdir()
    published, previous, new_file, lock, candidates = _paths(project)
    if not case.first_publish:
        write_stamped(published, "2")
        write_stamped(previous, "1")

    process = start_crashing_process(
        case.step,
        partial(_publish_child, project, "crashed-run", "1" if case.first_publish else "3"),
    )
    process.join(timeout=WAIT_SECONDS)
    if process.is_alive():
        process.terminate()
        process.join()
        pytest.fail(f"child did not stop at {case.row} ({case.step})")
    assert process.exitcode == 86

    assert _stamps(published, previous, new_file) == case.before
    assert lock.is_file()
    lock_line = lock.read_text(encoding="utf-8").strip()
    assert lock_line.startswith(LOCK_LINE_PREFIX)

    result = main(
        ["--data-set", "rehearsal"],
        run_id="stale-attempt",
        build=standin("rehearsal", version="stale"),
        project_dir=project,
    )
    assert result == 2
    output = capsys.readouterr().out
    assert output.count("\n") == 1
    assert str(lock) in output
    assert lock_line in output
    assert "ARCHITECTURE.md" in output
    assert "Environments and publishing" in output
    assert _stamps(published, previous, new_file) == case.before

    lock.unlink()
    shutil.rmtree(candidates / "run-crashed-run")
    assert not lock.exists()
    assert not (candidates / "run-crashed-run").exists()
    return project, published, previous, new_file


@pytest.mark.parametrize("case", CASES, ids=lambda case: f"{case.row}-{case.step}")
def test_crash_rows_recover_through_rollback_without_losing_versions(
    tmp_path: Path,
    landing_root: Path,
    capsys: pytest.CaptureFixture[str],
    case: CrashCase,
) -> None:
    """C4-C7: check each table row before recovery, stale-lock refusal, and rollback."""
    project, published, previous, new_file = _crash_and_clear_lock(
        tmp_path, landing_root, capsys, case
    )

    result = main(
        ["--data-set", "rehearsal", "--rollback"],
        project_dir=project,
    )
    output = capsys.readouterr().out
    assert case.recovery_output in output
    assert result == (1 if case.row == "C6" else 0)
    assert _stamps(published, previous, new_file) == case.rollback_result
    if case.row == "C6":
        assert "no-previous" in output


@pytest.mark.parametrize("case", CASES, ids=lambda case: f"{case.row}-{case.step}")
def test_crash_rows_recover_through_a_fresh_publish_without_losing_versions(
    tmp_path: Path,
    landing_root: Path,
    capsys: pytest.CaptureFixture[str],
    case: CrashCase,
) -> None:
    """C4-C7: after stale-lock cleanup, a new publish finishes the row's recovery."""
    project, published, previous, new_file = _crash_and_clear_lock(
        tmp_path, landing_root, capsys, case
    )

    result = main(
        ["--data-set", "rehearsal"],
        run_id="fresh-publish",
        build=standin("rehearsal", version=case.publish_result[0]),
        project_dir=project,
    )
    assert result == 0
    output = capsys.readouterr().out
    assert case.recovery_output in output
    assert _stamps(published, previous, new_file) == (
        case.publish_result[0],
        case.publish_result[1],
        None,
    )
