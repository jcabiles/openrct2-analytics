"""DuckDB build stand-in and stamped files for publish tests."""

from __future__ import annotations

import json
import multiprocessing
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

import duckdb

PUBLISH_STEPS = (
    "locked",
    "candidate-created",
    "landing-locked",
    "snapshot-taken",
    "built",
    "audited",
    "wal-checked",
    "previous-linked",
    "renamed",
    "previous-rotated",
    "candidate-removed",
)
CRASH_EXIT_CODE = 86
SAMPLE_PARK_ID = "park-standin"
SAMPLE_SESSION_ID = "session-standin"
DEFAULT_VERSION = "standin-v1"
INVALID_MIN_ROWS = (-1, 1.5, "x")
InvalidMinRows = int | float | str
StepObserver = Callable[[str], None]
CrashTarget = Callable[[StepObserver], None]


@dataclass(frozen=True)
class StandinOptions:
    """Optional relations and manifest cases added by the build stand-in.

    Args:
        view: Add a view in the main schema.
        empty_audited_table: Add an audited table with no rows.
        undersized_audited_table: Add a table below its expected row minimum.
        ephemeral_audited_model: Add an ephemeral model without a relation.
        empty_exempt_table: Add an empty table without an expected row minimum.
        invalid_expected_min_rows: Add a model with an invalid row minimum.
        unregistered_park: Add a model containing a park absent from the registry.
        table_without_session_id: Add a model without a session identifier column.
        non_main_schema_model: Add a model in the reporting schema.
        include_keyed_model: Include the default model with park and session keys.
        empty_park_session: Leave the park and session tables without rows.
        registered_park_when_empty: Keep one registry row when park/session tables are empty.
        registered_data_set: Register the candidate park under this data set instead.
    """

    view: bool = False
    empty_audited_table: bool = False
    undersized_audited_table: bool = False
    ephemeral_audited_model: bool = False
    empty_exempt_table: bool = False
    invalid_expected_min_rows: InvalidMinRows | None = None
    unregistered_park: bool = False
    table_without_session_id: bool = False
    non_main_schema_model: bool = False
    include_keyed_model: bool = field(default=True, kw_only=True)
    empty_park_session: bool = field(default=False, kw_only=True)
    registered_park_when_empty: bool = field(default=False, kw_only=True)
    registered_data_set: str | None = field(default=None, kw_only=True)


@dataclass(frozen=True)
class PublishStandin:
    """Configured callable that writes a candidate DuckDB file and dbt manifest.

    Args:
        data_set: Data-set name recorded in ``int_park_registry__current``.
        options: Optional schema and row-count cases to add.
        version: Value stored in ``publish_stamp``.
    """

    data_set: str
    options: StandinOptions = field(default_factory=StandinOptions)
    version: str = DEFAULT_VERSION

    def __call__(self, candidate_dir: Path, candidate_file: Path, snapshot_dir: Path) -> None:
        """Write the stand-in warehouse and manifest at the candidate paths."""
        if not snapshot_dir.is_dir():
            raise FileNotFoundError(f"snapshot directory does not exist: {snapshot_dir}")

        candidate_dir.mkdir(parents=True, exist_ok=True)
        candidate_file.parent.mkdir(parents=True, exist_ok=True)
        target_dir = candidate_dir / "target"
        target_dir.mkdir(parents=True, exist_ok=True)

        connection = duckdb.connect(str(candidate_file))
        try:
            database = candidate_file.stem
            _create_base_tables(
                connection,
                self.data_set,
                self.version,
                options=self.options,
            )
            nodes: dict[str, dict[str, object]] = {}
            if self.options.include_keyed_model:
                nodes["model.standin.fct_standin"] = _model_node("fct_standin", database=database)
            _add_optional_relations(connection, nodes, self.options, database)
        finally:
            connection.close()

        _write_manifest(target_dir, nodes)


def build_standin(
    data_set: str,
    *,
    options: StandinOptions | None = None,
    version: str = DEFAULT_VERSION,
) -> PublishStandin:
    """Return a three-path build step configured for a data set and test case."""
    if not data_set:
        raise ValueError("data_set must not be empty")
    if options is None:
        options = StandinOptions()
    if options.invalid_expected_min_rows not in INVALID_MIN_ROWS and (
        options.invalid_expected_min_rows is not None
    ):
        raise ValueError("invalid_expected_min_rows must be -1, 1.5, or 'x'")
    return PublishStandin(data_set=data_set, options=options, version=version)


def write_stamped(path: Path, version: str) -> None:
    """Create or replace a DuckDB file's one-row ``publish_stamp`` table."""
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(str(path))
    try:
        connection.execute("CREATE OR REPLACE TABLE publish_stamp (version VARCHAR)")
        connection.execute("INSERT INTO publish_stamp VALUES (?)", [version])
    finally:
        connection.close()


