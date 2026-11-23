"""Publish hand-step and early-crash recovery tests."""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable
from functools import partial
from pathlib import Path

import pytest

from openrct2_analytics.ingest.publish import main, publish
from openrct2_analytics.ingest.publish_errors import PublishFailed
from openrct2_analytics.ingest.publish_rollback import rollback
from tests.publish_standin import (
    CRASH_EXIT_CODE,
    read_stamp,
    start_crashing_process,
)
from tests.test_publish import land_sample, standin

WAIT_SECONDS = 30


def _published(project: Path) -> Path:
    return project / "warehouse" / "rehearsal.duckdb"


def _previous(project: Path) -> Path:
    return project / "warehouse" / "previous" / "rehearsal.duckdb"


def _new(project: Path) -> Path:
    return _previous(project).with_name("rehearsal.duckdb.new")


def _stamps(project: Path) -> tuple[str | None, str | None, str | None]:
    published, previous, new_file = (_published(project), _previous(project), _new(project))
    return (
        read_stamp(published) if published.exists() else None,
        read_stamp(previous) if previous.exists() else None,
        read_stamp(new_file) if new_file.exists() else None,
    )


def _files(project: Path) -> tuple[str, ...]:
    return tuple(sorted(path.relative_to(project).as_posix() for path in project.rglob("*")))


def _prepare_rotation_leftover(project: Path, landing_root: Path) -> None:
    land_sample(landing_root, "rehearsal")
    publish(
        "rehearsal",
        run_id="first-publish",
        build=standin("rehearsal", version="first"),
        project_dir=project,
    )
    publish(
        "rehearsal",
        run_id="second-publish",
        build=standin("rehearsal", version="second"),
        project_dir=project,
    )
    os.link(_previous(project), _new(project))
    _published(project).unlink()


def _publish_child(
    project: Path, run_id: str, version: str, on_step: Callable[[str], None]
) -> None:
    """Run publish in a child so the stand-in build is created after spawn."""
    publish(
        "rehearsal",
        run_id=run_id,
        build=standin("rehearsal", version=version),
        on_step=on_step,
        project_dir=project,
    )


@pytest.mark.usefixtures("landing_root")
def test_publish_rotation_leftover_prints_hand_step_without_changing_files(
    tmp_path: Path, landing_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A19: publish refuses a hand-created leftover without altering any file."""
    project = tmp_path / "publish-leftover"
    project.mkdir()
    _prepare_rotation_leftover(project, landing_root)
    before_stamps = _stamps(project)
    before_files = _files(project)

    result = main(
        ["--data-set", "rehearsal"],
        run_id="leftover-publish",
        build=standin("rehearsal", version="third"),
        project_dir=project,
    )

    output = capsys.readouterr().out
    assert result == 1
    assert "rotation-leftover" in output
    assert f"mv warehouse/previous/{_new(project).name} warehouse/rehearsal.duckdb" in output
    assert _stamps(project) == before_stamps
    assert _files(project) == before_files


@pytest.mark.usefixtures("landing_root")
def test_rollback_rotation_leftover_prints_hand_step_without_changing_files(
    tmp_path: Path, landing_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A19: rollback refuses a hand-created leftover without altering any file."""
    project = tmp_path / "rollback-leftover"
    project.mkdir()
    _prepare_rotation_leftover(project, landing_root)
    before_stamps = _stamps(project)
    before_files = _files(project)

    with pytest.raises(PublishFailed) as refused:
        rollback("rehearsal", project_dir=project)
    assert refused.value.reason == "rotation-leftover"
    assert _stamps(project) == before_stamps
    assert _files(project) == before_files

    result = main(["--data-set", "rehearsal", "--rollback"], project_dir=project)

    output = capsys.readouterr().out
    assert result == 1
    assert "rotation-leftover" in output
    assert f"mv warehouse/previous/{_new(project).name} warehouse/rehearsal.duckdb" in output
    assert _stamps(project) == before_stamps
    assert _files(project) == before_files


@pytest.mark.usefixtures("landing_root")
def test_candidate_created_crash_clears_stale_lock_and_run_folder(
    tmp_path: Path, landing_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """C1: stale-lock hand steps remove the lock and empty run folder before retry."""
    land_sample(landing_root, "rehearsal")
    project = tmp_path / "candidate-created-crash"
    project.mkdir()
    run_id = "crashed-candidate"
    process = start_crashing_process(
        "candidate-created",
        partial(_publish_child, project, run_id, "crashed"),
    )
    process.join(timeout=WAIT_SECONDS)
    if process.is_alive():
        process.terminate()
        process.join()
        pytest.fail("child did not stop at candidate-created")
    assert process.exitcode == CRASH_EXIT_CODE

    lock = project / "warehouse" / "rehearsal.lock"
    run_folder = project / "warehouse" / "candidate" / f"run-{run_id}"
    assert lock.is_file()
    assert lock.read_text(encoding="utf-8").startswith(f"{run_id} ")
    assert run_folder.is_dir()
    assert list(run_folder.iterdir()) == []

    lock.unlink()
    shutil.rmtree(run_folder)
    assert not lock.exists()
    assert not run_folder.exists()

    result = main(
        ["--data-set", "rehearsal"],
        run_id="retry-after-cleanup",
        build=standin("rehearsal", version="recovered"),
        project_dir=project,
    )

    assert result == 0
    assert read_stamp(_published(project)) == "recovered"
    assert not lock.exists()
    assert capsys.readouterr().out.startswith("no interrupted rotation:")
