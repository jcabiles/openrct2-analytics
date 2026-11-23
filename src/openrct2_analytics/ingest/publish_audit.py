"""Sequence and candidate warehouse audits for publishing."""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from pathlib import Path
from typing import cast

import duckdb

from openrct2_analytics.ingest import warehouse_guard
from openrct2_analytics.ingest.convert import VIOLATION_FILTER, seq_audit
from openrct2_analytics.ingest.publish_errors import PublishFailed, PublishRefused

StepObserver = Callable[[str], None]
_RELATION_PART_COUNT = 3
_LAST_RELATION_POSITION = _RELATION_PART_COUNT - 1


def audit_seq(landing_dir: Path) -> None:
    """Recompute the sequence audit from every landed v1 Parquet file.

    Args:
        landing_dir: Snapshot directory containing ``v1/*.parquet``.

    Raises:
        PublishFailed: When an event sequence has a gap, repeat, or bad start.
    """
    event_dir = landing_dir / "v1"
    try:
        files = sorted(path for path in event_dir.iterdir() if path.suffix == ".parquet")
    except OSError as exc:
        raise PublishFailed("seq-audit", f"{event_dir}: {exc}") from exc
    if not files:
        raise PublishFailed("seq-audit", f"{event_dir} holds no event files")

    connection = duckdb.connect(":memory:")
    try:
        try:
            events = connection.read_parquet(
                [path.as_posix() for path in files], union_by_name=True
            )
            selected = events.project("park_id, session_id, seq")
            violations = seq_audit(selected).filter(VIOLATION_FILTER).fetchall()
        except duckdb.Error as error:
            raise PublishFailed("seq-audit", f"{event_dir}: {error}") from error
    finally:
        connection.close()

    if violations:
        detail = "; ".join(
            f"park={park}, session={session}, first_seq={first}, last_seq={last}, "
            f"missing={missing}, duplicates={duplicates}, parks={parks}"
            for park, session, first, last, _rows, missing, duplicates, parks in violations
        )
        raise PublishFailed("seq-audit", detail)


def open_warehouse(
    path: Path,
    *,
    project_dir: Path,
    read_only: bool = True,
) -> duckdb.DuckDBPyConnection:
    """Open a DuckDB warehouse, refusing write access to published files.

    Args:
        path: Database file to open.
        project_dir: Project folder that owns the published warehouse paths.
        read_only: Whether DuckDB must open the database read-only.

    Returns:
        An open DuckDB connection.

    Raises:
        PublishRefused: When write mode targets a published or previous file.
    """
    if not read_only and warehouse_guard.is_published(path, project_dir=project_dir):
        raise PublishRefused(
            "published",
            f"write-mode open refused for published warehouse: {path}",
        )
    return duckdb.connect(str(path), read_only=read_only)


def audit_candidate(
    candidate_file: Path,
    candidate_dir: Path,
    data_set: str,
    project_dir: Path,
    *,
    on_step: StepObserver,
) -> None:
    """Run step 7's view, row-count, park, registry, and session checks.

    Args:
        candidate_file: DuckDB file produced by the build.
        candidate_dir: Candidate folder containing dbt's target manifest.
        data_set: Data set whose registry rows are valid for this candidate.
        project_dir: Project folder used to guard published warehouse opens.
        on_step: Observer called after all checks pass.

    Raises:
        PublishFailed: When a candidate violates one of the audit checks.
    """
    try:
        connection = open_warehouse(candidate_file, project_dir=project_dir)
    except duckdb.IOException as error:
        raise PublishFailed("candidate-unreadable", f"{candidate_file}: {error}") from error
    try:
        _check_views(connection)
        manifest_nodes = _read_manifest_nodes(candidate_dir)
        _check_expected_rows(connection, manifest_nodes)
        registry = _registry_relation(manifest_nodes)
        registry_tables = _registry_tables(manifest_nodes)
        park_tables = _tables_with_column(connection, "park_id")
        _check_park_rows(connection, park_tables, registry_tables)
        _check_registered_parks(
            connection, park_tables, registry, registry_tables, data_set=data_set
        )
        _check_session_rows(connection)
    finally:
        connection.close()
    on_step("audited")


