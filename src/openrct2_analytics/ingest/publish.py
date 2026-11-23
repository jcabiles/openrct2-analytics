"""Publish a data set's warehouse: lock, snapshot, build, audit, then rotate."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import duckdb

from openrct2_analytics.config import DATA_SETS, ConfigError, landing_dirs
from openrct2_analytics.ingest.capture import REPO_ROOT
from openrct2_analytics.ingest.lock import Interrupted, raise_interrupted, set_signal_handlers
from openrct2_analytics.ingest.publish_audit import (
    audit_candidate,
    audit_seq,
    open_warehouse,
    qualified,
)
from openrct2_analytics.ingest.publish_build import run_dbt_build
from openrct2_analytics.ingest.publish_contracts import check_contracts
from openrct2_analytics.ingest.publish_errors import (
    PublishFailed,
    PublishRefused,
    exit_code,
    format_line,
)
from openrct2_analytics.ingest.publish_prepare import (
    check_run_id,
    create_candidate,
    guard_path,
    take_lock,
)
from openrct2_analytics.ingest.publish_rollback import rollback
from openrct2_analytics.ingest.publish_rotation import (
    check_wal,
    finish_rotation,
    make_read_only,
    rotate,
)
from openrct2_analytics.ingest.publish_snapshot import take_snapshot
from openrct2_analytics.ingest.registry_feed import registry_dir


@dataclass(frozen=True)
class PublishSummary:
    """What a completed publish put in place, read from the candidate under the lock."""

    tables: int
    rows: int
    kept_rollback: bool


StepObserver = Callable[[str], None]
BuildStep = Callable[[Path, Path, Path], None]


def _check_data_set(name: str, *, check_registry: bool = True) -> None:
    """Refuse data sets whose landing or registry folders cannot be used."""
    try:
        landing_dirs(name)
        if check_registry:
            registry_dir(name)
    except ConfigError as error:
        raise PublishRefused("data-set", str(error)) from error


# System schemas, plus dbt's test-failure storage, which is not model output.
_UNCOUNTED_SCHEMAS = ("information_schema", "pg_catalog", "system", "dbt_test__audit")


def _candidate_counts(candidate_file: Path, project_dir: Path) -> tuple[int, int]:
    """Count model tables and rows in the audited candidate, across all model schemas."""
    try:
        connection = open_warehouse(candidate_file, project_dir=project_dir)
    except duckdb.Error as error:
        raise PublishFailed("candidate-count", f"{candidate_file}: {error}") from error
    try:
        placeholders = ", ".join("?" for _ in _UNCOUNTED_SCHEMAS)
        tables = connection.execute(
            "SELECT table_schema, table_name FROM information_schema.tables "
            f"WHERE table_type = 'BASE TABLE' AND table_schema NOT IN ({placeholders}) "
            "ORDER BY table_schema, table_name",
            list(_UNCOUNTED_SCHEMAS),
        ).fetchall()
        row_count = 0
        for schema, table in tables:
            relation = qualified(str(schema), str(table))
            count = connection.execute(f"SELECT count(*) FROM {relation}").fetchone()
            if count is None:
                raise PublishFailed("candidate-count", f"could not count rows in {relation}")
            row_count += int(count[0])
        return len(tables), row_count
    except duckdb.Error as error:
        raise PublishFailed("candidate-count", f"{candidate_file}: {error}") from error
    finally:
        connection.close()


def publish(
    name: str,
    *,
    run_id: str | None = None,
    build: BuildStep | None = None,
    on_step: StepObserver = lambda _: None,
    project_dir: Path = REPO_ROOT,
) -> PublishSummary:
    """Build a candidate warehouse for a data set and rotate it in as the published file.

    Args:
        name: Data-set name used in the landing folder, lock and warehouse file names.
        run_id: Identifier for the lock and candidate folder; a random one when omitted.
        build: Writes the candidate file from the snapshot, given the candidate folder, the
            candidate file and the snapshot folder; the dbt build when omitted.
        on_step: Observer called after each completed step.
        project_dir: Project folder containing ``warehouse``.

    Returns:
        The candidate's table and row counts and whether a rollback file was kept, both
        read while the publish lock is held and before the swap.

    Raises:
        PublishRefused: If the run ID, a path, the lock or the audit refuses the publish.
        PublishFailed: If a step fails; the published file is unchanged unless rotation failed.
    """
    # Resolve landing folders before the lock or warehouse exists, as convert does.
    _check_data_set(name)
    run_id = uuid4().hex if run_id is None else run_id
    check_run_id(run_id)
    warehouse_dir = project_dir / "warehouse"
    published_file = warehouse_dir / f"{name}.duckdb"
    previous_file = warehouse_dir / "previous" / f"{name}.duckdb"

    for guarded in (published_file, previous_file):
        guard_path(
            guarded,
            root=warehouse_dir,
            project_dir=project_dir,
            allow=frozenset({"published"}),
        )

    with take_lock(project_dir, name, run_id, on_step):
        finish_rotation(warehouse_dir, name)
        with create_candidate(project_dir, name, run_id, on_step) as candidate_dir:
            candidate_file = candidate_dir / f"{name}.duckdb"
            snapshot_dir = take_snapshot(project_dir, name, candidate_dir, on_step)
            audit_seq(snapshot_dir)
            check_contracts(candidate_dir, data_set=name)
            paths = (candidate_dir, candidate_file, snapshot_dir)
            if build is None:
                run_dbt_build(project_dir, name, run_id, *paths, on_step)
            else:
                build(*paths)
                on_step("built")
            audit_candidate(candidate_file, candidate_dir, name, project_dir, on_step=on_step)
            make_read_only(candidate_file)
            check_wal(candidate_file, published_file, on_step)
            # Counted before the swap so a failure or signal leaves the published and
            # rollback files untouched; rotate keeps a rollback exactly when one is published.
            tables, rows = _candidate_counts(candidate_file, project_dir)
            kept_rollback = published_file.is_file()
            rotate(candidate_file, published_file, previous_file, on_step)
    return PublishSummary(tables, rows, kept_rollback)


def main(
    argv: Sequence[str] | None = None,
    *,
    run_id: str | None = None,
    build: BuildStep | None = None,
    project_dir: Path = REPO_ROOT,
) -> int:
    """Publish or roll back a data set and return its command exit code."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-set", choices=DATA_SETS, required=True)
    parser.add_argument("--rollback", action="store_true")
    args = parser.parse_args(argv)

    set_signal_handlers(raise_interrupted)
    try:
        if args.rollback:
            _check_data_set(args.data_set, check_registry=False)
            rollback(args.data_set, project_dir=project_dir)
        else:
            summary = publish(args.data_set, run_id=run_id, build=build, project_dir=project_dir)
            if summary.kept_rollback:
                kept = f"kept warehouse/previous/{args.data_set}.duckdb for one rollback"
            else:
                kept = "no earlier file kept"
            print(
                f"published warehouse/{args.data_set}.duckdb: {summary.tables} tables, "
                f"{summary.rows} rows; {kept}"
            )
    except (PublishRefused, PublishFailed) as error:
        print(format_line(error))
        return exit_code(error)
    except Interrupted as error:
        print(f"publish interrupted: {error}; the lock was removed.")
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
