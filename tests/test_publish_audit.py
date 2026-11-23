"""Publish audit tests using real DuckDB files from the build stand-in."""

from __future__ import annotations

import shutil
from pathlib import Path

import duckdb
import pytest

from openrct2_analytics.ingest.publish_audit import audit_candidate, audit_seq, open_warehouse
from openrct2_analytics.ingest.publish_errors import PublishFailed, PublishRefused
from tests.publish_standin import StandinOptions, add_registry_model, build_standin, write_stamped


def _build_candidate(
    folder: Path,
    options: StandinOptions | None = None,
) -> tuple[Path, Path]:
    if options is None:
        options = StandinOptions()
    candidate_dir = folder / "candidate"
    candidate_file = candidate_dir / "warehouse.duckdb"
    snapshot_dir = folder / "snapshot"
    snapshot_dir.mkdir(parents=True)
    build_standin("company", options=options)(candidate_dir, candidate_file, snapshot_dir)
    add_registry_model(candidate_dir, "warehouse")
    return candidate_dir, candidate_file


def _audit(
    candidate_dir: Path,
    candidate_file: Path,
    *,
    project_dir: Path,
    steps: list[str] | None = None,
) -> None:
    if steps is None:
        steps = []
    audit_candidate(
        candidate_file,
        candidate_dir,
        "company",
        project_dir,
        on_step=steps.append,
    )


def _copy_sql_path(path: Path) -> str:
    return "'" + path.as_posix().replace("'", "''") + "'"


def test_missing_manifest_fails_empty_with_manifest_path(tmp_path: Path) -> None:
    candidate_dir, candidate_file = _build_candidate(tmp_path)
    manifest_path = candidate_dir / "target" / "manifest.json"
    manifest_path.unlink()

    with pytest.raises(PublishFailed) as error:
        _audit(candidate_dir, candidate_file, project_dir=tmp_path)

    assert error.value.reason == "empty"
    assert str(manifest_path) in error.value.detail


def test_invalid_json_manifest_fails_empty_with_manifest_path(tmp_path: Path) -> None:
    candidate_dir, candidate_file = _build_candidate(tmp_path)
    manifest_path = candidate_dir / "target" / "manifest.json"
    manifest_path.write_text("{invalid json", encoding="utf-8")

    with pytest.raises(PublishFailed) as error:
        _audit(candidate_dir, candidate_file, project_dir=tmp_path)

    assert error.value.reason == "empty"
    assert str(manifest_path) in error.value.detail


def test_unreadable_landing_folder_fails_sequence_audit(tmp_path: Path) -> None:
    landing_dir = tmp_path / "landing"
    event_dir = landing_dir / "v1"
    event_dir.mkdir(parents=True)
    original_mode = event_dir.stat().st_mode & 0o777
    event_dir.chmod(0o000)
    try:
        with pytest.raises(PublishFailed) as error:
            audit_seq(landing_dir)
    finally:
        event_dir.chmod(original_mode)

    assert error.value.reason == "seq-audit"
    assert str(event_dir) in error.value.detail
    assert "holds no event files" not in error.value.detail


def test_unreadable_landing_parquet_file_fails_sequence_audit(tmp_path: Path) -> None:
    source_file = tmp_path / "source.parquet"
    source_connection = duckdb.connect(":memory:")
    try:
        source_connection.execute(
            "CREATE TABLE events (park_id VARCHAR, session_id VARCHAR, seq BIGINT)"
        )
        source_connection.execute(f"COPY events TO {_copy_sql_path(source_file)} (FORMAT PARQUET)")
    finally:
        source_connection.close()

    event_dir = tmp_path / "landing" / "v1"
    event_dir.mkdir(parents=True)
    unreadable_file = event_dir / "events.parquet"
    shutil.copy2(source_file, unreadable_file)
    original_mode = unreadable_file.stat().st_mode & 0o777
    unreadable_file.chmod(0o000)
    try:
        assert unreadable_file.stat().st_mode & 0o777 == 0o000
        with pytest.raises(PublishFailed) as error:
            audit_seq(event_dir.parent)
    finally:
        unreadable_file.chmod(original_mode)

    assert error.value.reason == "seq-audit"


def test_invalid_landing_parquet_file_fails_sequence_audit(tmp_path: Path) -> None:
    event_dir = tmp_path / "landing" / "v1"
    event_dir.mkdir(parents=True)
    invalid_file = event_dir / "events.parquet"
    invalid_contents = b"not a parquet file"
    invalid_file.write_bytes(invalid_contents)
    assert invalid_file.read_bytes() == invalid_contents

    with pytest.raises(PublishFailed) as error:
        audit_seq(event_dir.parent)

    assert error.value.reason == "seq-audit"


