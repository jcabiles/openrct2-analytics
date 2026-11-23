"""Behavioral tests for the publish build stand-in and stamped files."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import cast

import duckdb
import pytest

from tests.publish_standin import (
    CRASH_EXIT_CODE,
    InvalidMinRows,
    StandinOptions,
    StepObserver,
    build_standin,
    read_stamp,
    start_crashing_process,
    write_stamped,
)


@contextmanager
def read_only(path: Path) -> Iterator[duckdb.DuckDBPyConnection]:
    connection = duckdb.connect(str(path), read_only=True)
    try:
        yield connection
    finally:
        connection.close()


def build_database(
    tmp_path: Path,
    *,
    data_set: str = "rehearsal",
    options: StandinOptions | None = None,
    version: str = "fixture-version",
) -> tuple[Path, Path]:
    candidate_dir = tmp_path / "candidate"
    candidate_dir.mkdir()
    candidate_file = candidate_dir / "warehouse.duckdb"
    snapshot_dir = tmp_path / "snapshot"
    snapshot_dir.mkdir()
    build_standin(data_set, options=options, version=version)(
        candidate_dir, candidate_file, snapshot_dir
    )
    return candidate_dir, candidate_file


def manifest_nodes(candidate_dir: Path) -> dict[str, object]:
    raw_manifest = json.loads(
        (candidate_dir / "target" / "manifest.json").read_text(encoding="utf-8")
    )
    assert isinstance(raw_manifest, dict)
    raw_nodes = cast(dict[str, object], raw_manifest)["nodes"]
    assert isinstance(raw_nodes, dict)
    return cast(dict[str, object], raw_nodes)


def model_node(candidate_dir: Path, name: str) -> dict[str, object]:
    node = manifest_nodes(candidate_dir)[f"model.standin.{name}"]
    assert isinstance(node, dict)
    return cast(dict[str, object], node)


def row_count(connection: duckdb.DuckDBPyConnection, table: str, schema: str = "main") -> int:
    row = connection.execute(f'SELECT count(*) FROM "{schema}"."{table}"').fetchone()
    assert row is not None
    count = row[0]
    assert isinstance(count, int)
    return count


def non_null_column_row_count(connection: duckdb.DuckDBPyConnection, column: str) -> int:
    tables = connection.execute(
        "SELECT DISTINCT table_schema, table_name FROM information_schema.columns "
        "WHERE column_name = ? ORDER BY table_schema, table_name",
        [column],
    ).fetchall()
    total = 0
    escaped_column = column.replace('"', '""')
    for row in tables:
        schema = row[0]
        table = row[1]
        assert isinstance(schema, str)
        assert isinstance(table, str)
        escaped_schema = schema.replace('"', '""')
        escaped_table = table.replace('"', '""')
        count_row = connection.execute(
            f'SELECT count("{escaped_column}") FROM "{escaped_schema}"."{escaped_table}"'
        ).fetchone()
        assert count_row is not None
        count = count_row[0]
        assert isinstance(count, int)
        total += count
    return total


def test_default_build_writes_a_stamped_database_and_manifest(tmp_path: Path) -> None:
    candidate_dir, candidate_file = build_database(tmp_path, data_set="company")

    with read_only(candidate_file) as connection:
        assert connection.execute("SELECT version FROM publish_stamp").fetchall() == [
            ("fixture-version",)
        ]
        assert connection.execute("SELECT park_id, session_id FROM fct_standin").fetchall() == [
            ("park-standin", "session-standin")
        ]
        assert connection.execute(
            "SELECT data_set, park_id FROM int_park_registry__current"
        ).fetchall() == [("company", "park-standin")]
        main_relations = connection.execute(
            "SELECT table_name, table_type FROM information_schema.tables "
            "WHERE table_schema = 'main' ORDER BY table_name"
        ).fetchall()
        assert main_relations == [
            ("fct_standin", "BASE TABLE"),
            ("int_park_registry__current", "BASE TABLE"),
            ("publish_stamp", "BASE TABLE"),
        ]

    nodes = manifest_nodes(candidate_dir)
    assert list(nodes) == ["model.standin.fct_standin"]
    node = model_node(candidate_dir, "fct_standin")
    assert node["relation_name"] == '"warehouse"."main"."fct_standin"'
    assert node["original_file_path"] == "models/marts/fct_standin.sql"
    assert node["materialized"] == "table"
    assert node["config"] == {"materialized": "table"}
    assert node["meta"] == {"expected_min_rows": 1}


def test_keyed_model_can_be_omitted_from_manifest(tmp_path: Path) -> None:
    candidate_dir, _ = build_database(tmp_path, options=StandinOptions(include_keyed_model=False))

    nodes = manifest_nodes(candidate_dir)
    assert "model.standin.fct_standin" not in nodes
    for node in nodes.values():
        assert isinstance(node, dict)
        meta = node["meta"]
        assert isinstance(meta, dict)
        assert "expected_min_rows" not in meta


def test_empty_park_session_option_leaves_no_key_rows(tmp_path: Path) -> None:
    _, candidate_file = build_database(tmp_path, options=StandinOptions(empty_park_session=True))

    with read_only(candidate_file) as connection:
        assert non_null_column_row_count(connection, "park_id") == 0
        assert non_null_column_row_count(connection, "session_id") == 0


def test_view_option_writes_a_view(tmp_path: Path) -> None:
    _, candidate_file = build_database(tmp_path, options=StandinOptions(view=True))

    with read_only(candidate_file) as connection:
        relation = connection.execute(
            "SELECT table_type FROM information_schema.tables "
            "WHERE table_schema = 'main' AND table_name = 'standin_view'"
        ).fetchone()
        assert relation == ("VIEW",)
        assert connection.execute("SELECT * FROM standin_view").fetchall() == [
            ("park-standin", "session-standin")
        ]


def test_empty_audited_option_writes_a_zero_row_model(tmp_path: Path) -> None:
    candidate_dir, candidate_file = build_database(
        tmp_path, options=StandinOptions(empty_audited_table=True)
    )

    with read_only(candidate_file) as connection:
        assert row_count(connection, "fct_empty_audited") == 0
    assert model_node(candidate_dir, "fct_empty_audited")["meta"] == {"expected_min_rows": 1}


def test_undersized_option_writes_one_row_with_minimum_two(tmp_path: Path) -> None:
    candidate_dir, candidate_file = build_database(
        tmp_path, options=StandinOptions(undersized_audited_table=True)
    )

    with read_only(candidate_file) as connection:
        assert row_count(connection, "fct_undersized") == 1
    assert model_node(candidate_dir, "fct_undersized")["meta"] == {"expected_min_rows": 2}


def test_ephemeral_option_has_a_key_but_no_relation(tmp_path: Path) -> None:
    candidate_dir, candidate_file = build_database(
        tmp_path, options=StandinOptions(ephemeral_audited_model=True)
    )

    with read_only(candidate_file) as connection:
        assert (
            connection.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'main' AND table_name = 'int_ephemeral_probe'"
            ).fetchall()
            == []
        )
    node = model_node(candidate_dir, "int_ephemeral_probe")
    assert node["materialized"] == "ephemeral"
    assert node["meta"] == {"expected_min_rows": 1}


def test_empty_exempt_option_has_no_minimum_key(tmp_path: Path) -> None:
    candidate_dir, candidate_file = build_database(
        tmp_path, options=StandinOptions(empty_exempt_table=True)
    )

    with read_only(candidate_file) as connection:
        assert row_count(connection, "fct_empty_exempt") == 0
    assert model_node(candidate_dir, "fct_empty_exempt")["meta"] == {}


@pytest.mark.parametrize("invalid_minimum", [-1, 1.5, "x"])
def test_invalid_minimum_option_preserves_the_bad_manifest_value(
    tmp_path: Path, invalid_minimum: InvalidMinRows
) -> None:
    candidate_dir, candidate_file = build_database(
        tmp_path,
        options=StandinOptions(invalid_expected_min_rows=invalid_minimum),
    )

    with read_only(candidate_file) as connection:
        assert row_count(connection, "fct_invalid_minimum") == 1
    assert model_node(candidate_dir, "fct_invalid_minimum")["meta"] == {
        "expected_min_rows": invalid_minimum
    }


def test_unregistered_park_option_adds_a_park_outside_the_registry(tmp_path: Path) -> None:
    _, candidate_file = build_database(tmp_path, options=StandinOptions(unregistered_park=True))

    with read_only(candidate_file) as connection:
        assert connection.execute("SELECT park_id FROM fct_unregistered_park").fetchall() == [
            ("park-unregistered",)
        ]
        assert (
            connection.execute(
                "SELECT park_id FROM int_park_registry__current WHERE park_id = 'park-unregistered'"
            ).fetchall()
            == []
        )


def test_table_without_session_option_omits_the_session_column(tmp_path: Path) -> None:
    _, candidate_file = build_database(
        tmp_path, options=StandinOptions(table_without_session_id=True)
    )

    with read_only(candidate_file) as connection:
        columns = connection.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'main' AND table_name = 'fct_without_session_id'"
        ).fetchall()
        assert {str(row[0]) for row in columns} == {"model_key", "park_id"}


def test_non_main_schema_option_qualifies_its_model_relation(tmp_path: Path) -> None:
    candidate_dir, candidate_file = build_database(
        tmp_path, options=StandinOptions(non_main_schema_model=True)
    )

    with read_only(candidate_file) as connection:
        assert row_count(connection, "fct_reporting", schema="reporting") == 1
    node = model_node(candidate_dir, "fct_reporting")
    assert node["schema"] == "reporting"
    assert node["relation_name"] == '"warehouse"."reporting"."fct_reporting"'
    assert node["original_file_path"] == "models/marts/fct_reporting.sql"


def test_manifest_relations_are_three_part_and_queryable(tmp_path: Path) -> None:
    candidate_dir, candidate_file = build_database(
        tmp_path,
        options=StandinOptions(
            ephemeral_audited_model=True,
            non_main_schema_model=True,
        ),
    )
    nodes = manifest_nodes(candidate_dir)

    with read_only(candidate_file) as connection:
        for node in nodes.values():
            assert isinstance(node, dict)
            relation_name = node.get("relation_name")
            if relation_name is None:
                assert node["materialized"] == "ephemeral"
                continue
            assert isinstance(relation_name, str)
            parts = relation_name.split(".")
            assert len(parts) == 3
            assert all(part.startswith('"') and part.endswith('"') for part in parts)
            row = connection.execute(f"SELECT count(*) FROM {relation_name}").fetchone()
            assert row is not None
            count = row[0]
            assert isinstance(count, int)


def test_write_stamped_uses_requested_version(tmp_path: Path) -> None:
    path = tmp_path / "rotation.duckdb"

    write_stamped(path, "version-before")
    assert read_stamp(path) == "version-before"
    write_stamped(path, "version-after")

    assert read_stamp(path) == "version-after"


def report_renamed_step(on_step: StepObserver) -> None:
    """Report the target step to a child process's crash observer."""
    on_step("renamed")


def test_crash_helper_exits_child_at_a_named_step() -> None:
    process = start_crashing_process("renamed", report_renamed_step)
    try:
        process.join(timeout=10)
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
        assert not process.is_alive()
        assert process.exitcode == CRASH_EXIT_CODE
    finally:
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)


def test_crash_helper_rejects_unknown_publish_step() -> None:
    with pytest.raises(ValueError, match="unknown publish step"):
        start_crashing_process("not-a-publish-step", report_renamed_step)