def read_stamp(path: Path) -> str:
    """Read the single version in a stamped DuckDB file without write access."""
    connection = duckdb.connect(str(path), read_only=True)
    try:
        rows = connection.execute("SELECT version FROM publish_stamp").fetchall()
    finally:
        connection.close()
    if len(rows) != 1:
        raise ValueError(f"expected one publish stamp in {path}, found {len(rows)}")
    version = rows[0][0]
    if not isinstance(version, str):
        raise TypeError(f"publish stamp in {path} is not text")
    return version


def crash_at_step(step: str) -> StepObserver:
    """Return an observer that exits its child process after the named publish step."""
    if step not in PUBLISH_STEPS:
        raise ValueError(f"unknown publish step: {step}")

    def observe(completed_step: str) -> None:
        if completed_step == step:
            os._exit(CRASH_EXIT_CODE)

    return observe


def _crash_child(step: str, target: CrashTarget) -> None:
    """Run ``target`` in a child process with an observer exiting at ``step``."""
    target(crash_at_step(step))


def start_crashing_process(step: str, target: CrashTarget) -> multiprocessing.context.SpawnProcess:
    """Start a spawned child that exits at ``step`` when its target reports it."""
    if step not in PUBLISH_STEPS:
        raise ValueError(f"unknown publish step: {step}")
    process = multiprocessing.get_context("spawn").Process(
        target=_crash_child,
        args=(step, target),
    )
    process.start()
    return process


def _create_base_tables(
    connection: duckdb.DuckDBPyConnection,
    data_set: str,
    version: str,
    *,
    options: StandinOptions,
) -> None:
    connection.execute("CREATE TABLE publish_stamp (version VARCHAR)")
    connection.execute("INSERT INTO publish_stamp VALUES (?)", [version])
    if options.include_keyed_model:
        connection.execute(
            "CREATE TABLE main.fct_standin (park_id VARCHAR, session_id VARCHAR, event_id VARCHAR)"
        )
        if not options.empty_park_session:
            connection.execute(
                "INSERT INTO main.fct_standin VALUES (?, ?, ?)",
                [SAMPLE_PARK_ID, SAMPLE_SESSION_ID, "event-standin"],
            )
    connection.execute(
        "CREATE TABLE main.int_park_registry__current (data_set VARCHAR, park_id VARCHAR)"
    )
    if not options.empty_park_session or options.registered_park_when_empty:
        registry_data_set = (
            data_set if options.registered_data_set is None else options.registered_data_set
        )
        connection.execute(
            "INSERT INTO main.int_park_registry__current VALUES (?, ?)",
            [registry_data_set, SAMPLE_PARK_ID],
        )


def _add_optional_relations(
    connection: duckdb.DuckDBPyConnection,
    nodes: dict[str, dict[str, object]],
    options: StandinOptions,
    database: str,
) -> None:
    _add_view(connection, options.view)
    _add_empty_audited_table(connection, nodes, options.empty_audited_table, database)
    _add_undersized_audited_table(connection, nodes, options.undersized_audited_table, database)
    _add_ephemeral_model(nodes, options.ephemeral_audited_model, database)
    _add_empty_exempt_table(connection, nodes, options.empty_exempt_table, database)
    _add_invalid_minimum(connection, nodes, options.invalid_expected_min_rows, database)
    _add_unregistered_park(connection, nodes, options.unregistered_park, database)
    _add_table_without_session_id(connection, nodes, options.table_without_session_id, database)
    _add_non_main_schema_model(connection, nodes, options.non_main_schema_model, database)


def _add_view(connection: duckdb.DuckDBPyConnection, enabled: bool) -> None:
    if enabled:
        connection.execute(
            "CREATE VIEW main.standin_view AS SELECT park_id, session_id FROM main.fct_standin"
        )


def _add_empty_audited_table(
    connection: duckdb.DuckDBPyConnection,
    nodes: dict[str, dict[str, object]],
    enabled: bool,
    database: str,
) -> None:
    if enabled:
        connection.execute("CREATE TABLE main.fct_empty_audited (model_key BIGINT)")
        _add_node(nodes, "fct_empty_audited", database=database)


def _add_undersized_audited_table(
    connection: duckdb.DuckDBPyConnection,
    nodes: dict[str, dict[str, object]],
    enabled: bool,
    database: str,
) -> None:
    if enabled:
        connection.execute("CREATE TABLE main.fct_undersized (model_key BIGINT)")
        connection.execute("INSERT INTO main.fct_undersized VALUES (1)")
        _add_node(nodes, "fct_undersized", database=database, expected_min_rows=2)


def _add_ephemeral_model(nodes: dict[str, dict[str, object]], enabled: bool, database: str) -> None:
    if enabled:
        _add_node(
            nodes,
            "int_ephemeral_probe",
            database=database,
            materialized="ephemeral",
        )


def _add_empty_exempt_table(
    connection: duckdb.DuckDBPyConnection,
    nodes: dict[str, dict[str, object]],
    enabled: bool,
    database: str,
) -> None:
    if enabled:
        connection.execute("CREATE TABLE main.fct_empty_exempt (model_key BIGINT)")
        _add_node(nodes, "fct_empty_exempt", database=database, expected_min_rows=None)