def test_open_warehouse_refuses_write_mode_for_published_and_previous_paths(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "project"
    published = project_dir / "warehouse" / "company.duckdb"
    previous = project_dir / "warehouse" / "previous" / "company.duckdb"
    write_stamped(published, "published")
    write_stamped(previous, "previous")

    for path in (published, previous):
        with pytest.raises(PublishRefused, match="published"):
            open_warehouse(path, project_dir=project_dir, read_only=False)
        connection = open_warehouse(path, project_dir=project_dir)
        try:
            assert connection.execute("SELECT version FROM publish_stamp").fetchone() == (
                "published" if path == published else "previous",
            )
        finally:
            connection.close()


@pytest.mark.parametrize("seqs", [[1, 3], [1, 1]], ids=["gap", "repeat"])
def test_seq_audit_recomputes_from_events_not_a_copied_audit(
    tmp_path: Path,
    seqs: list[int],
) -> None:
    landing_dir = tmp_path / "landing"
    v1_dir = landing_dir / "v1"
    audit_dir = landing_dir / "audit"
    v1_dir.mkdir(parents=True)
    audit_dir.mkdir()
    events_file = v1_dir / "events.parquet"
    stale_audit_file = audit_dir / "seq_audit.parquet"
    connection = duckdb.connect(":memory:")
    try:
        connection.execute("CREATE TABLE events (park_id VARCHAR, session_id VARCHAR, seq BIGINT)")
        connection.executemany(
            "INSERT INTO events VALUES ('park-a', 'session-a', ?)", [(seq,) for seq in seqs]
        )
        connection.execute(f"COPY events TO {_copy_sql_path(events_file)} (FORMAT PARQUET)")
        connection.execute(
            "CREATE TABLE stale (park_id VARCHAR, session_id VARCHAR, first_seq BIGINT, "
            "last_seq BIGINT, row_count BIGINT, missing BIGINT, duplicates BIGINT, "
            "park_count BIGINT)"
        )
        connection.execute(f"COPY stale TO {_copy_sql_path(stale_audit_file)} (FORMAT PARQUET)")
    finally:
        connection.close()

    with pytest.raises(PublishFailed) as error:
        audit_seq(landing_dir)

    assert error.value.reason == "seq-audit"
    assert "session-a" in error.value.detail


def test_seq_audit_fails_when_snapshot_has_no_event_files(tmp_path: Path) -> None:
    landing_dir = tmp_path / "landing"
    v1_dir = landing_dir / "v1"
    v1_dir.mkdir(parents=True)

    with pytest.raises(PublishFailed) as error:
        audit_seq(landing_dir)

    assert error.value.reason == "seq-audit"
    assert str(v1_dir) in error.value.detail
    assert "no event files" in error.value.detail


def test_views_have_their_own_failure_reason(tmp_path: Path) -> None:
    candidate_dir, candidate_file = _build_candidate(tmp_path, StandinOptions(view=True))

    with pytest.raises(PublishFailed) as error:
        _audit(candidate_dir, candidate_file, project_dir=tmp_path)

    assert error.value.reason == "views"
    assert error.value.detail == "candidate contains view(s): main.standin_view"


def test_empty_audited_model_fails_but_empty_model_without_key_is_exempt(
    tmp_path: Path,
) -> None:
    empty_dir, empty_file = _build_candidate(
        tmp_path / "empty", StandinOptions(empty_audited_table=True)
    )
    with pytest.raises(PublishFailed) as error:
        _audit(empty_dir, empty_file, project_dir=tmp_path)
    assert error.value.reason == "empty"
    assert "fct_empty_audited" in error.value.detail
    assert "expected 1" in error.value.detail
    assert "actual 0" in error.value.detail

    exempt_dir, exempt_file = _build_candidate(
        tmp_path / "exempt", StandinOptions(empty_exempt_table=True)
    )
    steps: list[str] = []
    _audit(exempt_dir, exempt_file, project_dir=tmp_path, steps=steps)
    assert steps == ["audited"]


def test_declared_count_is_enforced_even_for_a_nonempty_model(tmp_path: Path) -> None:
    candidate_dir, candidate_file = _build_candidate(
        tmp_path, StandinOptions(undersized_audited_table=True)
    )

    with pytest.raises(PublishFailed) as error:
        _audit(candidate_dir, candidate_file, project_dir=tmp_path)

    assert error.value.reason == "empty"
    assert "fct_undersized" in error.value.detail
    assert "expected 2" in error.value.detail
    assert "actual 1" in error.value.detail


def test_ephemeral_model_with_positive_minimum_fails_empty(tmp_path: Path) -> None:
    candidate_dir, candidate_file = _build_candidate(
        tmp_path, StandinOptions(ephemeral_audited_model=True)
    )

    with pytest.raises(PublishFailed) as error:
        _audit(candidate_dir, candidate_file, project_dir=tmp_path)

    assert error.value.reason == "empty"
    assert "int_ephemeral_probe" in error.value.detail
    assert "ephemeral" in error.value.detail


@pytest.mark.parametrize("expected", [-1, 1.5, "x"])
def test_invalid_expected_minimum_fails_empty(tmp_path: Path, expected: int | float | str) -> None:
    candidate_dir, candidate_file = _build_candidate(
        tmp_path, StandinOptions(invalid_expected_min_rows=expected)
    )

    with pytest.raises(PublishFailed) as error:
        _audit(candidate_dir, candidate_file, project_dir=tmp_path)

    assert error.value.reason == "empty"
    assert "fct_invalid_minimum" in error.value.detail


def test_no_park_fails_even_when_the_manifest_has_no_keyed_models(tmp_path: Path) -> None:
    candidate_dir, candidate_file = _build_candidate(
        tmp_path,
        StandinOptions(include_keyed_model=False, empty_park_session=True),
    )

    with pytest.raises(PublishFailed) as error:
        _audit(candidate_dir, candidate_file, project_dir=tmp_path)

    assert error.value.reason == "no-park"


def test_no_park_fails_when_only_the_registry_has_a_park(tmp_path: Path) -> None:
    candidate_dir, candidate_file = _build_candidate(
        tmp_path,
        StandinOptions(
            include_keyed_model=False,
            empty_park_session=True,
            registered_park_when_empty=True,
        ),
    )

    with pytest.raises(PublishFailed) as error:
        _audit(candidate_dir, candidate_file, project_dir=tmp_path)

    assert error.value.reason == "no-park"


def test_no_session_fails_when_park_rows_exist_without_session_columns(tmp_path: Path) -> None:
    candidate_dir, candidate_file = _build_candidate(
        tmp_path,
        StandinOptions(include_keyed_model=False, table_without_session_id=True),
    )

    with pytest.raises(PublishFailed) as error:
        _audit(candidate_dir, candidate_file, project_dir=tmp_path)

    assert error.value.reason == "no-session"


def test_unregistered_park_detail_lists_the_park(tmp_path: Path) -> None:
    candidate_dir, candidate_file = _build_candidate(
        tmp_path, StandinOptions(unregistered_park=True)
    )

    with pytest.raises(PublishFailed) as error:
        _audit(candidate_dir, candidate_file, project_dir=tmp_path)

    assert error.value.reason == "unregistered-park"
    assert "park-unregistered" in error.value.detail


def test_park_registered_only_under_other_data_set_is_unregistered(tmp_path: Path) -> None:
    candidate_dir, candidate_file = _build_candidate(
        tmp_path, StandinOptions(registered_data_set="rehearsal")
    )

    with pytest.raises(PublishFailed) as error:
        _audit(candidate_dir, candidate_file, project_dir=tmp_path)

    assert error.value.reason == "unregistered-park"


def test_model_in_non_main_schema_is_audited_through_relation_name(tmp_path: Path) -> None:
    candidate_dir, candidate_file = _build_candidate(
        tmp_path, StandinOptions(non_main_schema_model=True)
    )
    steps: list[str] = []

    _audit(candidate_dir, candidate_file, project_dir=tmp_path, steps=steps)

    assert steps == ["audited"]


def test_model_in_non_main_schema_below_minimum_fails_empty(tmp_path: Path) -> None:
    candidate_dir, candidate_file = _build_candidate(
        tmp_path, StandinOptions(non_main_schema_model=True)
    )
    connection = duckdb.connect(str(candidate_file))
    try:
        connection.execute("DELETE FROM reporting.fct_reporting")
    finally:
        connection.close()

    with pytest.raises(PublishFailed) as error:
        _audit(candidate_dir, candidate_file, project_dir=tmp_path)

    assert error.value.reason == "empty"
    assert "fct_reporting" in error.value.detail
