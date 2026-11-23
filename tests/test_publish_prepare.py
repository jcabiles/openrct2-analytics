"""The publish lock and candidate-folder preparation on real temporary paths."""

from __future__ import annotations

import errno
import os
import shutil
from pathlib import Path

import pytest

from openrct2_analytics.ingest.publish_errors import PublishFailed, PublishRefused
from openrct2_analytics.ingest.publish_prepare import (
    check_run_id,
    create_candidate,
    guard_path,
    take_lock,
)


@pytest.mark.parametrize("run_id", ["../", "/", ""])
def test_invalid_run_ids_refuse_before_creating_a_folder_or_lock(
    tmp_path: Path, run_id: str
) -> None:
    steps: list[str] = []

    with (
        pytest.raises(PublishRefused) as refused,
        take_lock(tmp_path, "rehearsal", run_id, steps.append),
    ):
        pytest.fail("an invalid run ID must be refused")

    assert refused.value.reason == "invalid-run-id"
    assert not (tmp_path / "warehouse").exists()
    assert steps == []


@pytest.mark.parametrize("name", ["", ".", "..", "a/b", "../x"])
def test_invalid_lock_names_refuse_without_creating_files(tmp_path: Path, name: str) -> None:
    warehouse = tmp_path / "warehouse"
    warehouse.mkdir()

    with (
        pytest.raises(PublishRefused) as refused,
        take_lock(tmp_path, name, "safe", lambda _: None),
    ):
        pytest.fail("an invalid lock name must be refused")

    assert refused.value.reason == "unsafe-path"
    assert list(warehouse.iterdir()) == []


@pytest.mark.parametrize("name", ["rehearsal", "company"])
def test_linked_warehouse_is_refused_before_any_step_or_creation(tmp_path: Path, name: str) -> None:
    project = tmp_path / "project"
    project.mkdir()
    target = tmp_path / "target"
    target.mkdir()
    (project / "warehouse").symlink_to(target, target_is_directory=True)
    steps: list[str] = []

    with pytest.raises(PublishRefused) as refused, take_lock(project, name, "safe", steps.append):
        pytest.fail("the linked warehouse must be refused")

    assert refused.value.reason == "unsafe-path"
    assert steps == []
    assert (project / "warehouse").is_symlink()
    assert list(target.iterdir()) == []
    assert not (target / f"{name}.lock").exists()
    assert not (target / "candidate").exists()
    assert not list(target.glob("*.duckdb"))