def _add_invalid_minimum(
    connection: duckdb.DuckDBPyConnection,
    nodes: dict[str, dict[str, object]],
    expected_min_rows: InvalidMinRows | None,
    database: str,
) -> None:
    if expected_min_rows is not None:
        connection.execute("CREATE TABLE main.fct_invalid_minimum (model_key BIGINT)")
        connection.execute("INSERT INTO main.fct_invalid_minimum VALUES (1)")
        _add_node(
            nodes,
            "fct_invalid_minimum",
            database=database,
            expected_min_rows=expected_min_rows,
        )


def _add_unregistered_park(
    connection: duckdb.DuckDBPyConnection,
    nodes: dict[str, dict[str, object]],
    enabled: bool,
    database: str,
) -> None:
    if enabled:
        connection.execute(
            "CREATE TABLE main.fct_unregistered_park (park_id VARCHAR, session_id VARCHAR)"
        )
        connection.execute(
            "INSERT INTO main.fct_unregistered_park VALUES (?, ?)",
            ["park-unregistered", SAMPLE_SESSION_ID],
        )
        _add_node(nodes, "fct_unregistered_park", database=database)


def _add_table_without_session_id(
    connection: duckdb.DuckDBPyConnection,
    nodes: dict[str, dict[str, object]],
    enabled: bool,
    database: str,
) -> None:
    if enabled:
        connection.execute(
            "CREATE TABLE main.fct_without_session_id (park_id VARCHAR, model_key BIGINT)"
        )
        connection.execute(
            "INSERT INTO main.fct_without_session_id VALUES (?, ?)", [SAMPLE_PARK_ID, 1]
        )
        _add_node(nodes, "fct_without_session_id", database=database)


def _add_non_main_schema_model(
    connection: duckdb.DuckDBPyConnection,
    nodes: dict[str, dict[str, object]],
    enabled: bool,
    database: str,
) -> None:
    if enabled:
        connection.execute("CREATE SCHEMA reporting")
        connection.execute(
            "CREATE TABLE reporting.fct_reporting "
            "(park_id VARCHAR, session_id VARCHAR, model_key BIGINT)"
        )
        connection.execute(
            "INSERT INTO reporting.fct_reporting VALUES (?, ?, ?)",
            [SAMPLE_PARK_ID, SAMPLE_SESSION_ID, 1],
        )
        _add_node(nodes, "fct_reporting", database=database, schema="reporting")


def _add_node(
    nodes: dict[str, dict[str, object]],
    name: str,
    *,
    database: str,
    schema: str = "main",
    materialized: str = "table",
    expected_min_rows: int | float | str | None = 1,
) -> None:
    unique_id = f"model.standin.{name}"
    meta: dict[str, object] = (
        {} if expected_min_rows is None else {"expected_min_rows": expected_min_rows}
    )
    nodes[unique_id] = _model_node(
        name,
        database=database,
        schema=schema,
        materialized=materialized,
        meta=meta,
    )


def _model_node(
    name: str,
    *,
    database: str,
    schema: str = "main",
    materialized: str = "table",
    meta: dict[str, object] | None = None,
) -> dict[str, object]:
    model_meta = {"expected_min_rows": 1} if meta is None else meta
    node: dict[str, object] = {
        "resource_type": "model",
        "unique_id": f"model.standin.{name}",
        "name": name,
        "schema": schema,
        "alias": name,
        "original_file_path": f"models/marts/{name}.sql",
        "materialized": materialized,
        "config": {"materialized": materialized},
        "meta": model_meta,
    }
    if materialized != "ephemeral":
        node["relation_name"] = (
            f'"{_quote_identifier(database)}"."{_quote_identifier(schema)}".'
            f'"{_quote_identifier(name)}"'
        )
    return node


def add_registry_model(candidate_dir: Path, database: str, *, kind: str = "current") -> None:
    """Plant the manifest node a real dbt manifest carries for one registry relation.

    Args:
        candidate_dir: Candidate folder whose ``target/manifest.json`` gets the node.
        database: Database name used in the node's relation name.
        kind: The ``meta.park_registry`` value: ``staging``, ``history`` or ``current``.
    """
    path = candidate_dir / "target" / "manifest.json"
    manifest = cast(dict[str, object], json.loads(path.read_text(encoding="utf-8")))
    nodes = cast(dict[str, dict[str, object]], manifest["nodes"])
    name = {
        "staging": "stg_park_registry",
        "history": "int_park_registry__history",
        "current": "int_park_registry__current",
    }[kind]
    nodes[f"model.standin.{name}"] = _model_node(
        name, database=database, meta={"park_registry": kind}
    )
    path.write_text(json.dumps(manifest), encoding="utf-8")


def _quote_identifier(identifier: str) -> str:
    """Escape a DuckDB identifier for use in a quoted relation name."""
    return identifier.replace('"', '""')


def _write_manifest(target_dir: Path, nodes: dict[str, dict[str, object]]) -> None:
    manifest: dict[str, object] = {
        "metadata": {"dbt_schema_version": "https://schemas.getdbt.com/dbt/manifest/v12.json"},
        "nodes": nodes,
    }
    (target_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
