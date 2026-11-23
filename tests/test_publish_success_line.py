"""The success line of ``make publish``: what it counts, what precedes it, how it fails."""

from __future__ import annotations

import os
from pathlib import Path

import duckdb
import pytest

from openrct2_analytics.ingest import publish as publish_module
from openrct2_analytics.ingest.publish import main
from openrct2_analytics.ingest.publish_errors import PublishFailed
from tests.publish_standin import write_stamped
from tests.test_publish import land_sample, project_for, published_file, standin

pytestmark = pytest.mark.usefixtures("landing_root")


def test_success_line_counts_tables_in_every_model_schema_but_not_test_storage(
    tmp_path: Path, landing_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    land_sample(landing_root, "rehearsal")
    project = project_for(tmp_path)
    inner = standin("rehearsal")

    def build(candidate_dir: Path, candidate_file: Path, snapshot_dir: Path) -> None:
        inner(candidate_dir, candidate_file, snapshot_dir)
        connection = duckdb.connect(str(candidate_file))
        try:
            for schema in ("staging", "marts", "dbt_test__audit"):
                connection.execute(f"CREATE SCHEMA {schema}")
                connection.execute(f"CREATE TABLE {schema}.t (x INTEGER)")
                connection.execute(f"INSERT INTO {schema}.t VALUES (1), (2)")
        finally:
            connection.close()

    assert main(["--data-set", "rehearsal"], build=build, project_dir=project) == 0

    # Three main tables with one row each, plus staging.t and marts.t with two rows each.
    assert capsys.readouterr().out.splitlines()[-1] == (
        "published warehouse/rehearsal.duckdb: 5 tables, 7 rows; no earlier file kept"
    )


def test_recovery_notice_precedes_the_success_line(
    tmp_path: Path, landing_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    land_sample(landing_root, "rehearsal")
    project = project_for(tmp_path)
    published = published_file(project)
    write_stamped(published, "before")
    leftover = project / "warehouse" / "previous" / "rehearsal.duckdb.new"
    leftover.parent.mkdir(parents=True)
    os.link(published, leftover)

    result = main(["--data-set", "rehearsal"], build=standin("rehearsal"), project_dir=project)

    assert result == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 2
    assert "it was the same file" in lines[0]
    assert lines[1].startswith("published warehouse/rehearsal.duckdb: ")


def test_success_line_names_the_kept_rollback_file_and_both_files_exist(
    tmp_path: Path, landing_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    land_sample(landing_root, "rehearsal")
    project = project_for(tmp_path)
    write_stamped(published_file(project), "before")

    result = main(["--data-set", "rehearsal"], build=standin("rehearsal"), project_dir=project)

    assert result == 0
    assert capsys.readouterr().out.splitlines()[-1] == (
        "published warehouse/rehearsal.duckdb: 3 tables, 3 rows; "
        "kept warehouse/previous/rehearsal.duckdb for one rollback"
    )
    assert published_file(project).is_file()
    assert (project / "warehouse" / "previous" / "rehearsal.duckdb").is_file()


def test_count_failure_publishes_nothing_and_keeps_old_files(
    tmp_path: Path,
    landing_root: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    land_sample(landing_root, "rehearsal")
    project = project_for(tmp_path)
    published = published_file(project)
    previous = project / "warehouse" / "previous" / "rehearsal.duckdb"
    write_stamped(published, "published")
    previous.parent.mkdir(parents=True, exist_ok=True)
    write_stamped(previous, "rollback")
    published_before = published.read_bytes()
    previous_before = previous.read_bytes()

    def fail_count(*_: object) -> tuple[int, int]:
        raise PublishFailed("candidate-count", "cannot read")

    monkeypatch.setattr(publish_module, "_candidate_counts", fail_count)

    result = main(["--data-set", "rehearsal"], build=standin("rehearsal"), project_dir=project)

    assert result == 1
    assert capsys.readouterr().out.splitlines()[-1] == (
        "publish failed: candidate-count: cannot read"
    )
    assert published.read_bytes() == published_before
    assert previous.read_bytes() == previous_before
    assert sorted(path.name for path in previous.parent.iterdir()) == ["rehearsal.duckdb"]


def test_counts_and_kept_flag_are_read_while_the_publish_lock_is_held(
    tmp_path: Path, landing_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    land_sample(landing_root, "rehearsal")
    project = project_for(tmp_path)
    lock = project / "warehouse" / "rehearsal.lock"
    real_counts = publish_module._candidate_counts
    lock_held: list[bool] = []

    def counts_under_lock(candidate_file: Path, project_dir: Path) -> tuple[int, int]:
        lock_held.append(lock.exists())
        return real_counts(candidate_file, project_dir)

    monkeypatch.setattr(publish_module, "_candidate_counts", counts_under_lock)

    assert main(["--data-set", "rehearsal"], build=standin("rehearsal"), project_dir=project) == 0

    assert lock_held == [True]
    assert not lock.exists()