def test_regular_file_warehouse_is_reported_as_prepare_failure(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    warehouse = project / "warehouse"
    warehouse.write_text("not a directory", encoding="utf-8")

    assert warehouse.is_file()

    with (
        pytest.raises(PublishFailed) as failed,
        take_lock(project, "rehearsal", "safe", lambda _: None),
    ):
        pytest.fail("a regular file warehouse must fail during prepare")

    assert failed.value.reason == "prepare"
    assert str(warehouse / "candidate" / "run-safe") in failed.value.detail


def test_unreadable_warehouse_is_reported_as_prepare_failure(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    warehouse = project / "warehouse"
    warehouse.mkdir()
    original_mode = warehouse.stat().st_mode & 0o777
    warehouse.chmod(0o000)
    try:
        assert warehouse.stat().st_mode & 0o777 == 0

        with (
            pytest.raises(PublishFailed) as failed,
            take_lock(project, "rehearsal", "safe", lambda _: None),
        ):
            pytest.fail("an unreadable warehouse must fail during prepare")

        assert failed.value.reason == "prepare"
        assert str(warehouse / "candidate" / "run-safe") in failed.value.detail
    finally:
        warehouse.chmod(original_mode)


def test_linked_candidate_is_refused_and_its_link_and_target_are_untouched(
    tmp_path: Path,
) -> None:
    target = tmp_path / "empty-target"
    target.mkdir()
    steps: list[str] = []

    with take_lock(tmp_path, "rehearsal", "safe", steps.append):
        candidate = tmp_path / "warehouse" / "candidate" / "run-safe"
        candidate.symlink_to(target, target_is_directory=True)
        with (
            pytest.raises(PublishRefused) as refused,
            create_candidate(tmp_path, "rehearsal", "safe", steps.append),
        ):
            pytest.fail("the linked candidate must be refused")

    assert refused.value.reason == "unsafe-path"
    assert candidate.is_symlink()
    assert list(target.iterdir()) == []
    assert not (tmp_path / "warehouse" / "rehearsal.lock").exists()
    assert steps == ["locked"]


def test_a_taken_lock_refusal_names_its_file_line_and_architecture_section(
    tmp_path: Path,
) -> None:
    warehouse = tmp_path / "warehouse"
    (warehouse / "candidate").mkdir(parents=True)
    (warehouse / "previous").mkdir()
    lock = warehouse / "rehearsal.lock"
    line = "other-run 456 2026-10-07T12:30:00+00:00"
    lock.write_text(line + "\n", encoding="utf-8")

    with (
        pytest.raises(PublishRefused) as refused,
        take_lock(tmp_path, "rehearsal", "safe", lambda _: None),
    ):
        pytest.fail("the existing lock must refuse the publish")

    assert refused.value.reason == "lock-taken"
    assert str(lock) in refused.value.detail
    assert line in refused.value.detail
    assert "ARCHITECTURE.md" in refused.value.detail
    assert "Environments and publishing" in refused.value.detail
    assert lock.read_text(encoding="utf-8") == line + "\n"


def test_unwritable_warehouse_lock_entry_is_reported_as_prepare_failure(
    tmp_path: Path,
) -> None:
    warehouse = tmp_path / "warehouse"
    candidate = warehouse / "candidate"
    previous = warehouse / "previous"
    candidate.mkdir(parents=True)
    previous.mkdir()
    original_mode = warehouse.stat().st_mode & 0o777
    warehouse.chmod(0o555)
    try:
        assert candidate.is_dir()
        assert previous.is_dir()
        assert warehouse.stat().st_mode & 0o777 == 0o555

        with (
            pytest.raises(PublishFailed) as failed,
            take_lock(tmp_path, "rehearsal", "safe", lambda _: None),
        ):
            pytest.fail("an unwritable lock folder must fail during prepare")

        assert failed.value.reason == "prepare"
        assert str(warehouse / "rehearsal.lock") in failed.value.detail
    finally:
        warehouse.chmod(original_mode)


def test_lock_folder_is_reported_as_prepare_failure(tmp_path: Path) -> None:
    warehouse = tmp_path / "warehouse"
    warehouse.mkdir()
    lock = warehouse / "rehearsal.lock"
    lock.mkdir()
    assert lock.is_dir()

    with (
        pytest.raises(PublishFailed) as failed,
        take_lock(tmp_path, "rehearsal", "safe", lambda _: None),
    ):
        pytest.fail("a lock folder must fail during prepare")

    assert failed.value.reason == "prepare"
    assert str(lock) in failed.value.detail


def test_lock_unlink_error_is_reported_as_lock_cleanup_failure(tmp_path: Path) -> None:
    warehouse = tmp_path / "warehouse"
    warehouse.mkdir()
    (warehouse / "candidate").mkdir()
    (warehouse / "previous").mkdir()
    original_mode = warehouse.stat().st_mode & 0o777

    try:
        with (
            pytest.raises(PublishFailed) as failed,
            take_lock(tmp_path, "rehearsal", "safe", lambda _: None),
        ):
            warehouse.chmod(0o555)

        assert warehouse.stat().st_mode & 0o777 == 0o555
        assert failed.value.reason == "lock-cleanup"
        assert str(warehouse / "rehearsal.lock") in failed.value.detail
    finally:
        warehouse.chmod(original_mode)


def test_lock_cleanup_error_is_a_note_on_the_body_failure(tmp_path: Path) -> None:
    warehouse = tmp_path / "warehouse"
    warehouse.mkdir()
    (warehouse / "candidate").mkdir()
    (warehouse / "previous").mkdir()
    original_mode = warehouse.stat().st_mode & 0o777

    try:
        with (
            pytest.raises(PublishFailed) as failed,
            take_lock(tmp_path, "rehearsal", "safe", lambda _: None),
        ):
            warehouse.chmod(0o555)
            raise PublishFailed("views", "view creation failed")

        assert warehouse.stat().st_mode & 0o777 == 0o555
        assert failed.value.reason == "views"
        assert any("lock cleanup also failed" in note for note in failed.value.__notes__)
    finally:
        warehouse.chmod(original_mode)


def test_unwritable_candidate_parent_is_reported_as_prepare_failure(
    tmp_path: Path,
) -> None:
    warehouse = tmp_path / "warehouse"
    warehouse.mkdir()
    original_mode = warehouse.stat().st_mode & 0o777
    warehouse.chmod(0o500)
    candidate_root = warehouse / "candidate"
    lock = warehouse / "rehearsal.lock"
    try:
        assert not os.access(warehouse, os.W_OK)

        with (
            pytest.raises(PublishFailed) as failed,
            take_lock(tmp_path, "rehearsal", "safe", lambda _: None),
        ):
            pytest.fail("an unwritable candidate parent must fail")

        assert failed.value.reason == "prepare"
        assert str(candidate_root) in failed.value.detail
        assert not lock.exists()
    finally:
        warehouse.chmod(original_mode)


def test_unwritable_project_folder_is_reported_as_warehouse_prepare_failure(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    warehouse = project / "warehouse"
    original_mode = project.stat().st_mode & 0o777
    project.chmod(0o555)
    try:
        assert project.is_dir()
        assert not warehouse.exists()
        assert project.stat().st_mode & 0o777 == 0o555

        with (
            pytest.raises(PublishFailed) as failed,
            take_lock(project, "rehearsal", "safe", lambda _: None),
        ):
            pytest.fail("an unwritable project folder must fail during prepare")

        assert failed.value.reason == "prepare"
        assert failed.value.detail.startswith(f"{warehouse}:")
    finally:
        project.chmod(original_mode)


def test_previous_folder_file_is_reported_as_prepare_failure(tmp_path: Path) -> None:
    warehouse = tmp_path / "warehouse"
    warehouse.mkdir()
    previous = warehouse / "previous"
    previous.write_text("not a directory", encoding="utf-8")
    assert previous.is_file()

    with (
        pytest.raises(PublishFailed) as failed,
        take_lock(tmp_path, "rehearsal", "safe", lambda _: None),
    ):
        pytest.fail("a file at the previous folder path must fail during prepare")

    assert failed.value.reason == "prepare"
    assert failed.value.detail.startswith(f"{previous}:")


def test_unwritable_candidate_folder_is_reported_as_prepare_failure(
    tmp_path: Path,
) -> None:
    warehouse = tmp_path / "warehouse"
    candidate_root = warehouse / "candidate"
    steps: list[str] = []

    with take_lock(tmp_path, "rehearsal", "safe", steps.append):
        original_mode = candidate_root.stat().st_mode & 0o777
        candidate_root.chmod(0o555)
        candidate = candidate_root / "run-safe"
        try:
            assert candidate_root.is_dir()
            assert not candidate.exists()
            assert candidate_root.stat().st_mode & 0o777 == 0o555

            with (
                pytest.raises(PublishFailed) as failed,
                create_candidate(tmp_path, "rehearsal", "safe", steps.append),
            ):
                pytest.fail("an unwritable candidate folder must fail during prepare")

            assert failed.value.reason == "prepare"
            assert failed.value.detail.startswith(f"{candidate}:")
        finally:
            candidate_root.chmod(original_mode)

    assert steps == ["locked"]


def test_candidate_that_already_exists_is_refused_and_left_untouched(
    tmp_path: Path,
) -> None:
    with take_lock(tmp_path, "rehearsal", "safe", lambda _: None):
        candidate = tmp_path / "warehouse" / "candidate" / "run-safe"
        candidate.mkdir()
        marker = candidate / "marker"
        marker.write_text("keep", encoding="utf-8")

        with (
            pytest.raises(PublishRefused) as refused,
            create_candidate(tmp_path, "rehearsal", "safe", lambda _: None),
        ):
            pytest.fail("the existing candidate must refuse")

        assert refused.value.reason == "candidate-exists"
        assert marker.read_text(encoding="utf-8") == "keep"


def test_candidate_cleanup_removes_only_the_folder_created_by_this_run(
    tmp_path: Path,
) -> None:
    steps: list[str] = []
    with take_lock(tmp_path, "rehearsal", "safe", steps.append):
        previous_candidate = tmp_path / "warehouse" / "candidate" / "run-old"
        previous_candidate.mkdir()
        marker = previous_candidate / "marker"
        marker.write_text("keep", encoding="utf-8")

        with create_candidate(tmp_path, "rehearsal", "safe", steps.append) as candidate:
            assert candidate.is_dir()
            assert candidate.name == "run-safe"

        assert not candidate.exists()
        assert marker.read_text(encoding="utf-8") == "keep"
        assert (tmp_path / "warehouse" / "previous").is_dir()

    assert steps == ["locked", "candidate-created", "candidate-removed"]


def test_candidate_removal_error_is_added_as_a_note_to_the_body_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def removal_fails(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
    ) -> None:
        raise OSError(errno.EIO, "candidate disk error", str(path))

    monkeypatch.setattr(shutil, "rmtree", removal_fails)

    with (
        take_lock(tmp_path, "rehearsal", "safe", lambda _: None),
        pytest.raises(RuntimeError, match="body failed") as raised,
        create_candidate(tmp_path, "rehearsal", "safe", lambda _: None),
    ):
        raise RuntimeError("body failed")

    assert any("candidate disk error" in note for note in raised.value.__notes__)
    assert (tmp_path / "warehouse" / "candidate" / "run-safe").is_dir()


def test_candidate_removal_error_without_body_failure_is_translated(
    tmp_path: Path,
) -> None:
    with take_lock(tmp_path, "rehearsal", "safe", lambda _: None):
        candidate = tmp_path / "warehouse" / "candidate" / "run-safe"
        marker = candidate / "marker"
        try:
            with (
                pytest.raises(PublishFailed) as failed,
                create_candidate(tmp_path, "rehearsal", "safe", lambda _: None),
            ):
                marker.write_text("keep", encoding="utf-8")
                candidate.chmod(0o555)

            assert failed.value.reason == "candidate-cleanup"
            assert "Permission denied" in failed.value.detail
            assert "PosixPath" not in failed.value.detail
            assert str(candidate) in failed.value.detail
            assert marker.read_text(encoding="utf-8") == "keep"
        finally:
            if candidate.is_dir():
                candidate.chmod(0o755)
                shutil.rmtree(candidate)


def test_check_run_id_accepts_letters_digits_and_dashes() -> None:
    check_run_id("A0-safe-99")


def test_guard_path_can_allow_published_paths_but_refuses_them_by_default(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    warehouse = project / "warehouse"
    warehouse.mkdir(parents=True)
    published = warehouse / "rehearsal.duckdb"
    published.write_bytes(b"published data")

    guard_path(
        published,
        root=warehouse,
        project_dir=project,
        allow=frozenset({"published"}),
    )

    with pytest.raises(PublishRefused) as refused:
        guard_path(published, root=warehouse, project_dir=project)

    assert refused.value.reason == "unsafe-path"
    assert "published" in refused.value.detail


def test_guard_path_does_not_allow_symlinks_when_published_is_allowed(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    warehouse = project / "warehouse"
    warehouse.mkdir(parents=True)
    target = tmp_path / "target"
    target.write_bytes(b"target data")
    linked = warehouse / "candidate.duckdb"
    linked.symlink_to(target)

    with pytest.raises(PublishRefused) as refused:
        guard_path(
            linked,
            root=warehouse,
            project_dir=project,
            allow=frozenset({"published"}),
        )

    assert refused.value.reason == "unsafe-path"
    assert "symlink" in refused.value.detail
