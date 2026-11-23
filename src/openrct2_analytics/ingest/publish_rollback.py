"""Restore the previous published warehouse version under the publish lock."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from openrct2_analytics.ingest.capture import REPO_ROOT
from openrct2_analytics.ingest.publish_prepare import guard_path, take_lock
from openrct2_analytics.ingest.publish_rotation import finish_rotation, rollback_rename

StepObserver = Callable[[str], None]
ROLLBACK_RUN_ID = "rollback"


def rollback(
    name: str,
    *,
    on_step: StepObserver = lambda _: None,
    project_dir: Path = REPO_ROOT,
) -> None:
    """Restore the one-step previous version of a published warehouse.

    Args:
        name: Data-set name used in the warehouse filenames and lock.
        on_step: Observer called after the lock and rollback WAL check succeed.
        project_dir: Project directory containing ``warehouse``.

    Raises:
        PublishRefused: If a path or lock is unsafe, or no previous file exists.
        PublishFailed: If replacing the published file fails.
    """
    warehouse_dir = project_dir / "warehouse"
    published_file = warehouse_dir / f"{name}.duckdb"
    previous_file = warehouse_dir / "previous" / f"{name}.duckdb"
    guard_path(
        published_file,
        root=warehouse_dir,
        project_dir=project_dir,
        allow=frozenset({"published"}),
    )
    guard_path(
        previous_file,
        root=warehouse_dir,
        project_dir=project_dir,
        allow=frozenset({"published"}),
    )

    with take_lock(project_dir, name, ROLLBACK_RUN_ID, on_step):
        finish_rotation(warehouse_dir, name)
        rollback_rename(published_file, previous_file, on_step)