def _read_manifest_nodes(candidate_dir: Path) -> list[dict[str, object]]:
    path = candidate_dir / "target" / "manifest.json"
    try:
        raw_manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PublishFailed("empty", f"{path}: {exc}") from exc
    if not isinstance(raw_manifest, dict):
        raise PublishFailed("empty", f"{path}: invalid dbt manifest object")
    raw_nodes = raw_manifest.get("nodes")
    if not isinstance(raw_nodes, dict):
        raise PublishFailed("empty", f"{path}: manifest has no nodes object")
    return [
        cast(dict[str, object], node)
        for node in raw_nodes.values()
        if isinstance(node, dict) and node.get("resource_type") == "model"
    ]


def _check_views(connection: duckdb.DuckDBPyConnection) -> None:
    views = connection.execute(
        "SELECT table_schema, table_name FROM information_schema.tables "
        "WHERE table_type = 'VIEW' ORDER BY table_schema, table_name"
    ).fetchall()
    if views:
        detail = ", ".join(f"{schema}.{table}" for schema, table in views)
        raise PublishFailed("views", f"candidate contains view(s): {detail}")


def _check_expected_rows(
    connection: duckdb.DuckDBPyConnection,
    nodes: list[dict[str, object]],
) -> None:
    for node in nodes:
        if node.get("resource_type") != "model":
            continue
        name = str(node.get("name", node.get("unique_id", "<unnamed model>")))
        meta = node.get("meta")
        if not isinstance(meta, dict) or "expected_min_rows" not in meta:
            continue
        raw_expected = meta["expected_min_rows"]
        expected = _whole_nonnegative_number(raw_expected)
        if expected is None:
            raise PublishFailed(
                "empty",
                f"model {name} has invalid expected_min_rows {raw_expected!r}; "
                "expected a whole number of zero or more",
            )
        if expected == 0:
            continue
        if _materialization(node) == "ephemeral":
            raise PublishFailed(
                "empty",
                f"model {name} is ephemeral with expected {expected} rows and actual unavailable",
            )
        relation_name = node.get("relation_name")
        if not isinstance(relation_name, str) or _relation_parts(relation_name) is None:
            raise PublishFailed(
                "empty",
                f"model {name} expected {expected} rows and actual unavailable: "
                "missing or invalid relation_name",
            )
        try:
            row = connection.execute(f"SELECT count(*) FROM {relation_name}").fetchone()
        except duckdb.Error as exc:
            raise PublishFailed(
                "empty",
                f"model {name} expected {expected} rows and actual unavailable: {exc}",
            ) from exc
        actual = _row_count(row, f"model {name}")
        if actual < expected:
            raise PublishFailed(
                "empty",
                f"model {name} expected {expected} rows and actual {actual}",
            )


def _whole_nonnegative_number(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float) and math.isfinite(value) and value >= 0 and value.is_integer():
        return int(value)
    return None


def _materialization(node: dict[str, object]) -> str | None:
    materialized = node.get("materialized")
    if isinstance(materialized, str):
        return materialized
    config = node.get("config")
    if isinstance(config, dict) and isinstance(config.get("materialized"), str):
        return cast(str, config["materialized"])
    return None


def _relation_parts(relation_name: str) -> tuple[str, str, str] | None:
    """Parse exactly three double-quoted DuckDB identifiers."""
    parts: list[str] = []
    index = 0
    for position in range(_RELATION_PART_COUNT):
        if index >= len(relation_name) or relation_name[index] != '"':
            return None
        index += 1
        identifier: list[str] = []
        while index < len(relation_name):
            char = relation_name[index]
            index += 1
            if char != '"':
                identifier.append(char)
            elif index < len(relation_name) and relation_name[index] == '"':
                identifier.append('"')
                index += 1
            else:
                break
        else:
            return None
        if not identifier:
            return None
        parts.append("".join(identifier))
        if position != _LAST_RELATION_POSITION:
            if index >= len(relation_name) or relation_name[index] != ".":
                return None
            index += 1
    if index != len(relation_name):
        return None
    return parts[0], parts[1], parts[2]


def _meta(node: dict[str, object]) -> dict[str, object]:
    meta = node.get("meta")
    return cast(dict[str, object], meta) if isinstance(meta, dict) else {}


def _node_relation(node: dict[str, object]) -> tuple[str, str, str] | None:
    relation_name = node.get("relation_name")
    if not isinstance(relation_name, str):
        return None
    parts = _relation_parts(relation_name)
    if parts is None:
        return None
    return relation_name, parts[1], parts[2]


def _registry_relation(nodes: list[dict[str, object]]) -> tuple[str, str, str]:
    for node in nodes:
        if node.get("resource_type") == "model" and _meta(node).get("park_registry") == "current":
            relation = _node_relation(node)
            if relation is not None:
                return relation
    raise PublishFailed(
        "unregistered-park", "candidate manifest has no model with meta park_registry: current"
    )


