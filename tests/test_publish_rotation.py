"""Publish rotation, recovery and rollback tests using stamped DuckDB files."""

from __future__ import annotations

import os
from collections.abc import Callable
from functools import partial
from pathlib import Path

import duckdb
import pytest

from openrct2_analytics.ingest.publish_errors import PublishFailed, exit_code
from openrct2_analytics.ingest.publish_rotation import (
    check_wal,
    finish_rotation,
    make_read_only,
    rollback_rename,
    rotate,
)
from tests.publish_standin import read_stamp, start_crashing_process, write_stamped

StepObserver = Callable[[str], None]


def _paths(root: Path) -> tuple[Path, Path, Path, Path]:
    warehouse = root / "warehouse"
    previous_dir = warehouse / "previous"
    previous_dir.mkdir(parents=True, exist_ok=True)
    published_file = warehouse / "rehearsal.duckdb"
    previous_file = previous_dir / "rehearsal.duckdb"
    candidate_file = root / "candidate.duckdb"
    new_file = previous_dir / "rehearsal.duckdb.new"
    return candidate_file, published_file, previous_file, new_file


def _optional_stamp(file: Path) -> str | None:
    return read_stamp(file) if file.exists() else None


def _stamps(*files: Path) -> tuple[str | None, ...]:
    return tuple(_optional_stamp(file) for file in files)


def _crash_rotate(
    candidate_file: Path,
    published_file: Path,
    previous_file: Path,
    on_step: StepObserver,
) -> None:
    rotate(candidate_file, published_file, previous_file, on_step)


def test_versions_rotate_and_rollback_one_step(tmp_path: Path) -> None:
    candidate, published, previous, _ = _paths(tmp_path)
    steps: list[str] = []
    write_stamped(candidate, "1")
    rotate(candidate, published, previous, steps.append)
    assert steps == ["renamed"]
    assert read_stamp(published) == "1"

    write_stamped(candidate, "2")
    steps.clear()
    rotate(candidate, published, previous, steps.append)
    assert steps == ["previous-linked", "renamed", "previous-rotated"]
    assert _stamps(published, previous) == ("2", "1")

    write_stamped(candidate, "3")
    steps.clear()
    rotate(candidate, published, previous, steps.append)
    assert steps == ["previous-linked", "renamed", "previous-rotated"]
    assert _stamps(published, previous) == ("3", "2")

    steps.clear()
    rollback_rename(published, previous, steps.append)
    assert steps == ["wal-checked"]
    assert _stamps(published, previous) == ("2", None)


