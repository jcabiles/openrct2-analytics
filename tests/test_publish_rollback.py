"""Rollback the published warehouse using real files and rotation helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from openrct2_analytics.ingest.publish import _check_data_set, main
from openrct2_analytics.ingest.publish_errors import PublishFailed, PublishRefused
from openrct2_analytics.ingest.publish_prepare import take_lock
from openrct2_analytics.ingest.publish_rollback import rollback
from openrct2_analytics.ingest.publish_rotation import rotate
from tests.publish_standin import read_stamp, write_stamped


def test_rollback_restores_previous_version_without_losing_it(tmp_path: Path) -> None:
    warehouse = tmp_path / "warehouse"
    published = warehouse / "rehearsal.duckdb"
    previous = warehouse / "previous" / "rehearsal.duckdb"
    candidate = tmp_path / "candidate.duckdb"
    write_stamped(published, "version-1")
    write_stamped(candidate, "version-2")
    with take_lock(tmp_path, "rehearsal", "publish-2", lambda _: None):
        rotate(candidate, published, previous, lambda _: None)

    rollback("rehearsal", project_dir=tmp_path)

    assert read_stamp(published) == "version-1"
    assert not previous.exists()
    assert not (warehouse / "rehearsal.lock").exists()


def test_guard_refusal_creates_no_folder_or_lock(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    warehouse = project / "warehouse"
    (warehouse / "previous").mkdir(parents=True)
    target = tmp_path / "target"
    target.write_text("outside", encoding="utf-8")
    published = warehouse / "rehearsal.duckdb"
    published.symlink_to(target)
    steps: list[str] = []

    with pytest.raises(PublishRefused) as refused:
        rollback("rehearsal", on_step=steps.append, project_dir=project)

    assert refused.value.reason == "unsafe-path"
    assert steps == []
    assert target.read_text(encoding="utf-8") == "outside"
    assert published.is_symlink()
    assert not (warehouse / "candidate").exists()
    assert not (warehouse / "rehearsal.lock").exists()


def test_regular_file_warehouse_is_reported_as_prepare_failure(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    warehouse = project / "warehouse"
    warehouse.write_text("not a directory", encoding="utf-8")

    assert warehouse.is_file()

    with pytest.raises(PublishFailed) as failed:
        rollback("rehearsal", project_dir=project)

    assert failed.value.reason == "prepare"


def test_held_lock_refusal_names_the_lock_file(tmp_path: Path) -> None:
    warehouse = tmp_path / "warehouse"
    (warehouse / "previous").mkdir(parents=True)
    published = warehouse / "rehearsal.duckdb"
    previous = warehouse / "previous" / "rehearsal.duckdb"
    write_stamped(published, "version-2")
    write_stamped(previous, "version-1")
    lock = warehouse / "rehearsal.lock"
    line = "other-run 456 2026-10-07T12:30:00+00:00"
    lock.write_text(line + "\n", encoding="utf-8")

    with pytest.raises(PublishRefused) as refused:
        rollback("rehearsal", project_dir=tmp_path)

    assert refused.value.reason == "lock-taken"
    assert str(lock) in refused.value.detail
    assert line in refused.value.detail
    assert lock.read_text(encoding="utf-8") == line + "\n"


def test_interrupted_rotation_finishes_before_rollback_rename(tmp_path: Path) -> None:
    warehouse = tmp_path / "warehouse"
    published = warehouse / "rehearsal.duckdb"
    previous = warehouse / "previous" / "rehearsal.duckdb"
    new_previous = previous.with_name(f"{previous.name}.new")
    write_stamped(published, "version-4")
    write_stamped(previous, "version-2")
    write_stamped(new_previous, "version-3")

    rollback("rehearsal", project_dir=tmp_path)

    assert read_stamp(published) == "version-3"
    assert not previous.exists()
    assert not new_previous.exists()


def test_lock_is_released_after_rollback_failure(tmp_path: Path) -> None:
    warehouse = tmp_path / "warehouse"
    published = warehouse / "rehearsal.duckdb"
    previous = warehouse / "previous" / "rehearsal.duckdb"
    write_stamped(published, "version-2")
    write_stamped(previous, "version-1")
    previous.with_name(f"{previous.name}.wal").write_text("wal", encoding="utf-8")

    with pytest.raises(PublishFailed) as refused:
        rollback("rehearsal", project_dir=tmp_path)

    assert refused.value.reason == "wal"
    assert not (warehouse / "rehearsal.lock").exists()


def test_lock_is_released_after_success(tmp_path: Path) -> None:
    warehouse = tmp_path / "warehouse"
    published = warehouse / "rehearsal.duckdb"
    previous = warehouse / "previous" / "rehearsal.duckdb"
    write_stamped(published, "version-2")
    write_stamped(previous, "version-1")

    rollback("rehearsal", project_dir=tmp_path)

    assert not (warehouse / "rehearsal.lock").exists()


def test_missing_previous_file_is_refused_by_rotation_helper(tmp_path: Path) -> None:
    warehouse = tmp_path / "warehouse"
    write_stamped(warehouse / "rehearsal.duckdb", "version-1")

    with pytest.raises(PublishFailed) as refused:
        rollback("rehearsal", project_dir=tmp_path)

    assert refused.value.reason == "no-previous"
    assert not (warehouse / "rehearsal.lock").exists()


def test_main_refuses_invalid_data_set_before_rollback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    warehouse = tmp_path / "warehouse"
    published = warehouse / "rehearsal.duckdb"
    previous = warehouse / "previous" / "rehearsal.duckdb"
    write_stamped(published, "current")
    write_stamped(previous, "previous")
    monkeypatch.setenv("OPENRCT2_DATA_DIR", "")
    before = {
        path.relative_to(warehouse): path.read_bytes()
        for path in warehouse.rglob("*")
        if path.is_file()
    }

    with pytest.raises(PublishRefused) as refused:
        _check_data_set("rehearsal")

    assert type(refused.value) is PublishRefused
    assert refused.value.reason == "data-set"
    assert refused.value.detail == "Environment variable OPENRCT2_DATA_DIR must not be empty"

    result = main(["--data-set", "rehearsal", "--rollback"], project_dir=tmp_path)

    assert result == 2
    assert capsys.readouterr().out == (
        "publish refused: data-set: Environment variable OPENRCT2_DATA_DIR must not be empty\n"
    )
    after = {
        path.relative_to(warehouse): path.read_bytes()
        for path in warehouse.rglob("*")
        if path.is_file()
    }
    assert after == before


def test_main_rollback_ignores_aliased_registry_folder(
    tmp_path: Path,
    landing_root: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rehearsal = landing_root / "rehearsal"
    company = landing_root / "company"
    for data_set in (rehearsal, company):
        (data_set / "raw").mkdir(parents=True)
        (data_set / "parquet").mkdir()
    (rehearsal / "registry" / "v1").mkdir(parents=True)
    (company / "registry").symlink_to("../rehearsal/registry", target_is_directory=True)

    result = main(["--rollback", "--data-set", "rehearsal"], project_dir=tmp_path)

    assert result == 1
    output = capsys.readouterr().out
    assert "publish failed: no-previous: rollback file does not exist: " in output
