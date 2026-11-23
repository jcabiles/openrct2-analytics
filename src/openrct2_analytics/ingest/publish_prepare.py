"""Prepare the publish lock and its isolated candidate folder."""

from __future__ import annotations

import os
import re
import shutil
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime
from pathlib import Path

from openrct2_analytics.ingest.lock import LockTaken, hold_lock
from openrct2_analytics.ingest.publish_errors import PublishFailed, PublishRefused
from openrct2_analytics.ingest.warehouse_guard import (
    UnsafeWarehousePath,
    check_warehouse_path,
)

RUN_ID_PATTERN = r"[A-Za-z0-9-]{1,64}"
ARCHITECTURE_POINTER = 'See ARCHITECTURE.md, "Environments and publishing".'


def check_run_id(run_id: str) -> None:
    """Refuse a run ID that cannot safely name a candidate folder.

    Args:
        run_id: The caller-supplied publish run identifier.

    Raises:
        PublishRefused: If ``run_id`` is not one to 64 letters, digits, or dashes.
    """
    if re.fullmatch(RUN_ID_PATTERN, run_id) is None:
        raise PublishRefused("invalid-run-id", f"invalid run ID: {run_id!r}")


def guard_path(
    path: Path,
    *,
    root: Path,
    project_dir: Path,
    allow: frozenset[str] = frozenset(),
) -> None:
    """Refuse a warehouse path that fails the warehouse path guard.

    Args:
        path: The warehouse path to check.
        root: The top folder the path must be under.
        project_dir: The project folder whose published files must be protected.
        allow: Guard refusal reasons to permit.
    """
    try:
        check_warehouse_path(path, root=root, project_dir=project_dir)
    except UnsafeWarehousePath as error:
        if error.reason in allow:
            return
        raise PublishRefused("unsafe-path", str(error)) from error
    except OSError as error:
        raise PublishFailed("prepare", f"{path}: {error}") from error


def _candidate_dir(project_dir: Path, run_id: str) -> Path:
    return project_dir / "warehouse" / "candidate" / f"run-{run_id}"


def _lock_line(run_id: str) -> str:
    started = datetime.now(UTC).isoformat(timespec="seconds")
    return f"{run_id} {os.getpid()} {started}"


def _lock_refusal(error: LockTaken) -> PublishRefused:
    detail = f"{error.path} is held ({error.line!r}). {ARCHITECTURE_POINTER}"
    return PublishRefused("lock-taken", detail)


def _check_lock_name(name: str) -> None:
    separators = {os.sep}
    if os.altsep is not None:
        separators.add(os.altsep)
    if not name or name in {".", ".."} or any(separator in name for separator in separators):
        raise PublishRefused("unsafe-path", f"lock name {name!r} is not a plain file name")


@contextmanager
def _hold_publish_lock(path: Path, line: str) -> Iterator[None]:
    """Translate a lock acquisition refusal and preserve errors through lock cleanup."""
    stack = ExitStack()
    try:
        stack.enter_context(hold_lock(path, line))
    except LockTaken as error:
        raise _lock_refusal(error) from error
    except OSError as error:
        raise PublishFailed("prepare", f"{path}: {error}") from error

    try:
        yield
    except BaseException as error:
        # Pass body failures through so hold_lock can attach any cleanup error as a note.
        stack.__exit__(type(error), error, error.__traceback__)
        raise
    else:
        try:
            stack.close()
        except OSError as error:
            raise PublishFailed("lock-cleanup", f"{path}: {error}") from error


@contextmanager
def take_lock(
    project_dir: Path,
    name: str,
    run_id: str,
    on_step: Callable[[str], None],
) -> Iterator[None]:
    """Guard the warehouse, create its folders, and hold the data-set lock.

    Args:
        project_dir: Project root containing the warehouse folder.
        name: Data-set name, used for the lock filename.
        run_id: Identifier written in the lock and candidate folder name.
        on_step: Callback called after the lock is acquired.

    Raises:
        PublishRefused: If the run ID, warehouse path, or lock prevents publishing.
    """
    _check_lock_name(name)
    check_run_id(run_id)
    candidate_dir = _candidate_dir(project_dir, run_id)
    guard_path(
        candidate_dir,
        root=project_dir / "warehouse",
        project_dir=project_dir,
    )

    warehouse_dir = project_dir / "warehouse"
    candidate_root = warehouse_dir / "candidate"
    previous_dir = warehouse_dir / "previous"
    try:
        warehouse_dir.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise PublishFailed("prepare", f"{warehouse_dir}: {error}") from error
    try:
        candidate_root.mkdir(exist_ok=True)
    except OSError as error:
        raise PublishFailed("prepare", f"{candidate_root}: {error}") from error
    try:
        previous_dir.mkdir(exist_ok=True)
    except OSError as error:
        raise PublishFailed("prepare", f"{previous_dir}: {error}") from error

    lock_path = warehouse_dir / f"{name}.lock"
    with _hold_publish_lock(lock_path, _lock_line(run_id)):
        on_step("locked")
        yield


def _cleanup(step: Callable[[], object], failure: BaseException | None) -> None:
    """Run cleanup without replacing an error from the context body."""
    try:
        step()
    except OSError as error:
        if failure is None:
            raise PublishFailed("candidate-cleanup", str(error)) from error
        failure.add_note(f"candidate cleanup also failed: {error}")
    except BaseException as error:
        if failure is None:
            raise
        failure.add_note(f"candidate cleanup also failed: {error}")


@contextmanager
def create_candidate(
    project_dir: Path,
    name: str,
    run_id: str,
    on_step: Callable[[str], None],
) -> Iterator[Path]:
    """Create and later remove the run's candidate folder.

    Args:
        project_dir: Project root containing the warehouse folder.
        name: Data-set name, included in candidate refusal details.
        run_id: Identifier used in the candidate folder name.
        on_step: Callback called after creation and successful removal.

    Yields:
        The candidate folder created for this run.

    Raises:
        PublishRefused: If the run ID, candidate path, or existing folder prevents creation.
        PublishFailed: If removing the candidate fails without an earlier error.
    """
    check_run_id(run_id)
    candidate_dir = _candidate_dir(project_dir, run_id)
    guard_path(
        candidate_dir,
        root=project_dir / "warehouse",
        project_dir=project_dir,
    )
    try:
        candidate_dir.mkdir()
    except FileExistsError as error:
        raise PublishRefused(
            "candidate-exists",
            f"{name} candidate folder already exists: {candidate_dir}",
        ) from error
    except OSError as error:
        raise PublishFailed("prepare", f"{candidate_dir}: {error}") from error

    failure: BaseException | None = None
    try:
        on_step("candidate-created")
        yield candidate_dir
    except BaseException as error:
        failure = error
        raise
    finally:
        _cleanup(
            lambda: _remove_candidate(candidate_dir, on_step),
            failure,
        )


def _remove_candidate(candidate_dir: Path, on_step: Callable[[str], None]) -> None:
    # rmtree puts the Path object itself in its OSError; a plain string keeps messages readable.
    shutil.rmtree(os.fspath(candidate_dir))
    on_step("candidate-removed")
