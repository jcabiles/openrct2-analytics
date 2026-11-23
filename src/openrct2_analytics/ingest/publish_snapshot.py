"""Take a stable copy of the landing Parquet files for a warehouse publish."""

from __future__ import annotations

import os
import shutil
import time
from collections.abc import Callable
from pathlib import Path

from openrct2_analytics.config import landing_dirs
from openrct2_analytics.ingest.convert import landing_lock_path
from openrct2_analytics.ingest.landing_paths import project_path
from openrct2_analytics.ingest.lock import LockTaken, hold_lock
from openrct2_analytics.ingest.play_mode_feed import FILE_GLOB as LABEL_GLOB
from openrct2_analytics.ingest.publish_errors import PublishFailed
from openrct2_analytics.ingest.registry_feed import FILE_GLOB, registry_dir


def _copy_snapshot(source_v1: Path, snapshot_v1: Path) -> None:
    """Copy the source files into a new snapshot folder, translating filesystem errors."""
    try:
        with os.scandir(source_v1) as entries:
            files = sorted(
                source_v1 / entry.name for entry in entries if entry.name.endswith(".parquet")
            )
    except FileNotFoundError:
        raise PublishFailed("no-input", f"{source_v1} holds no Parquet files") from None
    except OSError as exc:
        raise PublishFailed("snapshot", f"{source_v1}: {exc}") from exc
    if not files:
        raise PublishFailed("no-input", f"{source_v1} holds no Parquet files")
    try:
        snapshot_v1.mkdir(parents=True)
    except OSError as exc:
        raise PublishFailed("snapshot", f"{snapshot_v1}: {exc}") from exc
    for source in files:
        destination = snapshot_v1 / source.name
        try:
            shutil.copy2(source, destination)
        except OSError as exc:
            raise PublishFailed("snapshot", f"{source} -> {destination}: {exc}") from exc


def _copy_feed(source_v1: Path, snapshot_v1: Path) -> None:
    """Copy every registry and label delivery into the snapshot; the folder always exists."""
    try:
        snapshot_v1.mkdir(parents=True)
        for pattern in (FILE_GLOB, LABEL_GLOB):
            for source in sorted(source_v1.glob(pattern)):
                shutil.copy2(source, snapshot_v1 / source.name)
    except OSError as exc:
        raise PublishFailed("snapshot", f"{source_v1} -> {snapshot_v1}: {exc}") from exc


def take_snapshot(
    project_dir: Path,
    name: str,
    candidate_dir: Path,
    on_step: Callable[[str], None],
) -> Path:
    """Copy one conversion's ``v1`` Parquet files and the data set's feed into a candidate.

    Args:
        project_dir: Project root used to resolve a relative landing path.
        name: Data set name passed to ``landing_dirs``.
        candidate_dir: The already-created publish candidate folder.
        on_step: Callback invoked after each completed snapshot step.

    Returns:
        The candidate's ``landing`` folder, containing ``v1`` and ``registry``.

    Raises:
        PublishFailed: if a conversion holds the landing lock or ``v1`` has no Parquet files.
    """
    landing = project_path(landing_dirs(name).parquet, project_dir)
    lock_path = landing_lock_path(landing)
    try:
        landing = landing.resolve()
    except OSError as exc:
        raise PublishFailed("snapshot", f"{landing}: {exc}") from exc
    source_v1 = landing / "v1"
    snapshot_dir = candidate_dir / "landing"
    snapshot_v1 = snapshot_dir / "v1"
    feed = project_path(registry_dir(name), project_dir)
    source_feed_v1 = feed / "v1"
    snapshot_feed_v1 = snapshot_dir / "registry" / "v1"
    started = time.strftime("%Y-%m-%dT%H:%M:%S%z")

    try:
        landing_exists = landing.parent.exists()
    except OSError as exc:
        raise PublishFailed("snapshot", f"{landing.parent}: {exc}") from exc
    if not landing_exists:
        raise PublishFailed("no-input", f"{source_v1} holds no Parquet files")

    try:
        with hold_lock(lock_path, f"pid {os.getpid()} started {started}"):
            on_step("landing-locked")
            _copy_snapshot(source_v1, snapshot_v1)
            _copy_feed(source_feed_v1, snapshot_feed_v1)
    except LockTaken as error:
        raise PublishFailed(
            "converting",
            f"A conversion holds {error.path} ({error.line}). Publish again when it ends.",
        ) from error
    except OSError as exc:
        raise PublishFailed("snapshot", f"{lock_path}: {exc}") from exc

    on_step("snapshot-taken")
    return snapshot_dir
