"""Refuse a dbt build that would write into a published warehouse file.

`check_warehouse_path` runs before anything opens the DuckDB file a build is about to write. It
opens no file: it only reads symbolic-link and file-identity metadata. `root` is always the top
folder a build writes in (`warehouse` for project builds, the CI folder for `make check`), never a
folder below it. Relative paths resolve against the working directory, which is the repo root for
every `make` recipe.

Run it with
``python -m openrct2_analytics.ingest.warehouse_guard [--project-dir DIR] --root ROOT PATH``;
it prints ``warehouse path refused: <reason>: <path>`` and exits 2, or exits 0.
"""

from __future__ import annotations

import argparse
import os
import stat
import sys
from collections.abc import Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PUBLISHED_NAMES = ("rehearsal.duckdb", "company.duckdb")
REFUSED_EXIT = 2


class UnsafeWarehousePath(Exception):
    """A build path that is a link, a published file, or outside its root."""

    def __init__(self, reason: str, path: str) -> None:
        super().__init__(f"warehouse path refused: {reason}: {path}")
        self.reason = reason


def _published_files(project_dir: Path) -> list[str]:
    warehouse = os.path.realpath(project_dir / "warehouse")
    return [os.path.join(warehouse, name) for name in PUBLISHED_NAMES]


def _listdir(folder: str) -> list[str]:
    return os.listdir(folder) if os.path.isdir(folder) else []


def is_published(path: str | os.PathLike[str], *, project_dir: str | os.PathLike[str]) -> bool:
    """Say whether `path` is a published warehouse file or a rollback copy of one.

    True when the resolved path is `warehouse/rehearsal.duckdb` or `warehouse/company.duckdb` of
    `project_dir`, lies under its `warehouse/previous/`, or exists as the same file (a hard link
    included) as either published file or any file under `previous/`.

    Args:
        path: The DuckDB file a build would write.
        project_dir: The project folder whose `warehouse/` holds the published files.

    Returns:
        True when the path is, or is another name for, a published or previous file.
    """
    resolved = os.path.realpath(path)
    published = _published_files(Path(project_dir))
    previous = os.path.join(os.path.realpath(Path(project_dir) / "warehouse"), "previous")
    if resolved in published or resolved.startswith(previous + os.sep):
        return True
    if not os.path.exists(resolved):
        return False
    kept = [os.path.join(previous, name) for name in _listdir(previous)]
    return any(
        os.path.exists(item) and os.path.samefile(resolved, item) for item in [*published, *kept]
    )


def _is_under(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def _walk_for_links(target: str, path: str) -> None:
    """Raise `symlink` when any component of the absolute `target`, from `/` down, is a link."""
    current = os.sep
    for part in Path(target).parts[1:]:
        current = os.path.join(current, part)
        try:
            mode = os.lstat(current).st_mode
        except FileNotFoundError:
            return  # dbt creates the rest
        if stat.S_ISLNK(mode):
            raise UnsafeWarehousePath("symlink", path)


def check_warehouse_path(
    path: str | os.PathLike[str],
    *,
    root: str | os.PathLike[str],
    project_dir: str | os.PathLike[str],
) -> None:
    """Raise `UnsafeWarehousePath` unless `path` is a safe place for a build to write.

    Paths or roots containing a `..` component are refused as `outside-root` before resolution.
    For other inputs, reasons are checked in order: `symlink` (a link in any component of the
    absolute path from the filesystem root down to `path`, so a link in an ancestor of `root`
    counts), `published` (see `is_published`), `outside-root` (the resolved path is not under the
    resolved `root`). A component that does not exist yet ends the link walk.

    Args:
        path: The DuckDB file a build would write.
        root: The top folder the build writes in.
        project_dir: The project folder whose `warehouse/` holds the published files.

    Raises:
        UnsafeWarehousePath: With the reason in `reason`.
    """
    given = os.fspath(path)
    given_root = os.fspath(root)
    if ".." in Path(given).parts or ".." in Path(given_root).parts:
        raise UnsafeWarehousePath("outside-root", given)
    abs_root = os.path.abspath(given_root)
    abs_path = os.path.abspath(given)
    _walk_for_links(abs_path if _is_under(abs_path, abs_root) else abs_root, given)
    if is_published(abs_path, project_dir=project_dir):
        raise UnsafeWarehousePath("published", given)
    if not _is_under(os.path.realpath(abs_path), os.path.realpath(abs_root)):
        raise UnsafeWarehousePath("outside-root", given)


def main(argv: Sequence[str] | None = None) -> int:
    """Check one path and return a process exit code: 0 safe, 2 refused."""
    parser = argparse.ArgumentParser(description="Refuse unsafe warehouse build paths.")
    parser.add_argument("--project-dir", type=Path, default=REPO_ROOT)
    parser.add_argument("--root", required=True)
    parser.add_argument("path")
    args = parser.parse_args(argv)
    try:
        check_warehouse_path(args.path, root=args.root, project_dir=args.project_dir)
    except UnsafeWarehousePath as refusal:
        print(refusal, file=sys.stderr)
        return REFUSED_EXIT
    return 0


if __name__ == "__main__":
    sys.exit(main())