def test_link_failure_leaves_every_version_in_place(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate, published, previous, new_file = _paths(tmp_path)
    write_stamped(candidate, "3")
    write_stamped(published, "2")
    write_stamped(previous, "1")
    before = _stamps(published, previous, new_file, candidate)

    def fail_link(source: Path, destination: Path) -> None:
        raise OSError("injected link failure")

    monkeypatch.setattr(os, "link", fail_link)
    with pytest.raises(PublishFailed, match="injected link failure") as failure:
        rotate(candidate, published, previous, lambda _: None)

    assert failure.value.reason == "rotation"
    assert _stamps(published, previous, new_file, candidate) == before


def test_link_failure_through_unwritable_previous_folder(tmp_path: Path) -> None:
    candidate, published, previous, new_file = _paths(tmp_path)
    write_stamped(candidate, "3")
    write_stamped(published, "2")
    write_stamped(previous, "1")
    before = _stamps(published, previous, new_file, candidate)
    previous.parent.chmod(0o555)
    try:
        with pytest.raises(PublishFailed):
            rotate(candidate, published, previous, lambda _: None)
        assert _stamps(published, previous, new_file, candidate) == before
    finally:
        previous.parent.chmod(0o755)


def test_candidate_replace_failure_keeps_published_and_rollback_versions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate, published, previous, new_file = _paths(tmp_path)
    write_stamped(candidate, "3")
    write_stamped(published, "2")
    write_stamped(previous, "1")
    replace = os.replace

    def fail_candidate(source: Path, destination: Path) -> None:
        if source == candidate:
            raise OSError("injected candidate rename failure")
        replace(source, destination)

    monkeypatch.setattr(os, "replace", fail_candidate)
    with pytest.raises(PublishFailed, match="injected candidate rename failure") as failure:
        rotate(candidate, published, previous, lambda _: None)

    assert failure.value.reason == "rotation"
    assert _stamps(published, previous, new_file, candidate) == ("2", "1", "2", "3")


def test_last_replace_failure_keeps_candidate_previous_and_new_versions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate, published, previous, new_file = _paths(tmp_path)
    write_stamped(candidate, "3")
    write_stamped(published, "2")
    write_stamped(previous, "1")
    replace = os.replace

    def fail_new_file(source: Path, destination: Path) -> None:
        if source == new_file:
            raise OSError("injected previous rotation failure")
        replace(source, destination)

    monkeypatch.setattr(os, "replace", fail_new_file)
    with pytest.raises(PublishFailed, match="injected previous rotation failure") as failure:
        rotate(candidate, published, previous, lambda _: None)

    assert failure.value.reason == "rotation"
    assert _stamps(published, previous, new_file) == ("3", "1", "2")
    assert not candidate.exists()


def test_make_read_only_sets_mode_and_denies_a_write_open(tmp_path: Path) -> None:
    file = tmp_path / "published.duckdb"
    write_stamped(file, "1")

    make_read_only(file)

    assert file.stat().st_mode & 0o777 == 0o444
    with pytest.raises(duckdb.IOException):
        connection = duckdb.connect(str(file))
        connection.close()
    assert read_stamp(file) == "1"


def test_make_read_only_translates_chmod_oserror(tmp_path: Path) -> None:
    file = tmp_path / "missing.duckdb"
    assert not file.exists()

    with pytest.raises(PublishFailed) as failure:
        make_read_only(file)

    assert failure.value.reason == "rotation"
    assert str(file) in failure.value.detail
    assert isinstance(failure.value.__cause__, OSError)


def test_check_wal_refuses_candidate_or_published_logs(tmp_path: Path) -> None:
    candidate, published, _, _ = _paths(tmp_path)
    write_stamped(candidate, "candidate")
    write_stamped(published, "published")

    wal_files = (
        candidate.with_name(f"{candidate.name}.wal"),
        published.with_name(f"{published.name}.wal"),
    )
    for wal_file in wal_files:
        wal_file.write_text("pending", encoding="utf-8")
        steps: list[str] = []
        with pytest.raises(PublishFailed, match="write-ahead log") as refusal:
            check_wal(candidate, published, steps.append)
        assert refusal.value.reason == "wal"
        assert steps == []
        wal_file.unlink()

    steps = []
    check_wal(candidate, published, steps.append)
    assert steps == ["wal-checked"]


def test_finish_rotation_removes_new_when_it_is_the_published_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, published, _, new_file = _paths(tmp_path)
    write_stamped(published, "2")
    os.link(published, new_file)

    finish_rotation(published.parent, "rehearsal")

    assert not new_file.exists()
    assert read_stamp(published) == "2"
    assert "same file" in capsys.readouterr().out


def test_finish_rotation_moves_different_new_file_to_previous(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, published, previous, new_file = _paths(tmp_path)
    write_stamped(published, "3")
    write_stamped(previous, "1")
    write_stamped(new_file, "2")

    finish_rotation(published.parent, "rehearsal")

    assert _stamps(published, previous, new_file) == ("3", "2", None)
    assert "moved" in capsys.readouterr().out


def test_finish_rotation_without_new_file_reports_no_interrupted_rotation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, published, _, new_file = _paths(tmp_path)
    write_stamped(published, "3")

    finish_rotation(published.parent, "rehearsal")

    assert _stamps(published, new_file) == ("3", None)
    assert "no interrupted rotation" in capsys.readouterr().out


def test_finish_rotation_translates_unreadable_previous_folder(
    tmp_path: Path,
) -> None:
    _, _, previous, _ = _paths(tmp_path)
    previous.parent.chmod(0o000)
    try:
        assert not os.access(previous.parent, os.R_OK)
        with pytest.raises(PublishFailed) as failure:
            finish_rotation(previous.parent.parent, "rehearsal")
        assert failure.value.reason == "rotation"
    finally:
        previous.parent.chmod(0o755)


def test_finish_rotation_translates_unlink_failure_in_previous_folder(
    tmp_path: Path,
) -> None:
    _, published, _, new_file = _paths(tmp_path)
    write_stamped(published, "2")
    os.link(published, new_file)
    new_file.parent.chmod(0o555)
    try:
        assert not os.access(new_file.parent, os.W_OK)
        with pytest.raises(PublishFailed) as failure:
            finish_rotation(published.parent, "rehearsal")
        assert failure.value.reason == "rotation"
    finally:
        new_file.parent.chmod(0o755)


def test_finish_rotation_translates_samefile_oserror(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, published, _, new_file = _paths(tmp_path)
    write_stamped(published, "2")
    os.link(published, new_file)

    def fail_samefile(first: str | os.PathLike[str], second: str | os.PathLike[str]) -> bool:
        raise PermissionError("injected samefile failure")

    monkeypatch.setattr(os.path, "samefile", fail_samefile)
    with pytest.raises(PublishFailed, match="injected samefile failure") as failure:
        finish_rotation(published.parent, "rehearsal")

    assert failure.value.reason == "rotation"


def test_rotation_leftover_refusal_names_paths_and_mv_without_changing_files(
    tmp_path: Path,
) -> None:
    _, published, previous, new_file = _paths(tmp_path)
    write_stamped(previous, "1")
    write_stamped(new_file, "2")
    before = _stamps(published, previous, new_file)

    with pytest.raises(PublishFailed) as refusal:
        finish_rotation(published.parent, "rehearsal")

    assert refusal.value.reason == "rotation-leftover"
    assert exit_code(refusal.value) == 1
    assert str(new_file) in refusal.value.detail
    assert str(published) in refusal.value.detail
    assert "mv warehouse/previous/rehearsal.duckdb.new warehouse/rehearsal.duckdb" in (
        refusal.value.detail
    )
    assert _stamps(published, previous, new_file) == before


def test_no_previous_refusal_happens_before_wal_check(tmp_path: Path) -> None:
    published = tmp_path / "rehearsal.duckdb"
    previous = tmp_path / "previous.duckdb"
    write_stamped(published, "1")
    steps: list[str] = []

    with pytest.raises(PublishFailed) as refusal:
        rollback_rename(published, previous, steps.append)

    assert refusal.value.reason == "no-previous"
    assert steps == []


@pytest.mark.parametrize("crash_step", ["previous-linked", "renamed", "previous-rotated"])
def test_later_publish_crashes_recover_and_rollback_without_losing_current_versions(
    tmp_path: Path, crash_step: str
) -> None:
    candidate, published, previous, new_file = _paths(tmp_path)
    write_stamped(candidate, "3")
    write_stamped(published, "2")
    write_stamped(previous, "1")
    process = start_crashing_process(
        crash_step,
        partial(_crash_rotate, candidate, published, previous),
    )
    process.join(timeout=20)
    if process.is_alive():
        process.terminate()
        process.join()
        pytest.fail(f"child did not stop at {crash_step}")
    assert process.exitcode == 86

    before_recovery = _stamps(published, previous, new_file, candidate)
    if crash_step == "previous-linked":
        assert before_recovery == ("2", "1", "2", "3")
    elif crash_step == "renamed":
        assert before_recovery == ("3", "1", "2", None)
    else:
        assert before_recovery == ("3", "2", None, None)

    finish_rotation(published.parent, "rehearsal")
    if crash_step == "previous-linked":
        assert _stamps(published, previous, new_file) == ("2", "1", None)
    else:
        assert _stamps(published, previous, new_file) == ("3", "2", None)
    rollback_rename(published, previous, lambda _: None)
    expected_published = "1" if crash_step == "previous-linked" else "2"
    assert _stamps(published, previous, new_file) == (expected_published, None, None)


def test_first_publish_crash_recovers_without_creating_a_previous_file(tmp_path: Path) -> None:
    candidate, published, previous, new_file = _paths(tmp_path)
    write_stamped(candidate, "1")
    process = start_crashing_process(
        "renamed",
        partial(_crash_rotate, candidate, published, previous),
    )
    process.join(timeout=20)
    if process.is_alive():
        process.terminate()
        process.join()
        pytest.fail("child did not stop after the first publish rename")
    assert process.exitcode == 86
    assert _stamps(published, previous, new_file, candidate) == ("1", None, None, None)

    finish_rotation(published.parent, "rehearsal")
    with pytest.raises(PublishFailed, match="rollback file does not exist") as refusal:
        rollback_rename(published, previous, lambda _: None)
    assert refusal.value.reason == "no-previous"
    assert _stamps(published, previous, new_file) == ("1", None, None)