def _registry_tables(nodes: list[dict[str, object]]) -> set[tuple[str, str]]:
    """Return schema and table of every registry relation: staging, history and current."""
    tables: set[tuple[str, str]] = set()
    for node in nodes:
        if node.get("resource_type") == "model" and _meta(node).get("park_registry"):
            relation = _node_relation(node)
            if relation is not None:
                tables.add(relation[1:])
    return tables


def _tables_with_column(
    connection: duckdb.DuckDBPyConnection,
    column: str,
) -> list[tuple[str, str]]:
    rows = connection.execute(
        "SELECT DISTINCT table_schema, table_name FROM information_schema.columns "
        "WHERE column_name = ? AND table_schema NOT IN "
        "('information_schema', 'pg_catalog', 'system') "
        "ORDER BY table_schema, table_name",
        [column],
    ).fetchall()
    tables: list[tuple[str, str]] = []
    for schema, table in rows:
        if isinstance(schema, str) and isinstance(table, str):
            tables.append((schema, table))
    return tables


def _check_park_rows(
    connection: duckdb.DuckDBPyConnection,
    park_tables: list[tuple[str, str]],
    registry_tables: set[tuple[str, str]],
) -> None:
    total = 0
    for schema, table in park_tables:
        if (schema, table) in registry_tables:
            continue
        total += _count_non_null(connection, schema, table, "park_id")
    if total == 0:
        raise PublishFailed("no-park", "candidate has no non-null park_id values")


def _check_registered_parks(
    connection: duckdb.DuckDBPyConnection,
    park_tables: list[tuple[str, str]],
    registry: tuple[str, str, str],
    registry_tables: set[tuple[str, str]],
    *,
    data_set: str,
) -> None:
    registry_relation = registry[0]
    registry_columns = _columns(connection, registry[1], registry[2])
    if not {"park_id", "data_set"}.issubset(registry_columns):
        raise PublishFailed(
            "unregistered-park",
            "current park registry relation lacks park_id or data_set",
        )
    unregistered: dict[str, str] = {}
    for schema, table in park_tables:
        if (schema, table) in registry_tables:
            continue
        relation = qualified(schema, table)
        rows = connection.execute(
            f'SELECT DISTINCT source."park_id" FROM {relation} AS source '
            f"WHERE NOT EXISTS (SELECT 1 FROM {registry_relation} AS registered "
            'WHERE registered."data_set" = ? '
            'AND registered."park_id" IS NOT DISTINCT FROM source."park_id")',
            [data_set],
        ).fetchall()
        for (park_id,) in rows:
            display = "<NULL>" if park_id is None else str(park_id)
            unregistered[repr(park_id)] = display
    if unregistered:
        detail = ", ".join(sorted(unregistered.values()))
        raise PublishFailed("unregistered-park", f"unregistered park_id value(s): {detail}")


def _check_session_rows(connection: duckdb.DuckDBPyConnection) -> None:
    total = sum(
        _count_non_null(connection, schema, table, "session_id")
        for schema, table in _tables_with_column(connection, "session_id")
    )
    if total == 0:
        raise PublishFailed("no-session", "candidate has no non-null session_id values")


def _count_non_null(
    connection: duckdb.DuckDBPyConnection,
    schema: str,
    table: str,
    column: str,
) -> int:
    relation = qualified(schema, table)
    quoted_column = _quote_identifier(column)
    row = connection.execute(f'SELECT count("{quoted_column}") FROM {relation}').fetchone()
    return _row_count(row, f"{schema}.{table}.{column}")


def _columns(
    connection: duckdb.DuckDBPyConnection,
    schema: str,
    table: str,
) -> set[str]:
    rows = connection.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = ? AND table_name = ?",
        [schema, table],
    ).fetchall()
    return {str(row[0]) for row in rows}


def qualified(schema: str, table: str) -> str:
    """Return the double-quoted, escaped ``schema.table`` relation name."""
    return f'"{_quote_identifier(schema)}"."{_quote_identifier(table)}"'


def _quote_identifier(identifier: str) -> str:
    return identifier.replace('"', '""')


def _row_count(row: tuple[object, ...] | None, subject: str) -> int:
    if row is None or not isinstance(row[0], int):
        raise PublishFailed("empty", f"could not read row count for {subject}")
    return row[0]
