"""Read-only preparation, file rotation, interrupted recovery and rollback."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from openrct2_analytics.ingest.publish_errors import PublishFailed

__all__ = [
    "check_wal",
    "finish_rotation",
    "make_read_only",
    "rollback_rename",
    "rotate",
]

StepObserver = Callable[[str], None]


def finish_rotation(warehouse_dir: Path, name: str) -> None:
    """Finish a rotation left between its atomic file operations.

    Args:
        warehouse_dir: The warehouse folder containing the published database.
        name: The data-set name used in the database filename.
    """
    published_file = warehouse_dir / f"{name}.duckdb"
    previous_file = warehouse_dir / "previous" / f"{name}.duckdb"
    new_file = previous_file.with_name(f"{previous_file.name}.new")

    if not _exists(new_file, "rotation"):
        print(f"no interrupted rotation: {new_file} does not exist")
        return
    if not _exists(published_file, "rotation"):
        detail = (
            f"{new_file} exists while {published_file} is missing; open "
            f"{new_file} read-only to see which version it holds, then run "
            f"`mv warehouse/previous/{name}.duckdb.new "
            f"warehouse/{name}.duckdb` and run the command again"
        )
        raise PublishFailed("rotation-leftover", detail)
    try:
        same_file = os.path.samefile(new_file, published_file)
    except OSError as exc:
        raise PublishFailed(
            "rotation", f"could not compare {new_file} and {published_file}: {exc}"
        ) from exc
    if same_file:
        _unlink_rotation_leftover(new_file)
        print(
            f"finished interrupted rotation: removed {new_file}; "
            f"it was the same file as {published_file}"
        )
        return

    _replace_file(new_file, previous_file, "rotation")
    print(f"finished interrupted rotation: moved {new_file} over {previous_file}")


def make_read_only(file: Path) -> None:
    """Remove write permission from a candidate before publishing it.

    Args:
        file: The DuckDB file to make read-only.
    """
    try:
        os.chmod(file, 0o444)
    except OSError as exc:
        raise PublishFailed("rotation", f"could not make {file} read-only: {exc}") from exc


def check_wal(candidate_file: Path, published_file: Path, on_step: StepObserver) -> None:
    """Refuse rotation if either database has a DuckDB write-ahead log.

    Args:
        candidate_file: The audited candidate database.
        published_file: The database currently available to readers, if any.
        on_step: Observer called after the WAL check succeeds.
    """
    wal_files = [
        file.with_name(f"{file.name}.wal")
        for file in (candidate_file, published_file)
        if _exists(file.with_name(f"{file.name}.wal"), "rotation")
    ]
    if wal_files:
        files = ", ".join(str(file) for file in wal_files)
        raise PublishFailed("wal", f"write-ahead log exists beside {files}")
    on_step("wal-checked")


def rotate(
    candidate_file: Path,
    published_file: Path,
    previous_file: Path,
    on_step: StepObserver,
) -> None:
    """Publish a candidate and retain the previous version for rollback.

    Args:
        candidate_file: The audited candidate database.
        published_file: The public database path.
        previous_file: The one-step rollback database path.
        on_step: Observer called after each completed rotation operation.
    """
    if not _exists(published_file, "rotation"):
        _replace_file(candidate_file, published_file, "rotation")
        on_step("renamed")
        return

    new_file = previous_file.with_name(f"{previous_file.name}.new")
    _link_file(published_file, new_file)
    on_step("previous-linked")
    _replace_file(candidate_file, published_file, "rotation")
    on_step("renamed")
    _replace_file(new_file, previous_file, "rotation")
    on_step("previous-rotated")


def rollback_rename(
    published_file: Path,
    previous_file: Path,
    on_step: StepObserver,
) -> None:
    """Replace the published database with the one-step rollback version.

    Args:
        published_file: The database currently available to readers.
        previous_file: The rollback database to publish.
        on_step: Observer called after the WAL check succeeds.
    """
    if not _exists(previous_file, "rollback"):
        raise PublishFailed("no-previous", f"rollback file does not exist: {previous_file}")
    check_wal(previous_file, published_file, on_step)
    _replace_file(previous_file, published_file, "rollback")


def _unlink_rotation_leftover(file: Path) -> None:
    """Remove a temporary hard link known to name the published file."""
    try:
        file.unlink()
    except OSError as exc:
        raise PublishFailed("rotation", f"could not remove {file}: {exc}") from exc


def _exists(path: Path, reason: str) -> bool:
    """Check whether a path exists, translating unexpected filesystem errors."""
    try:
        os.stat(path)
    except (FileNotFoundError, NotADirectoryError):
        return False
    except OSError as exc:
        raise PublishFailed(reason, f"{path}: {exc}") from exc
    return True


def _link_file(source: Path, destination: Path) -> None:
    """Create the temporary hard link used before replacing a publish."""
    try:
        os.link(source, destination)
    except OSError as exc:
        raise PublishFailed(
            "rotation", f"could not hard-link {source} to {destination}: {exc}"
        ) from exc


def _replace_file(source: Path, destination: Path, reason: str) -> None:
    """Atomically rename a database path while preserving its operation error."""
    try:
        os.replace(source, destination)
    except OSError as exc:
        raise PublishFailed(
            reason, f"could not replace {destination} with {source}: {exc}"
        ) from exc
